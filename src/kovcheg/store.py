"""Module storage, format v2: `ModuleIndex` (read-only, used by retrieval) and `ModuleWriter` (used by the builder and migrate).

A module is a folder with `kovcheg.db` (SQLite: meta, documents, chunks, sparse, chunks_fts), `dense.f16.npy`
(float16, L2-normalised, row i <-> chunks.row = i), `sparse.npz` (inverted index of sparse lexical weights),
`manifest.json` (written last) and optionally `manifest.sig`.

Dense vectors are kept ONLY in `dense.f16.npy` (no `dense_store` table): incremental builds carry unchanged rows over
from the previous npy. While a build is in progress (inside the disposable work folder) `chunks.row` holds either the
row of the previous npy (>= 0) or `-(k + 1)` for row k of the not-yet-merged new vectors; `finalize()` compacts both
into the final npy and renumbers `row` to 0..n-1 in chunk-id order.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .types import Chunk

SCHEMA_VERSION = 2
FORMAT = "kovcheg-module"
DB_NAME = "kovcheg.db"
DENSE_NAME = "dense.f16.npy"
SPARSE_NAME = "sparse.npz"
MANIFEST_NAME = "manifest.json"
SIG_NAME = "manifest.sig"
LEGACY_DB_NAME = "search_bge.db"
MODULE_FILES = (DB_NAME, DENSE_NAME, SPARSE_NAME)

_NEW_ROWS = "dense.new.f16"        # raw float16 vectors appended during a build (work folder only)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS documents(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, title TEXT, kind TEXT, sha256 TEXT NOT NULL, size INTEGER, n_chunks INTEGER);
CREATE TABLE IF NOT EXISTS chunks(
    id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, idx INTEGER NOT NULL,
    text TEXT NOT NULL, page INTEGER, section TEXT, row INTEGER, UNIQUE(doc_id, idx));
CREATE TABLE IF NOT EXISTS sparse(chunk_id INTEGER PRIMARY KEY, tokens BLOB, weights BLOB);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, section, title, tokenize='unicode61 remove_diacritics 2');
"""


class ModuleFormatError(Exception):
    """The folder is not a readable v2 module (missing, legacy v1, or unknown format)."""


@dataclass
class SparsePostings:
    token_ids: np.ndarray      # int32, sorted unique
    indptr: np.ndarray         # int64, len T + 1
    chunk_ids: np.ndarray      # int64
    weights: np.ndarray        # float16

    def lookup(self, token_id: int) -> tuple[np.ndarray, np.ndarray]:
        """(chunk_ids, weights) of one token; empty arrays if absent."""
        i = int(np.searchsorted(self.token_ids, token_id))
        if i >= len(self.token_ids) or int(self.token_ids[i]) != token_id:
            return np.zeros(0, np.int64), np.zeros(0, np.float16)
        a, b = int(self.indptr[i]), int(self.indptr[i + 1])
        return self.chunk_ids[a:b], self.weights[a:b]


# ---- helpers ---------------------------------------------------------------------------------------

def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(block):
            h.update(data)
    return h.hexdigest()


def _ro_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro&immutable=1"


def connect_ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(_ro_uri(db), uri=True, check_same_thread=False)


_FTS_TERM = re.compile(r"[^\s\"]+")
_WORD = re.compile(r"\w", re.UNICODE)


def fts_query(query: str, max_terms: int = 64) -> str:
    """Turn free text into a safe FTS5 query: every whitespace-separated term quoted (so punctuation such as the dot in
    'J18.9' becomes a phrase), terms ORed. '' if nothing searchable."""
    terms: list[str] = []
    seen: set[str] = set()
    for t in _FTS_TERM.findall(query):
        if not _WORD.search(t) or t.lower() in seen:
            continue
        seen.add(t.lower())
        terms.append('"' + t.replace('"', '""') + '"')
        if len(terms) >= max_terms:
            break
    return " OR ".join(terms)


def _npz_member_memmap(path: Path, zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> np.ndarray | None:
    """Memory-map one stored (uncompressed) .npy member of an .npz; None if not possible."""
    if info.compress_type != zipfile.ZIP_STORED:
        return None
    with open(path, "rb") as f:
        f.seek(info.header_offset)
        hdr = f.read(30)
        if hdr[:4] != b"PK\x03\x04":
            return None
        n, m = int.from_bytes(hdr[26:28], "little"), int.from_bytes(hdr[28:30], "little")
        start = info.header_offset + 30 + n + m
        f.seek(start)
        version = np.lib.format.read_magic(f)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(f)
        elif version == (2, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(f)
        else:
            return None
        offset = f.tell()
    if fortran or dtype.hasobject:
        return None
    if int(np.prod(shape)) == 0:
        return np.zeros(shape, dtype)
    return np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=shape)


def load_sparse_postings(path: Path) -> SparsePostings:
    arrays: dict[str, np.ndarray] = {}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            key = info.filename[:-4] if info.filename.endswith(".npy") else info.filename
            arr = _npz_member_memmap(path, zf, info)
            if arr is None:
                with zf.open(info) as fh:
                    arr = np.lib.format.read_array(fh)
            arrays[key] = arr
    try:
        return SparsePostings(arrays["token_ids"], arrays["indptr"], arrays["chunk_ids"], arrays["weights"])
    except KeyError as e:
        raise ModuleFormatError(f"{path}: missing array {e}") from None


# ---- read side ------------------------------------------------------------------------------------

class ModuleIndex:
    """Read-only view of one v2 module. Thread-safe (one connection guarded by a lock)."""

    def __init__(self, path: Path, conn: sqlite3.Connection, meta: dict[str, str], manifest: dict):
        self.path = path
        self._conn = conn
        self._lock = threading.Lock()
        self.meta = meta
        self.manifest = manifest
        self.name: str = manifest.get("name") or meta.get("name") or path.name
        self.encoder_id: str | None = meta.get("encoder_id") or None
        self.dim: int = int(meta.get("dim") or 0)
        self.n_chunks: int = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        self.has_dense: bool = bool(self.encoder_id) and self.dim > 0 and (path / DENSE_NAME).exists()
        self.has_sparse: bool = bool(self.encoder_id) and (path / SPARSE_NAME).exists()
        self._dense: np.ndarray | None = None
        self._rows: np.ndarray | None = None
        self._sparse: SparsePostings | None = None

    @classmethod
    def open(cls, path: Path) -> ModuleIndex:
        path = Path(path)
        db = path / DB_NAME
        if not db.exists():
            if (path / LEGACY_DB_NAME).exists():
                raise ModuleFormatError(f"{path.name}: legacy v1 module (search_bge.db); convert it with `kovcheg migrate {path.name}`")
            raise ModuleFormatError(f"{path}: not a Kovcheg module (no {DB_NAME})")
        try:
            conn = connect_ro(db)
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.DatabaseError as e:
            raise ModuleFormatError(f"{path.name}: unreadable database: {e}") from None
        if meta.get("format") != FORMAT or ver != SCHEMA_VERSION:
            conn.close()
            raise ModuleFormatError(f"{path.name}: unsupported module format (format={meta.get('format')!r}, version={ver}); "
                                    "rebuild it or run `kovcheg migrate`")
        manifest: dict = {}
        mf = path / MANIFEST_NAME
        if mf.exists():
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
        return cls(path, conn, meta, manifest)

    # ---- vectors ------------------------------------------------------------------------------
    def dense(self) -> np.ndarray:
        if not self.has_dense:
            raise ModuleFormatError(f"{self.name}: module has no dense vectors")
        if self._dense is None:
            self._dense = np.load(self.path / DENSE_NAME, mmap_mode="r")
        return self._dense

    def row_chunk_ids(self) -> np.ndarray:
        if self._rows is None:
            with self._lock:
                rows = self._conn.execute("SELECT row, id FROM chunks WHERE row IS NOT NULL ORDER BY row").fetchall()
            arr = np.zeros(len(rows), np.int64)
            for r, cid in rows:
                arr[r] = cid
            self._rows = arr
        return self._rows

    def sparse_postings(self) -> SparsePostings:
        if not self.has_sparse:
            raise ModuleFormatError(f"{self.name}: module has no sparse index")
        if self._sparse is None:
            self._sparse = load_sparse_postings(self.path / SPARSE_NAME)
        return self._sparse

    # ---- lexical ------------------------------------------------------------------------------
    def bm25(self, query: str, limit: int) -> list[tuple[int, float]]:
        q = fts_query(query)
        if not q or limit <= 0:
            return []
        sql = ("SELECT rowid, bm25(chunks_fts, 1.0, 0.5, 0.5) AS s FROM chunks_fts WHERE chunks_fts MATCH ? "
               "ORDER BY s LIMIT ?")
        try:
            with self._lock:
                rows = self._conn.execute(sql, (q, int(limit))).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(int(cid), -float(s)) for cid, s in rows]

    # ---- chunks -------------------------------------------------------------------------------
    _CHUNK_SQL = ("SELECT c.id, c.doc_id, c.idx, c.text, c.page, c.section, d.path, d.title "
                  "FROM chunks c JOIN documents d ON d.id = c.doc_id ")

    def _mk(self, r) -> Chunk:
        return Chunk(id=r[0], doc_id=r[1], idx=r[2], text=r[3], page=r[4], section=r[5], module=self.name,
                     doc_path=r[6] or "", doc_title=r[7] or "")

    def chunks(self, ids: Sequence[int]) -> list[Chunk]:
        ids = [int(i) for i in ids]
        found: dict[int, Chunk] = {}
        with self._lock:
            for s in range(0, len(ids), 500):
                part = ids[s:s + 500]
                q = self._CHUNK_SQL + f"WHERE c.id IN ({','.join('?' * len(part))})"
                for r in self._conn.execute(q, part):
                    found[r[0]] = self._mk(r)
        return [found[i] for i in ids if i in found]

    def neighbors(self, chunk_id: int, before: int, after: int) -> list[Chunk]:
        with self._lock:
            r = self._conn.execute("SELECT doc_id, idx FROM chunks WHERE id = ?", (int(chunk_id),)).fetchone()
            if r is None:
                return []
            doc_id, idx = r
            rows = self._conn.execute(self._CHUNK_SQL + "WHERE c.doc_id = ? AND c.idx BETWEEN ? AND ? AND c.idx != ? ORDER BY c.idx",
                                      (doc_id, idx - max(0, before), idx + max(0, after), idx)).fetchall()
        return [self._mk(x) for x in rows]

    def documents(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute("SELECT id, path, title, kind, sha256, size, n_chunks FROM documents ORDER BY path")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        self._dense = None
        self._sparse = None

    def __enter__(self) -> ModuleIndex:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---- write side -----------------------------------------------------------------------------------

def _sparse_blob(weights: dict[int, float]) -> tuple[bytes, bytes]:
    if not weights:
        return b"", b""
    toks = np.fromiter(weights.keys(), np.int32, len(weights))
    w = np.fromiter(weights.values(), np.float32, len(weights)).astype(np.float16)
    return toks.tobytes(), w.tobytes()


class ModuleWriter:
    """Writes a v2 module in a (disposable) work folder. Not thread-safe; one writer per folder."""

    def __init__(self, folder: Path, *, name: str):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.conn = sqlite3.connect(self.folder / DB_NAME)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = MEMORY")   # work folder is thrown away on failure
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.executescript(SCHEMA)
        self.conn.execute("CREATE TABLE IF NOT EXISTS _seen(doc_id INTEGER PRIMARY KEY)")
        self.conn.execute("PRAGMA user_version = 2")
        self.set_meta(format=FORMAT, schema_version=str(SCHEMA_VERSION), name=name)
        self._new_rows = 0
        self._new_f = None
        self.dim = int(self.get_meta("dim") or 0)

    # ---- meta ---------------------------------------------------------------------------------
    def set_meta(self, **kv: object) -> None:
        self.conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", [(k, str(v)) for k, v in kv.items()])

    def get_meta(self, key: str) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    # ---- documents ----------------------------------------------------------------------------
    def find_document(self, path: str) -> tuple[int, str] | None:
        r = self.conn.execute("SELECT id, sha256 FROM documents WHERE path = ?", (path,)).fetchone()
        return (r[0], r[1]) if r else None

    def mark_seen(self, doc_id: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO _seen(doc_id) VALUES (?)", (doc_id,))

    def mark_seen_prefix(self, prefix: str) -> int:
        """Mark every document whose path starts with `prefix` as seen (e.g. all articles of an unchanged ZIM)."""
        esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cur = self.conn.execute("INSERT OR IGNORE INTO _seen(doc_id) SELECT id FROM documents WHERE path LIKE ? ESCAPE '\\'", (esc + "%",))
        return cur.rowcount

    def delete_document(self, doc_id: int) -> None:
        ids = [r[0] for r in self.conn.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,))]
        for s in range(0, len(ids), 500):
            part = ids[s:s + 500]
            ph = ",".join("?" * len(part))
            self.conn.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({ph})", part)
            self.conn.execute(f"DELETE FROM sparse WHERE chunk_id IN ({ph})", part)
        self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def delete_unseen(self) -> list[str]:
        """Delete documents not marked seen during this build; returns their paths."""
        rows = self.conn.execute("SELECT id, path FROM documents WHERE id NOT IN (SELECT doc_id FROM _seen)").fetchall()
        for doc_id, _ in rows:
            self.delete_document(doc_id)
        return [p for _, p in rows]

    def add_document(self, path: str, *, title: str, kind: str, sha256: str, size: int | None,
                     chunks: Sequence[tuple[str, int | None, str | None]]) -> tuple[int, list[int]]:
        """Insert a document and its chunks (text, page, section); returns (doc_id, chunk ids). Replaces an existing path."""
        old = self.find_document(path)
        if old:
            self.delete_document(old[0])
        cur = self.conn.execute("INSERT INTO documents(path, title, kind, sha256, size, n_chunks) VALUES (?, ?, ?, ?, ?, ?)",
                                (path, title, kind, sha256, size, len(chunks)))
        doc_id = int(cur.lastrowid)
        ids: list[int] = []
        for i, (text, page, section) in enumerate(chunks):
            c = self.conn.execute("INSERT INTO chunks(doc_id, idx, text, page, section, row) VALUES (?, ?, ?, ?, ?, NULL)",
                                  (doc_id, i, text, page, section))
            cid = int(c.lastrowid)
            ids.append(cid)
            self.conn.execute("INSERT INTO chunks_fts(rowid, text, section, title) VALUES (?, ?, ?, ?)", (cid, text, section or "", title or ""))
        self.mark_seen(doc_id)
        return doc_id, ids

    # ---- vectors ------------------------------------------------------------------------------
    def add_vectors(self, chunk_ids: Sequence[int], dense: np.ndarray | None, sparse: Sequence[dict[int, float]] | None) -> None:
        if dense is not None and len(chunk_ids):
            d = np.ascontiguousarray(dense, dtype=np.float16)
            if self.dim == 0:
                self.dim = int(d.shape[1])
            if d.shape != (len(chunk_ids), self.dim):
                raise ValueError(f"dense shape {d.shape} does not match ({len(chunk_ids)}, {self.dim})")
            if self._new_f is None:
                self._new_f = open(self.folder / _NEW_ROWS, "ab")
            self._new_f.write(d.tobytes())
            self.conn.executemany("UPDATE chunks SET row = ? WHERE id = ?",
                                  [(-(self._new_rows + k + 1), int(c)) for k, c in enumerate(chunk_ids)])
            self._new_rows += len(chunk_ids)
        if sparse:
            self.conn.executemany("INSERT OR REPLACE INTO sparse(chunk_id, tokens, weights) VALUES (?, ?, ?)",
                                  [(int(c), *_sparse_blob(w)) for c, w in zip(chunk_ids, sparse, strict=True)])

    def drop_vectors(self) -> None:
        """Forget all vectors (encoder removed or changed)."""
        self.conn.execute("UPDATE chunks SET row = NULL")
        self.conn.execute("DELETE FROM sparse")

    def commit(self) -> None:
        self.conn.commit()

    # ---- finalize -----------------------------------------------------------------------------
    def finalize(self, *, old_dense: np.ndarray | None, encoder_id: str, has_sparse: bool, vacuum: bool | None = None,
                 block: int = 8192) -> dict:
        """Compact vectors into dense.f16.npy, build sparse.npz, clean up, switch to journal_mode DELETE.
        Returns stats {documents, chunks}. Does not write the manifest."""
        if self._new_f is not None:
            self._new_f.close()
            self._new_f = None
        conn = self.conn
        conn.execute("UPDATE documents SET n_chunks = (SELECT COUNT(*) FROM chunks WHERE chunks.doc_id = documents.id)")
        dense_path, sparse_path = self.folder / DENSE_NAME, self.folder / SPARSE_NAME
        for p in (dense_path, sparse_path):
            p.unlink(missing_ok=True)
        if encoder_id and self.dim:
            self._write_dense(old_dense, dense_path, block)
        else:
            conn.execute("UPDATE chunks SET row = NULL")
        (self.folder / _NEW_ROWS).unlink(missing_ok=True)
        if encoder_id and has_sparse:
            self._write_sparse(sparse_path)
        else:
            conn.execute("DELETE FROM sparse")
        n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        self.set_meta(encoder_id=encoder_id or "", dim=self.dim if encoder_id else 0)
        conn.execute("DROP TABLE IF EXISTS _seen")
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
        conn.commit()
        if vacuum is None:
            pages = conn.execute("PRAGMA page_count").fetchone()[0]
            free = conn.execute("PRAGMA freelist_count").fetchone()[0]
            vacuum = pages > 0 and free / pages > 0.2
        if vacuum:
            conn.execute("VACUUM")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.close()
        return {"documents": int(n_docs), "chunks": int(n_chunks)}

    def _write_dense(self, old_dense: np.ndarray | None, out: Path, block: int) -> None:
        conn = self.conn
        rows = conn.execute("SELECT id, row FROM chunks WHERE row IS NOT NULL ORDER BY id").fetchall()
        missing = conn.execute("SELECT COUNT(*) FROM chunks WHERE row IS NULL").fetchone()[0]
        if missing:
            raise RuntimeError(f"{missing} chunks have no dense vector")
        new_path = self.folder / _NEW_ROWS
        new = (np.memmap(new_path, dtype=np.float16, mode="r").reshape(-1, self.dim)
               if self._new_rows and new_path.exists() else np.zeros((0, self.dim), np.float16))
        if old_dense is not None and old_dense.shape[1:] != (self.dim,) and any(r >= 0 for _, r in rows):
            raise RuntimeError("previous dense vectors have a different dimension")
        arr = np.lib.format.open_memmap(out, mode="w+", dtype=np.float16, shape=(len(rows), self.dim))
        for s in range(0, len(rows), block):
            part = rows[s:s + block]
            src = np.array([r for _, r in part], np.int64)
            buf = np.empty((len(part), self.dim), np.float16)
            old_mask = src >= 0
            if old_mask.any():
                if old_dense is None:
                    raise RuntimeError("chunks refer to previous dense vectors, but none are available")
                buf[old_mask] = old_dense[src[old_mask]]
            if (~old_mask).any():
                buf[~old_mask] = new[-src[~old_mask] - 1]
            arr[s:s + len(part)] = buf
        arr.flush()
        del arr
        conn.executemany("UPDATE chunks SET row = ? WHERE id = ?", [(i, cid) for i, (cid, _) in enumerate(rows)])

    def _write_sparse(self, out: Path) -> None:
        tok_parts: list[np.ndarray] = []
        cid_parts: list[np.ndarray] = []
        w_parts: list[np.ndarray] = []
        for cid, tb, wb in self.conn.execute("SELECT chunk_id, tokens, weights FROM sparse ORDER BY chunk_id"):
            if not tb:
                continue
            t = np.frombuffer(tb, np.int32)
            tok_parts.append(t)
            w_parts.append(np.frombuffer(wb, np.float16))
            cid_parts.append(np.full(len(t), cid, np.int64))
        if tok_parts:
            toks, cids, ws = np.concatenate(tok_parts), np.concatenate(cid_parts), np.concatenate(w_parts)
        else:
            toks, cids, ws = np.zeros(0, np.int32), np.zeros(0, np.int64), np.zeros(0, np.float16)
        del tok_parts, cid_parts, w_parts
        order = np.argsort(toks, kind="stable")
        toks, cids, ws = toks[order], cids[order], ws[order]
        token_ids, counts = np.unique(toks, return_counts=True)
        indptr = np.zeros(len(token_ids) + 1, np.int64)
        np.cumsum(counts, out=indptr[1:])
        with open(out, "wb") as f:
            np.savez(f, token_ids=token_ids.astype(np.int32), indptr=indptr, chunk_ids=cids, weights=ws.astype(np.float16))

    def abort(self) -> None:
        if self._new_f is not None:
            self._new_f.close()
            self._new_f = None
        try:
            self.conn.close()
        except sqlite3.Error:
            pass


def file_entries(folder: Path, names: Iterable[str] = MODULE_FILES) -> dict[str, dict]:
    """Manifest `files` section: sha256 and size of the module files that exist."""
    out: dict[str, dict] = {}
    for n in names:
        p = folder / n
        if p.exists():
            out[n] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    return out


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
