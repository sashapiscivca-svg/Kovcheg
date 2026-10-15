"""Hybrid retrieval over one or many modules.

Retrievers (each used only where the module supports it):
  dense   cosine similarity on the module's float16 memmap, computed in bounded blocks (never all vectors as float32)
  sparse  BGE-M3 lexical weights through the module's inverted index (`sparse.npz`)
  bm25    SQLite FTS5; always available, needs no model

Ranks are fused with weighted Reciprocal Rank Fusion. Each retriever's candidates from all modules are ranked
together by raw score: cosine and sparse dot products are comparable across modules built with the same encoder, and
BM25 scores, although computed with per-module statistics, are close enough that a strong match in one module
outranks a stop-word match in another (per-module ranks would tie them). BM25 candidates are ordered first by
query-term coverage (corpus-independent), then by bm25(). A chunk's fused score is normalised by the
total weight of the retrievers its module offers, so a BM25-only module competes fairly with a fully embedded one.

Pipeline (driven by `engine.Kovcheg`): `Retriever.candidates` (fuse, dedup, per-document cap) -> optional rerank
-> `select` (cap + top_k) -> `expand_context` (neighbours merged into `Hit.context`, after the final ranking).
"""
from __future__ import annotations

import re
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .types import Chunk, Hit

RETRIEVERS = ("dense", "sparse", "bm25")
# a word may contain apostrophes (Ukrainian кип'ятити, м'ясо; English don't): one token, not two
_TOKEN = re.compile(r"\w+(?:['’ʼ]\w+)*", re.UNICODE)
_UNIT = re.compile(r"^[^\W\d_]{1,6}$", re.UNICODE)    # short alphabetic token after a number: mg, ml, kg, мг, мл
BLOCK_BYTES = 64 << 20                                # float32 scratch per dense block (~64 MB)


# ---- FTS5 query -------------------------------------------------------------------------------------------------

def _quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def fts_query(question: str, max_terms: int = 32) -> str:
    """FTS5 MATCH expression for a free-text question ('' if it has no usable terms).

    Every token of 2+ characters is quoted and OR-ed (no FTS5 syntax can leak in). Phrases are added so exact
    matches score higher: code-like pieces ("J18.9" -> "J18 9", "COVID-19"), number + unit ("500 mg"), and the
    whole question when it is short. FTS5 bm25() sums over all phrases, so a chunk matching a phrase ranks above
    chunks matching the same words scattered.
    """
    words = _TOKEN.findall(question)
    terms = list(dict.fromkeys(w.lower() for w in words if len(w) > 1))[:max_terms]
    phrases: list[str] = []
    for piece in question.split():
        toks = _TOKEN.findall(piece)
        if len(toks) > 1:
            phrases.append(" ".join(toks))
    for a, b in zip(words, words[1:], strict=False):
        if a.isdigit() and _UNIT.match(b):
            phrases.append(f"{a} {b}")
    if 2 <= len(words) <= 8:
        phrases.append(" ".join(words))
    phrases = list(dict.fromkeys(p.lower() for p in phrases))
    if not terms and not phrases:
        return ""
    # prefix terms tolerate inflection (кровотечу -> кровотеча, bleeding -> bleed): FTS5 has no stemmer for Ukrainian
    prefixes = list(dict.fromkeys(stem(t) for t in terms if t not in STOPWORDS and stem(t) != t))
    return " OR ".join([_quote(p) for p in phrases] + [_quote(t) for t in terms] + [_quote(p) + "*" for p in prefixes])


def stem(word: str) -> str:
    """Crude language-agnostic stem for inflected languages: words of 7+ letters keep their first 5 letters, words of 5–6
    letters drop the last 2 (keeping at least 4); shorter words are unchanged. A fixed-length prefix makes different forms
    meet (кип'ятити / кип'ятіть / кип'ятіння -> кип'ят; кровотеча / кровотечу -> крово; disinfecting / disinfection)."""
    n = sum(ch.isalpha() for ch in word)
    if n < 5 or not all(ch.isalpha() or ch in "'’ʼ" for ch in word):
        return word
    keep = 5 if n >= 7 else max(4, n - 2)
    out, letters = [], 0
    for ch in word:
        if letters == keep:
            break
        out.append(ch)
        letters += ch.isalpha()
    return "".join(out)


# ---- lexical coverage ---------------------------------------------------------------------------------------------

# Very common words of the supported interface languages; ignored when measuring query-term coverage only.
STOPWORDS = frozenset("""
a an and are as at be by can do does for from how i in is it of on or should the to what when where which who why with you
your my me if not no yes after before about into than then there this that these those was were will would
і й та а але або в у на з із зі до по за від для про як що це чи не ні так коли де хто чому який яка яке які мені мене
його її їх бо ж же ще вже треба можна потрібно слід робити
и в во на с со к ко по за от для о об как что это ли не ни так когда где кто почему какой какая какие мне меня нужно можно
""".split())


def _fold(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def query_terms(question: str) -> set[str]:
    """Distinct content words of a question (case- and diacritic-folded like FTS5 unicode61)."""
    words = {_fold(w) for w in _TOKEN.findall(question) if len(w) > 1}
    content = {w for w in words if w not in STOPWORDS}
    return content or words


def coverage(terms: set[str], chunk: Chunk) -> float:
    """Fraction of query terms present in a chunk (text, section, document title). Corpus-independent, so it orders
    BM25 matches across modules of very different sizes, where raw bm25() values are not comparable."""
    if not terms:
        return 0.0
    words = {_fold(w) for w in _TOKEN.findall(f"{chunk.text} {chunk.section or ''} {chunk.doc_title}")}
    stems = {stem(w) for w in words}
    found = sum(1.0 if t in words else 0.8 if stem(t) in stems else 0.0 for t in terms)   # inflected match counts slightly less
    # a question word in the section heading says what the passage is about (heading "Boiling" for "how long to boil")
    section = chunk.section if chunk.section and _fold(chunk.section) != _fold(chunk.doc_title) else ""   # an H1 equal to the title says nothing
    heading = {stem(_fold(w)) for w in _TOKEN.findall(section)}
    found += 0.3 * sum(1 for t in terms if stem(t) in heading)
    return round(found / len(terms), 3)


def matches_any_term(terms: set[str], chunk: Chunk, prefix: int = 5) -> bool:
    """True if any query content word occurs in the chunk, comparing the first `prefix` letters so that inflected forms
    match (кровотеча / кровотечу, bleeding / bleed). Used as the evidence gate when no reranker can judge relevance."""
    if not terms:
        return True
    words = {_fold(w)[:prefix] for w in _TOKEN.findall(f"{chunk.text} {chunk.section or ''} {chunk.doc_title}")}
    return any(t[:prefix] in words for t in terms)


_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def focused_snippet(text: str, question: str, max_chars: int = 320) -> str:
    """The part of a passage that answers the question: the sentence with the most question words (inflection-tolerant),
    extended with its neighbours up to `max_chars`. Search-only mode shows passages, so the key sentence must be visible."""
    t = " ".join(text.split())
    if len(t) <= max_chars:
        return t
    sents = [s for s in _SENTENCE.split(t) if s]
    terms = {stem(x) for x in query_terms(question)}

    def score(s: str) -> int:
        return len(terms & {stem(_fold(w)) for w in _TOKEN.findall(s)})

    best = max(range(len(sents)), key=lambda i: (score(sents[i]), -i)) if terms else 0
    lo = hi = best
    out = sents[best]
    while True:
        grown = False
        if hi + 1 < len(sents) and len(out) + 1 + len(sents[hi + 1]) <= max_chars:
            hi += 1
            out = f"{out} {sents[hi]}"
            grown = True
        if lo > 0 and len(out) + 1 + len(sents[lo - 1]) <= max_chars:
            lo -= 1
            out = f"{sents[lo]} {out}"
            grown = True
        if not grown:
            break
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + " …"
    return ("… " if lo > 0 else "") + out + (" …" if hi < len(sents) - 1 and not out.endswith("…") else "")


# ---- text stitching -----------------------------------------------------------------------------------------------

def _overlap(a: str, b: str, limit: int = 600) -> int:
    """Length of the longest suffix of `a` that is a prefix of `b` (chunk sentence overlap), at least 20 chars."""
    m = min(len(a), len(b), limit)
    for n in range(m, 19, -1):
        if a.endswith(b[:n]):
            return n
    return 0


def stitch(texts: Sequence[str]) -> str:
    """Join consecutive chunks of one document, removing the sentence overlap the chunker repeats."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
            continue
        n = _overlap(out, t)
        out = out + t[n:] if n else out + "\n" + t
    return out


def hit_text(hit: Hit) -> str:
    """The hit's text with its context neighbours merged in document order."""
    if not hit.context:
        return hit.chunk.text
    parts = sorted([*hit.context, hit.chunk], key=lambda c: c.idx)
    return stitch([c.text for c in parts])


# ---- module handles and cache -------------------------------------------------------------------------------------

def _stamp(path: Path) -> tuple:
    out = []
    for name in ("manifest.json", "kovcheg.db", "dense.f16.npy", "sparse.npz"):
        try:
            st = (path / name).stat()
            out.append((name, st.st_ino, st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((name, None))
    return tuple(out)


@dataclass
class ModuleHandle:
    """An opened module plus retrieval-side state (lazy row map, own read-only FTS connection)."""
    index: Any                                   # kovcheg.store.ModuleIndex
    stamp: tuple
    lock: threading.Lock = field(default_factory=threading.Lock)
    _rows: np.ndarray | None = None
    _fts: sqlite3.Connection | None = None
    _fts_failed: bool = False

    @property
    def name(self) -> str:
        """Module name = folder name (what users select); used as `Chunk.module` in every hit."""
        return Path(self.index.path).name

    def row_chunk_ids(self) -> np.ndarray:
        if self._rows is None:
            self._rows = np.asarray(self.index.row_chunk_ids(), dtype=np.int64)
        return self._rows

    def fts(self) -> sqlite3.Connection | None:
        if self._fts is None and not self._fts_failed:
            try:
                uri = (Path(self.index.path) / "kovcheg.db").resolve().as_uri() + "?mode=ro&immutable=1"
                self._fts = sqlite3.connect(uri, uri=True, check_same_thread=False)
            except (sqlite3.Error, OSError):
                self._fts_failed = True
        return self._fts

    def close(self) -> None:
        if self._fts is not None:
            self._fts.close()
            self._fts = None
        try:
            self.index.close()
        except Exception:  # noqa: BLE001 - closing must never raise
            pass


def _open_index(path: Path):
    from .store import ModuleIndex
    return ModuleIndex.open(path)


class IndexCache:
    """LRU of opened modules. An entry is reopened when the module's files change (rebuild, migrate, swap)."""

    def __init__(self, capacity: int = 8, opener=_open_index):
        self.capacity, self._opener = capacity, opener
        self._items: OrderedDict[Path, ModuleHandle] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: str | Path) -> ModuleHandle:
        path = Path(path).resolve()
        stamp = _stamp(path)
        with self._lock:
            h = self._items.get(path)
            if h is not None and h.stamp == stamp:
                self._items.move_to_end(path)
                return h
            if h is not None:
                self._items.pop(path)
                h.close()
            h = ModuleHandle(self._opener(path), stamp)
            self._items[path] = h
            while len(self._items) > self.capacity:
                _, old = self._items.popitem(last=False)
                old.close()
            return h

    def clear(self) -> None:
        with self._lock:
            for h in self._items.values():
                h.close()
            self._items.clear()


# ---- per-retriever search -----------------------------------------------------------------------------------------

def _topk(scores: np.ndarray, n: int) -> np.ndarray:
    """Indices of the n largest scores, best first."""
    if n <= 0 or scores.size == 0:
        return np.zeros(0, np.int64)
    if scores.size > n:
        idx = np.argpartition(-scores, n - 1)[:n]
    else:
        idx = np.arange(scores.size)
    return idx[np.argsort(-scores[idx], kind="stable")]


def dense_search(matrix: np.ndarray, q: np.ndarray, n: int, block_rows: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Top-n rows of `matrix` (float16 memmap, L2-normalised rows) by cosine with q. Returns (rows, scores).

    Rows are converted to float32 one block at a time, so scratch memory is bounded by ~BLOCK_BYTES.
    """
    total, dim = matrix.shape
    if total == 0 or n <= 0:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    q = np.asarray(q, np.float32).reshape(-1)
    block = block_rows or max(1024, BLOCK_BYTES // (4 * max(dim, 1)))
    best_rows, best_scores = np.zeros(0, np.int64), np.zeros(0, np.float32)
    for start in range(0, total, block):
        s = np.asarray(matrix[start:start + block], dtype=np.float32) @ q
        top = _topk(s, n)
        rows = np.concatenate([best_rows, top.astype(np.int64) + start])
        scores = np.concatenate([best_scores, s[top]])
        keep = _topk(scores, n)
        best_rows, best_scores = rows[keep], scores[keep]
    return best_rows, best_scores


def sparse_search(postings: Any, q: dict[int, float], n: int) -> tuple[np.ndarray, np.ndarray]:
    """Top-n chunk ids by sparse dot product through an inverted index. Returns (chunk_ids, raw scores)."""
    if not q or postings is None or len(postings.token_ids) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    token_ids = np.asarray(postings.token_ids)
    toks = np.fromiter(q.keys(), np.int64, len(q))
    qw = np.fromiter(q.values(), np.float32, len(q))
    pos = np.searchsorted(token_ids, toks)
    ok = pos < len(token_ids)
    ok[ok] = token_ids[pos[ok]] == toks[ok]
    ids_parts, w_parts = [], []
    for p, w in zip(pos[ok], qw[ok], strict=True):
        a, b = int(postings.indptr[p]), int(postings.indptr[p + 1])
        if b > a:
            ids_parts.append(np.asarray(postings.chunk_ids[a:b], np.int64))
            w_parts.append(np.asarray(postings.weights[a:b], np.float32) * w)
    if not ids_parts:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    uniq, inv = np.unique(np.concatenate(ids_parts), return_inverse=True)
    scores = np.bincount(inv, weights=np.concatenate(w_parts)).astype(np.float32)
    top = _topk(scores, n)
    top = top[scores[top] > 0]
    return uniq[top], scores[top]


def bm25_search(handle: ModuleHandle, question: str, n: int) -> list[tuple[int, float]]:
    """(chunk_id, score) best first; score = -bm25() so higher is better."""
    expr = fts_query(question)
    if not expr:
        return []
    conn = handle.fts()
    if conn is not None:
        try:
            with handle.lock:
                rows = conn.execute("SELECT rowid, bm25(chunks_fts, 1.0, 0.6, 0.4) FROM chunks_fts WHERE chunks_fts MATCH ? "
                                    "ORDER BY 2 LIMIT ?", (expr, n)).fetchall()
            return [(int(r), -float(s)) for r, s in rows]
        except sqlite3.Error:
            pass
    return [(int(c), float(s)) for c, s in handle.index.bm25(question, n)]


# ---- fusion -------------------------------------------------------------------------------------------------------

@dataclass
class QueryVectors:
    dense: np.ndarray | None = None
    sparse: dict[int, float] | None = None


@dataclass
class SearchResult:
    hits: list[Hit]
    warnings: list[str] = field(default_factory=list)
    retrievers: dict[str, list[str]] = field(default_factory=dict)    # module -> retrievers used
    timings: dict[str, float] = field(default_factory=dict)


def _norm_text(t: str) -> str:
    return " ".join(t.lower().split())


class Retriever:
    """Hybrid search over a set of opened modules. Stateless apart from settings and the optional encoder."""

    def __init__(self, settings, encoder=None):
        self.settings = settings
        self.encoder = encoder
        self._qcache: OrderedDict[tuple[str, str], QueryVectors] = OrderedDict()
        self._lock = threading.Lock()

    # query encoding is the expensive step on CPU; cache a few recent questions
    def encode_query(self, question: str) -> QueryVectors:
        if self.encoder is None:
            return QueryVectors()
        key = (self.encoder.id, question)
        with self._lock:
            if key in self._qcache:
                self._qcache.move_to_end(key)
                return self._qcache[key]
        enc = self.encoder.encode([question], query=True)
        qv = QueryVectors(np.asarray(enc.dense[0], np.float32), enc.sparse[0] if enc.sparse else None)
        with self._lock:
            self._qcache[key] = qv
            while len(self._qcache) > 64:
                self._qcache.popitem(last=False)
        return qv

    def _usable(self, h: ModuleHandle, warnings: list[str]) -> set[str]:
        ix = h.index
        avail = {"bm25"}
        enc = self.encoder
        if ix.has_dense or ix.has_sparse:
            if enc is None:
                warnings.append(f"module '{h.name}': embedding model not loaded, keyword search (BM25) only")
            elif ix.encoder_id != enc.id or (ix.has_dense and ix.dim != enc.dim):
                warnings.append(f"module '{h.name}' was built with encoder '{ix.encoder_id}' but '{enc.id}' is loaded; "
                                "keyword search (BM25) only — rebuild the module or change embedding.model")
            else:
                if ix.has_dense:
                    avail.add("dense")
                if ix.has_sparse and enc.has_sparse:
                    avail.add("sparse")
        w = self.settings.retrieval.weights
        return {r for r in avail if w.get(r, 0.0) > 0}

    def candidates(self, question: str, handles: Sequence[ModuleHandle], n: int | None = None) -> SearchResult:
        """Fused, deduplicated, per-document-capped candidates, best first (at most n)."""
        import time
        rs = self.settings.retrieval
        n = n or rs.candidates
        per = max(rs.candidates, n)
        warnings: list[str] = []
        timings: dict[str, float] = {}
        usable = {h.name: self._usable(h, warnings) for h in handles}
        qv = QueryVectors()
        if any(u & {"dense", "sparse"} for u in usable.values()):
            t = time.perf_counter()
            try:
                qv = self.encode_query(question)
            except Exception as e:  # noqa: BLE001 - degrade to BM25
                warnings.append(f"query encoding failed ({e}); keyword search (BM25) only")
                usable = {k: v & {"bm25"} for k, v in usable.items()}
            timings["encode"] = time.perf_counter() - t

        t = time.perf_counter()
        by_name = {h.name: h for h in handles}
        dense_all: list[tuple[float, tuple[str, int]]] = []
        sparse_all: list[tuple[float, tuple[str, int]]] = []
        bm25_all: list[tuple[tuple[float, float], tuple[str, int]]] = []   # ((coverage, bm25), key)
        ranks: dict[tuple[str, int], dict[str, int]] = {}
        raw: dict[tuple[str, int], dict[str, float]] = {}
        vecs: dict[tuple[str, int], np.ndarray] = {}
        chunks: dict[tuple[str, int], Chunk] = {}
        qterms = query_terms(question)
        for h in handles:
            u = usable[h.name]
            try:
                if "dense" in u and qv.dense is not None:
                    mat = h.index.dense()
                    rows, scores = dense_search(mat, qv.dense, per)
                    cids = h.row_chunk_ids()[rows]
                    for r, c, s in zip(rows, cids, scores, strict=True):
                        key = (h.name, int(c))
                        dense_all.append((float(s), key))
                        vecs[key] = np.asarray(mat[int(r)], np.float32)
                if "sparse" in u and qv.sparse:
                    cids, scores = sparse_search(h.index.sparse_postings(), qv.sparse, per)
                    sparse_all.extend((float(s), (h.name, int(c))) for c, s in zip(cids, scores, strict=True))
                if "bm25" in u:
                    found = bm25_search(h, question, per)
                    for c in h.index.chunks([cid for cid, _ in found]):
                        chunks[(h.name, c.id)] = c
                    for cid, s in found:
                        c = chunks.get((h.name, cid))
                        cov = coverage(qterms, c) if c is not None else 0.0
                        bm25_all.append(((cov, s), (h.name, cid)))
            except Exception as e:  # noqa: BLE001 - one broken module must not break the search
                warnings.append(f"module '{h.name}': search failed ({e})")
        dense_all.sort(key=lambda x: -x[0])
        sparse_all.sort(key=lambda x: -x[0])
        bm25_all.sort(key=lambda x: (-x[0][0], -x[0][1]))
        for name, lst in (("dense", dense_all), ("sparse", sparse_all), ("bm25", bm25_all)):
            for rank, (s, key) in enumerate(lst[:per * 2]):
                ranks.setdefault(key, {})[name] = rank
                raw.setdefault(key, {})[name] = s[1] if isinstance(s, tuple) else s
        smax = max((s for s, _ in sparse_all), default=0.0) or 1.0

        k, w = rs.rrf_k, rs.weights
        fused: dict[tuple[str, int], float] = {}
        for key, rr in ranks.items():
            total_w = sum(w.get(r, 0.0) for r in usable[key[0]]) or 1.0
            fused[key] = sum(w.get(r, 0.0) / (k + rank + 1) for r, rank in rr.items()) / total_w
        order = sorted(fused, key=lambda x: -fused[x])[: max(n * 3, n + 20)]

        by_module: dict[str, list[int]] = {}
        for name, cid in order:
            if (name, cid) not in chunks:
                by_module.setdefault(name, []).append(cid)
        for name, ids in by_module.items():
            try:
                for c in by_name[name].index.chunks(ids):
                    chunks[(name, c.id)] = c
            except Exception as e:  # noqa: BLE001
                warnings.append(f"module '{name}': reading chunks failed ({e})")
        hits: list[Hit] = []
        for key in order:
            c = chunks.get(key)
            if c is None:
                continue
            if c.module != key[0]:
                c = Chunk(**{**c.__dict__, "module": key[0]})
            sc = raw.get(key, {})
            hits.append(Hit(chunk=c, score=fused[key], dense=sc.get("dense"),
                            sparse=(sc["sparse"] / smax) if "sparse" in sc else None, bm25=sc.get("bm25")))
        hits = dedup(hits, vecs, rs.dedup_threshold)
        hits = cap_per_document(hits, rs.max_per_document)[:n]
        timings["retrieve"] = time.perf_counter() - t
        return SearchResult(hits, list(dict.fromkeys(warnings)), {m: sorted(u) for m, u in usable.items()}, timings)


def dedup(hits: list[Hit], vecs: dict[tuple[str, int], np.ndarray] | None = None, threshold: float = 0.95) -> list[Hit]:
    """Drop hits whose text is identical (whitespace/case-insensitive) or whose dense vectors are near-duplicates."""
    seen_text: set[str] = set()
    kept: list[Hit] = []
    kept_vecs: list[np.ndarray] = []
    for h in hits:
        t = _norm_text(h.chunk.text)
        if t in seen_text:
            continue
        v = vecs.get(h.key) if vecs else None
        if v is not None and kept_vecs and threshold < 1.0:
            if float(np.max(np.stack(kept_vecs) @ v)) >= threshold:
                continue
        seen_text.add(t)
        kept.append(h)
        if v is not None:
            kept_vecs.append(v)
    return kept


def cap_per_document(hits: list[Hit], max_per_document: int) -> list[Hit]:
    """Keep at most `max_per_document` hits per (module, document); order preserved. 0 disables the cap."""
    if max_per_document <= 0:
        return list(hits)
    counts: dict[tuple[str, int], int] = {}
    out = []
    for h in hits:
        key = (h.chunk.module, h.chunk.doc_id)
        if counts.get(key, 0) < max_per_document:
            counts[key] = counts.get(key, 0) + 1
            out.append(h)
    return out


def select(hits: list[Hit], top_k: int, max_per_document: int) -> list[Hit]:
    """Final source list: per-document cap, then the first top_k."""
    return cap_per_document(hits, max_per_document)[:top_k]


def expand_context(hits: list[Hit], handles: dict[str, ModuleHandle], neighbors: int) -> list[Hit]:
    """Fill `Hit.context` with up to `neighbors` chunks before/after each hit (same document).

    Neighbours that are themselves among the hits are skipped so no text is given to the LLM twice.
    """
    if neighbors <= 0:
        return hits
    taken = {h.key for h in hits}
    for h in hits:
        handle = handles.get(h.chunk.module)
        if handle is None:
            continue
        try:
            nb = handle.index.neighbors(h.chunk.id, neighbors, neighbors)
        except Exception:  # noqa: BLE001 - context is an optional extra
            continue
        ctx = []
        for c in nb:
            key = (h.chunk.module, c.id)
            if key in taken:
                continue
            taken.add(key)
            ctx.append(c if c.module == h.chunk.module else Chunk(**{**c.__dict__, "module": h.chunk.module}))
        h.context = sorted(ctx, key=lambda c: c.idx)
    return hits
