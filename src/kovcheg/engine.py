"""`Kovcheg`: the answering facade used by the CLI and the UI (no UI code here).

Models are loaded lazily on first use; a model that fails to load is reported (status + warnings) and the engine
degrades: no encoder -> BM25 only, no reranker -> fused order, no LLM -> search-only answers with sources.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .generation import Generator, build_prompt, check_citations, load_generator
from .rerank import Reranker, best_rerank, load_reranker, rerank
from .retrieval import IndexCache, ModuleHandle, Retriever, expand_context, matches_any_term, query_terms, select
from .types import Answer

_UNSET: Any = object()
INTEGRITY = ("valid", "unsigned", "untrusted", "invalid", "unknown")


@dataclass
class ModuleInfo:
    name: str
    path: Path
    title: str = ""
    description: str = ""
    language: str = ""
    documents: int = 0
    chunks: int = 0
    encoder_id: str = ""
    integrity: str = "unknown"          # valid | unsigned | untrusted (signed by an unknown key) | invalid | unknown
    integrity_message: str = ""
    signer: str | None = None
    error: str | None = None            # set when the module cannot be opened (legacy, corrupt, ...)

    @property
    def usable(self) -> bool:
        return self.error is None

    @property
    def enabled_by_default(self) -> bool:
        return self.usable and self.integrity != "invalid"


@dataclass
class _Component:
    """Lazy-loaded model slot."""
    configured: str
    loader: Callable[[], Any]
    obj: Any = None
    state: str = "not_loaded"           # disabled | not_loaded | loaded | error
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self) -> Any:
        if self.state in ("loaded", "disabled", "error"):
            return self.obj
        with self.lock:
            if self.state == "not_loaded":
                try:
                    self.obj = self.loader()
                    self.state = "loaded" if self.obj is not None else "disabled"
                except Exception as e:  # noqa: BLE001 - reported, never fatal
                    self.obj, self.state, self.error = None, "error", (str(e) if isinstance(e, FileNotFoundError | ImportError) else f"{type(e).__name__}: {e}")
        return self.obj

    def info(self, path_check: Path | None = None) -> dict:
        d = {"configured": self.configured, "state": self.state, "loaded": self.state == "loaded", "error": self.error,
             "id": getattr(self.obj, "id", None)}
        if self.state == "not_loaded" and path_check is not None and not path_check.exists():
            d["error"] = f"not found: {path_check}"
        return d


def _integrity_of(result: Any) -> tuple[str, str, str | None]:
    """Map whatever `security.verify_module` returns onto (status, message, signer)."""
    msg = str(getattr(result, "message", "") or getattr(result, "reason", "") or "")
    signer = getattr(result, "signer", None) or getattr(result, "key_id", None)
    status = getattr(result, "status", None)
    if isinstance(status, str):
        s = status.lower()
        if s in ("valid", "ok", "verified", "trusted"):
            return "valid", msg, signer
        if s in ("unsigned", "none"):
            return "unsigned", msg, signer
        if s == "untrusted":
            return "untrusted", msg, signer
        if s in ("invalid", "missing_files", "tampered", "bad"):
            return "invalid", msg, signer
        if s == "error":
            return "unknown", msg, signer
    if isinstance(result, tuple) and result:
        ok, *rest = result
        msg = str(rest[0]) if rest else msg
        result = ok
    for attr in ("valid", "ok"):
        v = getattr(result, attr, None)
        if isinstance(v, bool):
            signed = getattr(result, "signed", True)
            return ("valid" if v else ("unsigned" if signed is False else "invalid")), msg, signer
    if result is True:
        return "valid", msg, signer
    if result is False:
        return "invalid", msg, signer
    if result is None:
        return "unsigned", msg or "no signature", signer
    return "unknown", msg, signer


class Kovcheg:
    """Offline QA over the modules of one Kovcheg home. One instance per process; safe to share between threads."""

    def __init__(self, settings: Settings, *, encoder: Any = _UNSET, reranker: Any = _UNSET, generator: Any = _UNSET):
        self.settings = settings
        s = settings
        self._encoder = self._slot(s.embedding.model, lambda: _load_encoder(s), encoder)
        self._reranker = self._slot(s.rerank.model if s.rerank.enabled else "", lambda: load_reranker(s), reranker)
        self._llm = self._slot(s.llm.model, lambda: load_generator(s), generator)
        self._indexes = IndexCache()
        self._integrity: dict[tuple, tuple[str, str, str | None]] = {}
        self._enc_lock, self._rr_lock, self._llm_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self._retriever: Retriever | None = None
        self._retriever_enc: Any = None

    @staticmethod
    def _slot(configured: str, loader: Callable[[], Any], injected: Any) -> _Component:
        c = _Component(configured or "", loader)
        if injected is not _UNSET:
            c.obj, c.state = injected, ("loaded" if injected is not None else "disabled")
        elif not configured:
            c.state = "disabled"
        return c

    @classmethod
    def from_home(cls, home: str | Path | None = None, overrides: dict | None = None, **models: Any) -> Kovcheg:
        return cls(load_settings(home, overrides), **models)

    # ---- models -------------------------------------------------------------------------------------------------
    @property
    def encoder(self):
        return self._encoder.get()

    @property
    def reranker(self) -> Reranker | None:
        return self._reranker.get()

    @property
    def generator(self) -> Generator | None:
        return self._llm.get()

    def load_models(self, llm: bool = True) -> list[str]:
        """Load configured models now (e.g. at UI start); returns error messages."""
        slots = [self._encoder, self._reranker] + ([self._llm] if llm else [])
        for slot in slots:
            slot.get()
        return [f"{n}: {c.error}" for n, c in zip(("encoder", "reranker", "llm"), slots, strict=False) if c.error]

    def _model_warnings(self) -> list[str]:
        out = []
        for name, c in (("embedding model", self._encoder), ("reranker", self._reranker), ("LLM", self._llm)):
            if c.state == "error":
                out.append(f"{name} unavailable ({c.error})")
        return out

    def _get_retriever(self) -> Retriever:
        enc = self.encoder
        if self._retriever is None or self._retriever_enc is not enc:
            self._retriever = Retriever(self.settings, _Locked(enc, self._enc_lock) if enc is not None else None)
            self._retriever_enc = enc
        return self._retriever

    # ---- modules ------------------------------------------------------------------------------------------------
    def module_names(self) -> list[str]:
        d = self.settings.modules_dir
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir()
                      if p.is_dir() and not p.name.startswith(".") and not p.name.endswith((".tmp", ".old", ".bak", ".work")))

    def integrity(self, name: str) -> tuple[str, str, str | None]:
        """(status, message, signer) of a module; deep check, cached per file state."""
        from .retrieval import _stamp
        path = self.settings.modules_dir / name
        key = (name, _stamp(path))
        if key in self._integrity:
            return self._integrity[key]
        try:
            from .security import verify_module
        except ImportError as e:
            res = ("unknown", f"verification unavailable ({e})", None)
        else:
            try:
                res = _integrity_of(verify_module(path, self.settings.keys_dir, deep=True))
            except Exception as e:  # noqa: BLE001
                res = ("unknown", f"verification failed: {type(e).__name__}: {e}", None)
        self._integrity[key] = res
        return res

    def modules(self, verify: bool = True) -> list[ModuleInfo]:
        out = []
        for name in self.module_names():
            path = self.settings.modules_dir / name
            info = ModuleInfo(name=name, path=path)
            try:
                ix = self._indexes.get(path).index
                m = ix.manifest or {}
                info.title, info.description, info.language = m.get("title") or name, m.get("description", ""), m.get("language", "")
                info.chunks, info.encoder_id = ix.n_chunks, ix.encoder_id or ""
                info.documents = int((m.get("stats") or {}).get("documents") or 0) or len(ix.documents())
            except Exception as e:  # noqa: BLE001
                info.error = str(e)
            if verify and info.error is None:
                info.integrity, info.integrity_message, info.signer = self.integrity(name)
            out.append(info)
        return out

    def _handles(self, modules: Sequence[str] | None, warnings: list[str]) -> list[ModuleHandle]:
        if modules is None:
            names = [m.name for m in self.modules() if m.enabled_by_default]
        else:
            names = list(dict.fromkeys(modules))
        handles = []
        for n in names:
            path = self.settings.modules_dir / n
            if not path.is_dir():
                warnings.append(f"module '{n}' not found")
                continue
            try:
                handles.append(self._indexes.get(path))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"module '{n}' cannot be opened: {e}")
                continue
            if modules is not None:
                status, msg, _ = self.integrity(n)
                if status == "invalid":
                    warnings.append(f"module '{n}' FAILED integrity verification ({msg}); its content may have been altered")
        return handles

    def reload(self) -> None:
        """Forget opened modules and integrity results (models stay loaded)."""
        self._indexes.clear()
        self._integrity.clear()

    def close(self) -> None:
        self._indexes.clear()

    # ---- status -------------------------------------------------------------------------------------------------
    def status(self, verify: bool = True) -> dict:
        s = self.settings
        enc_path = s.path(s.embedding.model) if s.embedding.model and not s.embedding.model.startswith("hashing") else None
        rr_path = s.path(s.rerank.model) if s.rerank.enabled and s.rerank.model else None
        llm_path = s.path(s.llm.model) if s.llm.model and s.llm.model != "echo" else None
        mods = self.modules(verify=verify)
        return {
            "home": str(s.home),
            "encoder": self._encoder.info(enc_path),
            "reranker": self._reranker.info(rr_path),
            "llm": self._llm.info(llm_path),
            "modules": [{"name": m.name, "title": m.title, "documents": m.documents, "chunks": m.chunks, "encoder_id": m.encoder_id,
                         "integrity": m.integrity, "integrity_message": m.integrity_message, "signer": m.signer, "error": m.error}
                        for m in mods],
            "warnings": self._model_warnings(),
        }

    # ---- search / ask -------------------------------------------------------------------------------------------
    def search(self, question: str, modules: Sequence[str] | None = None, top_k: int | None = None, *, use_reranker: bool = True,
               expand: bool = True) -> Answer:
        """Retrieve sources without generating. status: ok | no_evidence."""
        t0 = time.perf_counter()
        ans = self._retrieve(question, modules, top_k, use_reranker, expand)
        ans.timings["total"] = time.perf_counter() - t0
        return ans

    def _retrieve(self, question: str, modules: Sequence[str] | None, top_k: int | None, use_reranker: bool, expand: bool) -> Answer:
        s = self.settings
        top_k = top_k or s.retrieval.top_k
        warnings: list[str] = []
        question = question.strip()
        if not question:
            return Answer(question, "", [], status="no_evidence", warnings=["empty question"])
        handles = self._handles(modules, warnings)
        if not handles:
            warnings.append("no modules selected or available")
            return Answer(question, "", [], status="no_evidence", warnings=warnings + self._model_warnings())
        retriever = self._get_retriever()
        rr = self.reranker if use_reranker else None
        pool = max(top_k, s.rerank.top_n if rr is not None else 0) * 2
        res = retriever.candidates(question, handles, pool)
        warnings += res.warnings
        timings = dict(res.timings)
        hits = res.hits
        if rr is not None and hits:
            t = time.perf_counter()
            try:
                with self._rr_lock:
                    hits = rerank(rr, question, hits, s.rerank.top_n)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"reranking failed ({type(e).__name__}: {e}); using fused order")
            timings["rerank"] = time.perf_counter() - t
        hits = select(hits, top_k, s.retrieval.max_per_document)
        status = "ok"
        best = best_rerank(hits)
        if not hits:
            status = "no_evidence"
        elif best is not None and best < s.rerank.min_score:
            status = "no_evidence"
            warnings.append(f"best reranker score {best:.2f} is below rerank.min_score {s.rerank.min_score}: no relevant passage found")
        elif best is None and not any("dense" in r for r in res.retrievers.values()):
            # keyword-only retrieval and no reranker: an OR query matches almost anything through a single common word, so
            # require that at least one content word of the question (allowing for inflection) occurs in some source
            terms = query_terms(question)
            if not any(matches_any_term(terms, h.chunk) for h in hits):
                status = "no_evidence"
                warnings.append("no source contains any content word of the question: no relevant passage found")
        if expand and hits:
            t = time.perf_counter()
            expand_context(hits, {h.name: h for h in handles}, s.retrieval.context_neighbors)
            timings["expand"] = time.perf_counter() - t
        return Answer(question, "", hits, status=status, warnings=list(dict.fromkeys(warnings + self._model_warnings())), timings=timings)

    def ask_stream(self, question: str, modules: Sequence[str] | None = None, top_k: int | None = None, *,
                   search_only: bool = False, use_reranker: bool = True) -> Iterator[str | Answer]:
        """Yield answer text deltas (str) as they are generated, then the final `Answer`.

        The LLM is called only when retrieval found evidence. Answer.hits[i] is source [i + 1].
        """
        t0 = time.perf_counter()
        ans = self._retrieve(question, modules, top_k, use_reranker, expand=True)
        if ans.status == "no_evidence":
            ans.timings["total"] = time.perf_counter() - t0
            yield ans
            return
        if search_only or self._llm.state == "disabled":
            ans.status = "search_only"
            ans.timings["total"] = time.perf_counter() - t0
            yield ans
            return
        gen = self.generator
        if gen is None:
            ans.status = "llm_unavailable"
            ans.warnings = list(dict.fromkeys(ans.warnings + self._model_warnings()))
            ans.timings["total"] = time.perf_counter() - t0
            yield ans
            return
        prompt = build_prompt(ans.question, ans.hits, context_window=gen.context_window, max_tokens=gen.max_tokens, count=gen.count_tokens)
        ans.warnings += prompt.trimmed
        t = time.perf_counter()
        parts: list[str] = []
        try:
            with self._llm_lock:
                for delta in gen.stream(prompt.messages):
                    parts.append(delta)
                    yield delta
        except Exception as e:  # noqa: BLE001 - keep sources, report the failure
            ans.status = "error"
            ans.warnings.append(f"generation failed: {type(e).__name__}: {e}")
        ans.timings["generate"] = time.perf_counter() - t
        ans.text = "".join(parts).strip()
        if ans.text:
            ans.citations, cw = check_citations(ans.text, ans.hits, prompt.n_sources)
            ans.warnings += cw
        elif ans.status == "ok":
            ans.status = "error"
            ans.warnings.append("the model returned an empty answer")
        ans.timings["total"] = time.perf_counter() - t0
        yield ans

    def ask(self, question: str, modules: Sequence[str] | None = None, top_k: int | None = None, *, search_only: bool = False,
            use_reranker: bool = True, on_token: Callable[[str], None] | None = None) -> Answer:
        """Answer a question; `on_token` receives text deltas while the model generates."""
        final: Answer | None = None
        for item in self.ask_stream(question, modules, top_k, search_only=search_only, use_reranker=use_reranker):
            if isinstance(item, Answer):
                final = item
            elif on_token is not None:
                on_token(item)
        assert final is not None
        return final


class _Locked:
    """Serialises calls to a shared encoder (models are not guaranteed thread-safe)."""

    def __init__(self, inner: Any, lock: threading.Lock):
        self._inner, self._lock = inner, lock
        self.id, self.dim, self.has_sparse = inner.id, inner.dim, inner.has_sparse

    def encode(self, texts, *, query: bool = False):
        with self._lock:
            return self._inner.encode(texts, query=query)


def _load_encoder(settings: Settings):
    from .embedding import load_encoder
    return load_encoder(settings)
