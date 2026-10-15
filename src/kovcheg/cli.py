"""`kovcheg` command line. Standard library + numpy only; optional features import their libraries lazily.

Exit codes: 0 ok, 1 error, 2 usage, 3 no evidence (nothing relevant found), 4 missing component (module, model,
optional library, key).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from . import __version__

OK, ERROR, USAGE, NO_EVIDENCE, MISSING = 0, 1, 2, 3, 4
DISCLAIMER = "Kovcheg can be wrong. In life-threatening situations follow official protocols and call emergency services."

# What a person reads next to an answer follows the interface language ([ui] language); diagnostics stay in English.
MESSAGES = {
    "en": {"disclaimer": DISCLAIMER, "sources": "Sources:", "closest": "Closest passages (low relevance, not an answer):",
           "no_evidence": "The selected modules contain nothing relevant to this question; Kovcheg will not guess an answer.",
           "no_passages": "No relevant passages found in the selected modules.",
           "search_only": "Search-only mode (no language model configured): the most relevant passages are listed below.",
           "llm_unavailable": "The language model is unavailable; the most relevant passages are listed below."},
    "uk": {"disclaimer": "Ковчег може помилятися. У ситуаціях, що загрожують життю, дійте за офіційними протоколами й викликайте "
                         "екстрені служби.",
           "sources": "Джерела:", "closest": "Найближчі фрагменти (низька релевантність, це не відповідь):",
           "no_evidence": "У вибраних модулях немає нічого релевантного для цього питання; Ковчег не вгадуватиме відповідь.",
           "no_passages": "У вибраних модулях не знайдено релевантних фрагментів.",
           "search_only": "Режим пошуку (мовну модель не налаштовано): нижче — найрелевантніші фрагменти.",
           "llm_unavailable": "Мовна модель недоступна; нижче — найрелевантніші фрагменти."},
}


def msg(settings, key: str) -> str:
    return MESSAGES.get(getattr(settings.ui, "language", "en"), MESSAGES["en"])[key]

CONFIG_TEMPLATE = """\
# Kovcheg settings. Every key is optional; the values shown are the defaults.
# Paths are relative to this folder (the Kovcheg home).

[embedding]
# model = "models/bge-m3"            # local copy of BAAI/bge-m3; "" = keyword (BM25) search only
# device = "cpu"

[rerank]
# model = "models/bge-reranker-v2-m3"
# enabled = true
# top_n = 20                         # candidates scored by the cross-encoder (time grows linearly)
# min_score = -6.0                   # below this logit the library is considered to have no answer

[llm]
# model = ""                         # path to a .gguf file, e.g. "models/qwen2.5-1.5b-instruct-q4_k_m.gguf"; "" = search only
# context_window = 4096
# max_tokens = 600
# temperature = 0.1
# threads = 0                        # 0 = all physical cores

[retrieval]
# top_k = 8                          # sources shown and given to the LLM
# candidates = 50
# max_per_document = 3
# context_neighbors = 1
# weights = { dense = 1.0, sparse = 0.6, bm25 = 0.8 }

[chunking]
# target_chars = 1000
# max_chars = 1600

[ui]
# host = "127.0.0.1"                 # "0.0.0.0" serves phones and laptops on the local network
# port = 8501
# language = "uk"                    # uk | en
"""

OPTIONAL_LIBS = {
    "FlagEmbedding": "BGE-M3 embeddings and reranker (extra: embed)",
    "torch": "PyTorch, needed by FlagEmbedding",
    "llama_cpp": "local LLM (extra: llm)",
    "streamlit": "web interface (extra: ui)",
    "pdfplumber": "PDF reading with layout (extra: docs)",
    "pypdf": "PDF reading fallback (extra: docs)",
    "docx": "DOCX reading, python-docx (extra: docs)",
    "libzim": "Wikipedia ZIM files, GPL-3.0 (extra: zim)",
    "cryptography": "module signatures (extra: sign)",
}


class UsageError(Exception):
    pass


# ---- helpers ------------------------------------------------------------------------------------------------------

def parse_set(items: list[str] | None) -> dict:
    """`--set llm.model=x.gguf --set retrieval.top_k=5` -> nested overrides dict (values parsed as TOML when possible)."""
    out: dict = {}
    for item in items or []:
        if "=" not in item:
            raise UsageError(f"--set expects KEY=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            value = tomllib.loads(f"v = {raw}")["v"]
        except tomllib.TOMLDecodeError:
            value = raw
        parts = key.strip().split(".")
        d = out
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = value
    return out


def _settings(args):
    from .config import load_settings
    try:
        return load_settings(args.home, parse_set(args.set))
    except (ValueError, tomllib.TOMLDecodeError) as e:
        raise UsageError(f"bad settings: {e}") from e


def _engine(args, settings=None):
    from .engine import Kovcheg
    return Kovcheg(settings or _settings(args))


def _err(msg: str) -> None:
    print(f"kovcheg: {msg}", file=sys.stderr)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _snippet(text: str, n: int = 240) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def _module_args(args) -> list[str] | None:
    return list(args.module) if args.module else None


def _print_sources(ans, settings, *, file=None) -> None:
    from .rerank import sigmoid
    from .retrieval import focused_snippet
    file = file or sys.stdout
    if not ans.hits:
        return
    print("\n" + msg(settings, "closest" if ans.status == "no_evidence" else "sources"), file=file)
    for i, h in enumerate(ans.hits, 1):
        rel = f"  relevance {sigmoid(h.rerank):.0%}" if h.rerank is not None else ""
        print(f"[{i}] {h.chunk.citation}  ({h.chunk.module}: {h.chunk.doc_path}){rel}", file=file)
        print(f"    {focused_snippet(h.chunk.text, ans.question)}", file=file)


def _print_warnings(ans) -> None:
    for w in ans.warnings:
        print(f"warning: {w}", file=sys.stderr)


def _human_size(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _path_size(p: Path) -> int | None:
    if p.is_file():
        return p.stat().st_size
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return None


# ---- commands -----------------------------------------------------------------------------------------------------

def cmd_init(args) -> int:
    from .config import resolve_home
    home = resolve_home(args.home)
    for d in ("models", "modules", "sources", "keys/trusted"):
        (home / d).mkdir(parents=True, exist_ok=True)
    cfg = home / "kovcheg.toml"
    if cfg.exists():
        print(f"{cfg} exists; left unchanged")
    else:
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        print(f"created {cfg}")
    print(f"Kovcheg home ready: {home}\n  put documents in {home / 'sources' / '<module>'}/ and run: kovcheg build <module>")
    return OK


def cmd_build(args) -> int:
    try:
        from .builder import BuildError, build_module
    except ImportError as e:
        _err(f"indexing is not available: {e}")
        return MISSING
    s = _settings(args)
    last = [0.0]

    def progress(stage: str, done: int, total: int | None, item: str) -> None:
        now = time.monotonic()
        if args.quiet or (now - last[0] < 0.5 and stage == "index"):
            return
        last[0] = now
        tot = f"/{total}" if total else ""
        print(f"\r[{stage}] {done}{tot} {_snippet(item, 60):<60}", end="", file=sys.stderr, flush=True)

    try:
        rep = build_module(s, args.name, Path(args.source) if args.source else None, title=args.title, description=args.description,
                           language=args.language, rebuild=args.rebuild, encoder=None if args.no_embed else "auto", progress=progress)
    except (BuildError, ValueError) as e:
        print(file=sys.stderr)
        _err(str(e))
        return ERROR
    except (ImportError, FileNotFoundError) as e:
        print(file=sys.stderr)
        _err(f"{e}\n  (use --no-embed to build a keyword-only module without the embedding model)")
        return MISSING
    except KeyboardInterrupt:
        print(file=sys.stderr)
        _err("interrupted; the previous version of the module is unchanged")
        return ERROR
    print(file=sys.stderr)
    print(rep.summary())
    for path, reason in rep.skipped:
        print(f"  skipped {path}: {reason}")
    for m in rep.messages:
        print(f"  {m}")
    if rep.signed_by:
        print(f"  signed with key {rep.signed_by}")
    return OK


def answer_dict(ans) -> dict:
    from .rerank import sigmoid
    return {
        "question": ans.question, "status": ans.status, "answer": ans.text,
        "sources": [{"n": i, "module": h.chunk.module, "path": h.chunk.doc_path, "title": h.chunk.doc_title, "page": h.chunk.page,
                     "section": h.chunk.section, "citation": h.chunk.citation, "chunk_id": h.chunk.id, "text": h.chunk.text,
                     "context": [c.text for c in h.context], "score": h.score, "dense": h.dense, "sparse": h.sparse, "bm25": h.bm25,
                     "rerank": h.rerank, "relevance": sigmoid(h.rerank)} for i, h in enumerate(ans.hits, 1)],
        "citations": [{"n": c.number, "valid": c.valid} for c in ans.citations],
        "warnings": ans.warnings, "timings": {k: round(v, 4) for k, v in ans.timings.items()},
    }


def _status_code(ans) -> int:
    return {"ok": OK, "search_only": OK, "no_evidence": NO_EVIDENCE, "llm_unavailable": MISSING}.get(ans.status, ERROR)


def _check_modules(k, names: list[str] | None) -> int | None:
    available = set(k.module_names())
    if names:
        missing = [m for m in names if m not in available]
        if missing:
            _err(f"module(s) not found: {', '.join(missing)} (available: {', '.join(sorted(available)) or 'none'})")
            return MISSING
    elif not available:
        _err(f"no modules in {k.settings.modules_dir}; build one with: kovcheg build NAME")
        return MISSING
    return None


def cmd_search(args) -> int:
    k = _engine(args)
    if (rc := _check_modules(k, _module_args(args))) is not None:
        return rc
    ans = k.search(" ".join(args.question), _module_args(args), args.top_k, use_reranker=not args.no_rerank)
    if args.json:
        _print_json(answer_dict(ans))
    else:
        _print_warnings(ans)
        if ans.status == "no_evidence":
            print(msg(k.settings, "no_passages"))
        _print_sources(ans, k.settings)
    return _status_code(ans)


def cmd_ask(args) -> int:
    k = _engine(args)
    if (rc := _check_modules(k, _module_args(args))) is not None:
        return rc
    question = " ".join(args.question)
    streamed = [False]

    def on_token(t: str) -> None:
        streamed[0] = True
        print(t, end="", flush=True)

    ans = k.ask(question, _module_args(args), args.top_k, search_only=args.search_only, use_reranker=not args.no_rerank,
                on_token=None if args.json else on_token)
    if args.json:
        _print_json(answer_dict(ans))
        return _status_code(ans)
    if streamed[0]:
        print()
    if ans.status == "no_evidence":
        print(msg(k.settings, "no_evidence"))
    elif ans.status == "search_only":
        print(msg(k.settings, "search_only"))
    elif ans.status == "llm_unavailable":
        print(msg(k.settings, "llm_unavailable"))
    _print_sources(ans, k.settings)
    _print_warnings(ans)
    if ans.status in ("ok", "search_only"):
        print("\n" + msg(k.settings, "disclaimer"))
    return _status_code(ans)


def build_ui_command(settings, host: str | None = None, port: int | None = None) -> list[str]:
    app = Path(__file__).resolve().parent / "ui" / "app.py"
    return [sys.executable, "-m", "streamlit", "run", str(app),
            "--server.headless", "true", "--server.fileWatcherType", "none", "--browser.gatherUsageStats", "false",
            "--client.toolbarMode", "minimal",   # no "Deploy" button or developer menu in an offline tool
            "--server.address", host or settings.ui.host, "--server.port", str(port or settings.ui.port),
            "--", "--home", str(settings.home)]


def cmd_ui(args) -> int:
    if importlib.util.find_spec("streamlit") is None:
        _err('the web interface needs streamlit: pip install "kovcheg[ui]"')
        return MISSING
    s = _settings(args)
    cmd = build_ui_command(s, args.host, args.port)
    env = dict(os.environ, KOVCHEG_HOME=str(s.home))
    if args.set:
        env["KOVCHEG_OVERRIDES"] = json.dumps(parse_set(args.set))
    host, port = args.host or s.ui.host, args.port or s.ui.port
    print(f"Kovcheg web interface: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}  (Ctrl-C to stop)")
    if host == "0.0.0.0":
        print("  serving on all network interfaces: anyone on this network can use it")
    sys.stdout.flush()
    try:
        return subprocess_call(cmd, env)
    except KeyboardInterrupt:
        return OK


def subprocess_call(cmd: list[str], env: dict) -> int:
    import subprocess
    return subprocess.call(cmd, env=env)


def cmd_modules(args) -> int:
    k = _engine(args)
    mods = k.modules(verify=not args.no_verify)
    if args.json:
        _print_json([{**m.__dict__, "path": str(m.path)} for m in mods])
        return OK
    if not mods:
        print(f"no modules in {k.settings.modules_dir}")
        return OK
    w = max(len(m.name) for m in mods)
    for m in mods:
        if m.error:
            print(f"{m.name:<{w}}  ERROR  {m.error}")
            continue
        print(f"{m.name:<{w}}  {m.integrity.upper():<9}  {m.documents:>6} docs  {m.chunks:>8} chunks  "
              f"encoder={m.encoder_id or 'none (BM25 only)'}  {m.title if m.title != m.name else ''}")
    return OK


def cmd_inspect(args) -> int:
    s = _settings(args)
    path = s.modules_dir / args.name
    if not path.is_dir():
        _err(f"module not found: {path}")
        return MISSING
    from .store import ModuleFormatError, ModuleIndex
    try:
        ix = ModuleIndex.open(path)
    except ModuleFormatError as e:
        _err(str(e))
        return ERROR
    try:
        docs = ix.documents()
        files = {f.name: f.stat().st_size for f in sorted(path.iterdir()) if f.is_file()}
        info = {"name": args.name, "path": str(path), "manifest": ix.manifest, "chunks": ix.n_chunks, "encoder_id": ix.encoder_id,
                "dim": ix.dim, "has_dense": ix.has_dense, "has_sparse": ix.has_sparse, "files": files, "documents": docs}
    finally:
        ix.close()
    if args.json:
        _print_json(info)
        return OK
    m = info["manifest"]
    print(f"{args.name}: {m.get('title') or args.name}")
    if m.get("description"):
        print(f"  {m['description']}")
    dim = f" ({info['dim']}-d)" if info["dim"] else ""
    print(f"  {len(docs)} documents, {info['chunks']} chunks; encoder {info['encoder_id'] or 'none (BM25 only)'}{dim}; "
          f"dense={info['has_dense']} sparse={info['has_sparse']}")
    print(f"  updated {m.get('updated_at', '?')}, kovcheg {m.get('kovcheg_version', '?')}, signer {m.get('signer') or '-'}")
    for name, size in files.items():
        print(f"  {name:<16} {_human_size(size)}")
    print("  documents:")
    for d in docs[: args.limit]:
        print(f"    {d['path']}  ({d.get('n_chunks') or 0} chunks, {d.get('kind') or '?'})")
    if len(docs) > args.limit:
        print(f"    … {len(docs) - args.limit} more (use --limit)")
    return OK


def cmd_verify(args) -> int:
    try:
        from .security import verify_module
    except ImportError as e:
        _err(f"verification is not available: {e}")
        return MISSING
    s = _settings(args)
    from .engine import _integrity_of
    k = _engine(args, s)
    names = [args.name] if args.name else k.module_names()
    if args.name and not (s.modules_dir / args.name).is_dir():
        _err(f"module not found: {args.name}")
        return MISSING
    worst = OK
    for n in names:
        v = verify_module(s.modules_dir / n, s.keys_dir, deep=not args.quick, use_cache=False)   # explicit check: always re-hash
        status, msg, _ = _integrity_of(v)
        print(f"{n}: {status.upper()} — {msg}")
        if status == "invalid":
            worst = ERROR
    return worst


def cmd_keygen(args) -> int:
    try:
        from .security import keygen
    except ImportError as e:
        _err(f"signing is not available: {e}")
        return MISSING
    s = _settings(args)
    try:
        info = keygen(s.keys_dir, force=args.force)
    except ImportError as e:
        _err(str(e))
        return MISSING
    except FileExistsError as e:
        _err(f"{e} (use --force to replace)")
        return ERROR
    print(f"key {info.key_id}\n  private: {info.private_path} (keep secret)\n  public:  {info.public_path} (share with users)")
    return OK


def cmd_sign(args) -> int:
    try:
        from .security import sign_module
    except ImportError as e:
        _err(f"signing is not available: {e}")
        return MISSING
    s = _settings(args)
    path = s.modules_dir / args.name
    if not path.is_dir():
        _err(f"module not found: {path}")
        return MISSING
    try:
        kid = sign_module(path, s.keys_dir)
    except (ImportError, FileNotFoundError) as e:
        _err(f"{e} (create a key with: kovcheg keygen)")
        return MISSING
    print(f"{args.name}: signed with key {kid}")
    return OK


def cmd_migrate(args) -> int:
    try:
        from .migrate import migrate_module
    except ImportError as e:
        _err(f"migration is not available: {e}")
        return MISSING
    s = _settings(args)
    path = s.modules_dir / args.name
    if not path.is_dir():
        _err(f"module not found: {path}")
        return MISSING
    try:
        rep = migrate_module(path, delete_old=args.delete_old, keys_dir=s.keys_dir)
    except (FileNotFoundError, FileExistsError) as e:
        _err(str(e))
        return ERROR
    print(f"{args.name}: migrated to format v2 — {rep.documents} documents, {rep.chunks} chunks"
          + (f", {rep.duplicates_removed} duplicates removed" if rep.duplicates_removed else ""))
    for m in rep.messages:
        print(f"  {m}")
    return OK


def _ram() -> tuple[int | None, int | None]:
    """(total, available) bytes."""
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) * 1024
        return info.get("MemTotal"), info.get("MemAvailable")
    except (OSError, ValueError):
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"), None
    except (ValueError, OSError, AttributeError):
        return None, None


def recommend(ram_bytes: int | None) -> dict:
    """Hardware tier for the machine's RAM (same tiers as the README and examples/tier-*.toml)."""
    gb = (ram_bytes or 0) / 2**30
    if gb and gb < 3:
        return {"tier": "S — search", "note": "keyword (BM25) search only; no models fit comfortably (examples/tier-s-search.toml)",
                "settings": {"embedding.model": "", "rerank.enabled": False, "llm.model": ""}}
    if gb and gb < 6:
        return {"tier": "A (lite)", "note": "BGE-M3 search; reranker off; search only or a ~1.5B instruct model in Q4_K_M with a short context",
                "settings": {"rerank.enabled": False, "llm.context_window": 2048, "llm.max_tokens": 400}}
    if not gb or gb < 12:
        return {"tier": "A — mini PC", "note": "BGE-M3 + a ~1.5B instruct model in Q4_K_M, reranker off (e.g. Intel N100, 8 GB; "
                "examples/tier-a-minipc.toml)", "settings": {"rerank.enabled": False, "llm.context_window": 4096, "llm.max_tokens": 500}}
    return {"tier": "B — laptop", "note": "BGE-M3 + reranker + a 3.8-7B instruct model in Q4_K_M (examples/tier-b-laptop.toml)",
            "settings": {"rerank.enabled": True, "rerank.top_n": 20, "llm.context_window": 8192, "llm.max_tokens": 700}}


def doctor_report(args) -> dict:
    s = _settings(args)
    total, avail = _ram()
    try:
        du = shutil.disk_usage(s.home)
        disk = {"total": du.total, "free": du.free}
    except OSError:
        disk = {}
    libs = {}
    for name, what in OPTIONAL_LIBS.items():
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        libs[name] = {"installed": found, "purpose": what}
    models = {}
    for key, model, enabled in (("embedding", s.embedding.model, True), ("reranker", s.rerank.model, s.rerank.enabled),
                                ("llm", s.llm.model, True)):
        if not model or not enabled:
            models[key] = {"configured": model, "enabled": False}
        elif model.startswith("hashing") or model == "echo":
            models[key] = {"configured": model, "enabled": True, "note": "test-only model, not for real use"}
        else:
            p = s.path(model)
            models[key] = {"configured": model, "enabled": True, "path": str(p), "exists": p.exists(), "size": _path_size(p)}
    modules = []
    try:
        from .engine import Kovcheg
        for m in Kovcheg(s).modules(verify=not args.quick):
            modules.append({"name": m.name, "integrity": m.integrity, "message": m.integrity_message, "documents": m.documents,
                            "chunks": m.chunks, "encoder_id": m.encoder_id, "error": m.error})
    except Exception as e:  # noqa: BLE001 - doctor must always print something
        modules.append({"name": "?", "error": f"{type(e).__name__}: {e}"})
    return {"kovcheg": __version__, "python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "cpus": os.cpu_count(), "ram": {"total": total, "available": avail}, "disk": disk, "home": str(s.home),
            "config": str(s.home / "kovcheg.toml") if (s.home / "kovcheg.toml").exists() else None,
            "libraries": libs, "models": models, "modules": modules, "recommended": recommend(total)}


def cmd_doctor(args) -> int:
    r = doctor_report(args)
    if args.json:
        _print_json(r)
        return OK
    print(f"Kovcheg {r['kovcheg']} on Python {r['python']} — {r['platform']}")
    print(f"CPU: {r['cpus']} threads ({r['machine']}); RAM: {_human_size(r['ram']['total'])} total, "
          f"{_human_size(r['ram']['available'])} available; disk free: {_human_size(r['disk'].get('free'))}")
    print(f"home: {r['home']}  (settings: {r['config'] or 'defaults'})")
    print("optional libraries:")
    for name, d in r["libraries"].items():
        print(f"  {'+' if d['installed'] else '-'} {name:<14} {d['purpose']}")
    print("models:")
    for key, d in r["models"].items():
        if not d["enabled"]:
            print(f"  {key:<10} disabled")
        elif "path" in d:
            print(f"  {key:<10} {'OK ' if d['exists'] else 'MISSING'} {d['path']} ({_human_size(d['size'])})")
        else:
            print(f"  {key:<10} {d['configured']} ({d.get('note', '')})")
    print("modules:")
    if not r["modules"]:
        print("  none")
    for m in r["modules"]:
        print(f"  {m['name']}: " + (f"ERROR {m['error']}" if m.get("error") else
                                    f"{m['integrity'].upper()}, {m['documents']} docs, {m['chunks']} chunks, encoder {m['encoder_id'] or 'none'}"))
    rec = r["recommended"]
    print(f"recommended tier: {rec['tier']} — {rec['note']}")
    for k, v in rec["settings"].items():
        print(f"  {k} = {json.dumps(v)}")
    return OK


def _matches(hit, expected: list[str]) -> bool:
    c = hit.chunk
    for e in expected:
        mod, _, path = e.rpartition(":") if ":" in e and not e.startswith(("http:", "https:")) else ("", "", e)
        if mod and mod != c.module:
            continue
        if c.doc_path == path or c.doc_path.endswith("/" + path) or (c.doc_title and c.doc_title == path):
            return True
    return False


def run_eval(k, items: list[dict], top_k: int, modules: list[str] | None, use_reranker: bool) -> dict:
    """hit@1/3/k and MRR@k of retrieval against expected document paths (`path`, `module:path` or a title)."""
    rows = []
    for it in items:
        exp = it.get("expected") or it.get("expected_docs") or it.get("doc") or []
        exp = [exp] if isinstance(exp, str) else list(exp)
        ans = k.search(it["question"], it.get("modules") or modules, top_k, use_reranker=use_reranker, expand=False)
        rank = next((i for i, h in enumerate(ans.hits, 1) if _matches(h, exp)), None)
        rows.append({"question": it["question"], "expected": exp, "rank": rank, "top": [h.chunk.doc_path for h in ans.hits[:3]],
                     "seconds": round(ans.timings.get("total", 0.0), 4)})
    n = len(rows) or 1

    def hit(m: int) -> float:
        return sum(1 for r in rows if r["rank"] and r["rank"] <= m) / n
    return {"n": len(rows), "k": top_k, "hit@1": hit(1), "hit@3": hit(3), f"hit@{top_k}": hit(top_k),
            "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n, "items": rows}


def cmd_eval(args) -> int:
    path = Path(args.file)
    if not path.is_file():
        _err(f"file not found: {path}")
        return MISSING
    items = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("#"):
            try:
                obj = json.loads(line)
                obj["question"]
            except (ValueError, KeyError, TypeError) as e:
                raise UsageError(f"{path}:{i}: expected a JSON object with 'question' and 'expected' ({e})") from e
            items.append(obj)
    k = _engine(args)
    if (rc := _check_modules(k, _module_args(args))) is not None:
        return rc
    top_k = args.top_k or k.settings.retrieval.top_k
    res = run_eval(k, items, top_k, _module_args(args), not args.no_rerank)
    if args.json:
        _print_json(res)
        return OK
    for r in res["items"]:
        mark = "MISS" if r["rank"] is None else f"@{r['rank']}"
        print(f"{mark:>5}  {r['question']}")
    ks = sorted({1, 3, top_k})
    print(f"\n{res['n']} questions: " + "  ".join(f"hit@{k} {res[f'hit@{k}']:.3f}" for k in ks) + f"  MRR {res['mrr']:.3f}")
    return OK


# ---- parser -------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    def common_args(default: Any) -> argparse.ArgumentParser:
        c = argparse.ArgumentParser(add_help=False)
        c.add_argument("--home", default=default, help="Kovcheg home folder (default: $KOVCHEG_HOME or the current folder)")
        c.add_argument("--set", action="append", default=default, metavar="KEY=VALUE",
                       help="override a setting, e.g. --set llm.model=models/x.gguf")
        return c

    # options are accepted before and after the command; SUPPRESS keeps the subcommand from resetting them to None
    common = common_args(argparse.SUPPRESS)
    p = argparse.ArgumentParser(prog="kovcheg", description="Offline question answering over your own documents.",
                                parents=[common_args(None)])
    p.add_argument("--version", action="version", version=f"kovcheg {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    def add(name: str, func, help: str, aliases: tuple[str, ...] = ()) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help, parents=[common], aliases=list(aliases))
        sp.set_defaults(func=func)
        return sp

    add("init", cmd_init, "create the home folder layout and a commented kovcheg.toml")

    sp = add("build", cmd_build, "create or update a module from a folder of documents")
    sp.add_argument("name")
    sp.add_argument("--source", help="documents folder (default: sources/NAME)")
    sp.add_argument("--title")
    sp.add_argument("--description")
    sp.add_argument("--language")
    sp.add_argument("--rebuild", action="store_true", help="re-index everything instead of only changed files")
    sp.add_argument("--no-embed", action="store_true", help="keyword (BM25) index only; no embedding model needed")
    sp.add_argument("-q", "--quiet", action="store_true")

    for name, func, help in (("search", cmd_search, "show the most relevant passages"),
                             ("ask", cmd_ask, "answer a question with numbered sources")):
        sp = add(name, func, help)
        sp.add_argument("question", nargs="+")
        sp.add_argument("-m", "--module", action="append", help="module to search (repeatable; default: all valid modules)")
        sp.add_argument("-k", "--top-k", type=int, help="number of sources")
        sp.add_argument("--no-rerank", action="store_true", help="skip the cross-encoder reranker")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "ask":
            sp.add_argument("--search-only", action="store_true", help="do not call the language model")

    sp = add("ui", cmd_ui, "start the web interface")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)

    sp = add("modules", cmd_modules, "list modules with their integrity status", aliases=("list",))
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--no-verify", action="store_true", help="skip signature and hash checks")

    sp = add("inspect", cmd_inspect, "show a module's manifest, files and documents")
    sp.add_argument("name")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--limit", type=int, default=50, help="documents to list")

    sp = add("verify", cmd_verify, "check module signatures and file hashes")
    sp.add_argument("name", nargs="?")
    sp.add_argument("--quick", action="store_true", help="signature and sizes only, no hashing")

    sp = add("keygen", cmd_keygen, "create an Ed25519 key pair for signing modules")
    sp.add_argument("--force", action="store_true")

    sp = add("sign", cmd_sign, "sign a module with your private key")
    sp.add_argument("name")

    sp = add("migrate", cmd_migrate, "convert a pre-1.0 module (search_bge.db) to format v2 without re-encoding")
    sp.add_argument("name")
    sp.add_argument("--delete-old", action="store_true", help="remove search_bge.db after a successful migration")

    sp = add("doctor", cmd_doctor, "check this computer, libraries, models and modules")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--quick", action="store_true", help="skip module hash checks")

    sp = add("eval", cmd_eval, "measure retrieval quality (hit@k, MRR) on a JSONL file of {question, expected}")
    sp.add_argument("file")
    sp.add_argument("-m", "--module", action="append")
    sp.add_argument("-k", "--top-k", type=int)
    sp.add_argument("--no-rerank", action="store_true")
    sp.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return USAGE
    try:
        return args.func(args)
    except UsageError as e:
        _err(str(e))
        return USAGE
    except KeyboardInterrupt:
        _err("interrupted")
        return ERROR
    except BrokenPipeError:
        return OK


if __name__ == "__main__":
    sys.exit(main())
