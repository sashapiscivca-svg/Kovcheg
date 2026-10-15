"""Test helpers for the answering side: write tiny v2 modules directly in the documented on-disk format.

Independent of the builder on purpose, so retrieval tests also cross-check the format contract of `store.py`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np

from kovcheg.embedding import HashingEncoder
from kovcheg.types import Hit

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE documents(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, title TEXT, kind TEXT, sha256 TEXT NOT NULL, size INTEGER,
                       n_chunks INTEGER);
CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, idx INTEGER NOT NULL,
                    text TEXT NOT NULL, page INTEGER, section TEXT, row INTEGER, UNIQUE(doc_id, idx));
CREATE TABLE sparse(chunk_id INTEGER PRIMARY KEY, tokens BLOB, weights BLOB);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, section, title, tokenize='unicode61 remove_diacritics 2');
"""

# path -> list of chunks; a chunk is "text" or (text, page, section)
Docs = dict[str, Sequence[str | tuple[str, int | None, str | None]]]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_module(modules_dir: Path, name: str, docs: Docs, encoder: HashingEncoder | None = None, *, titles: dict[str, str] | None = None,
                sparse: bool = True) -> Path:
    """Create `<modules_dir>/<name>/` in format v2. With `encoder=None` the module is BM25-only."""
    folder = Path(modules_dir) / name
    folder.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(folder / "kovcheg.db")
    db.executescript(SCHEMA)
    db.execute("PRAGMA user_version = 2")
    meta = {"format": "kovcheg-module", "schema_version": "2", "name": name,
            "encoder_id": encoder.id if encoder else "", "dim": str(encoder.dim if encoder else 0)}
    db.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    texts, cids = [], []
    cid = 0
    for d, (path, chunks) in enumerate(docs.items(), start=1):
        title = (titles or {}).get(path, Path(path).stem)
        db.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)", (d, path, title, "txt", hashlib.sha256(path.encode()).hexdigest(),
                                                                          100, len(chunks)))
        for i, ch in enumerate(chunks):
            text, page, section = (ch, None, None) if isinstance(ch, str) else ch
            cid += 1
            row = len(texts) if encoder else None
            db.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)", (cid, d, i, text, page, section, row))
            db.execute("INSERT INTO chunks_fts(rowid, text, section, title) VALUES (?, ?, ?, ?)", (cid, text, section or "", title))
            texts.append(text)
            cids.append(cid)
    files = ["kovcheg.db"]
    if encoder is not None:
        enc = encoder.encode(texts)
        np.save(folder / "dense.f16.npy", enc.dense.astype(np.float16))
        files.append("dense.f16.npy")
        if sparse and encoder.has_sparse:
            post: dict[int, list[tuple[int, float]]] = {}
            for c, sp in zip(cids, enc.sparse, strict=True):
                toks = np.array(sorted(sp), np.int32)
                db.execute("INSERT INTO sparse VALUES (?, ?, ?)", (c, toks.tobytes(), np.array([sp[t] for t in toks], np.float16).tobytes()))
                for t, w in sp.items():
                    post.setdefault(t, []).append((c, w))
            tok_ids = np.array(sorted(post), np.int32)
            indptr = np.zeros(len(tok_ids) + 1, np.int64)
            ch_ids, ws = [], []
            for i, t in enumerate(tok_ids):
                lst = post[int(t)]
                indptr[i + 1] = indptr[i] + len(lst)
                ch_ids += [c for c, _ in lst]
                ws += [w for _, w in lst]
            np.savez(folder / "sparse.npz", token_ids=tok_ids, indptr=indptr, chunk_ids=np.array(ch_ids, np.int64),
                     weights=np.array(ws, np.float16))
            files.append("sparse.npz")
    db.commit()
    db.execute("PRAGMA journal_mode=DELETE")
    db.close()
    manifest = {"format": "kovcheg-module", "version": 2, "name": name, "title": name.title(), "description": f"test module {name}",
                "language": "en", "created_at": "2026-10-15T00:00:00Z", "updated_at": "2026-10-15T00:00:00Z", "kovcheg_version": "1.0.0",
                "encoder": {"id": encoder.id if encoder else None, "dim": encoder.dim if encoder else 0,
                            "sparse": bool(encoder and sparse)},
                "chunking": {}, "stats": {"documents": len(docs), "chunks": len(texts)},
                "files": {f: {"sha256": _sha(folder / f), "size": (folder / f).stat().st_size} for f in files}, "signer": None}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder


MEDICAL: Docs = {
    "first-aid.md": [
        ("Severe bleeding: apply firm direct pressure on the wound with a clean cloth. Keep pressing for at least ten minutes.", 1,
         "Bleeding control"),
        ("If bleeding from a limb does not stop, apply a tourniquet 5-7 cm above the wound and note the time.", 1, "Bleeding control"),
        ("Burns: cool the burn under cool running water for twenty minutes. Do not apply ice or butter.", 2, "Burns"),
        ("Cover the burn loosely with cling film or a clean plastic bag.", 2, "Burns"),
    ],
    "pharmacy.txt": [
        ("Paracetamol adult dose is 500 mg to 1 g every 4 to 6 hours, maximum 4 g per day.", 3, "Analgesics"),
        ("Ibuprofen should be taken with food; avoid in stomach ulcers.", 3, "Analgesics"),
    ],
    "codes.txt": [
        ("Pneumonia, unspecified organism is coded J18.9 in ICD-10.", None, "Respiratory"),
        ("Acute bronchitis is coded J20 in ICD-10.", None, "Respiratory"),
    ],
}

WATER: Docs = {
    "water.md": [
        ("Boil water for at least one minute to make it safe to drink.", None, "Water purification"),
        ("At altitudes above 2000 m boil water for three minutes.", None, "Water purification"),
    ],
}


def make_home(tmp: Path, *, encoder: HashingEncoder | None = None, extra: dict[str, Docs] | None = None) -> Path:
    """A Kovcheg home with modules 'medical' and 'water' (and `extra`), BM25-only unless an encoder is given."""
    home = Path(tmp)
    (home / "modules").mkdir(parents=True, exist_ok=True)
    make_module(home / "modules", "medical", MEDICAL, encoder)
    make_module(home / "modules", "water", WATER, encoder)
    for name, docs in (extra or {}).items():
        make_module(home / "modules", name, docs, encoder)
    return home


def overrides(encoder: HashingEncoder | None = None, *, llm: str = "", rerank: bool = False) -> dict:
    """Settings overrides that never touch real models."""
    return {"embedding": {"model": encoder.id if encoder else ""}, "rerank": {"enabled": rerank, "model": ""}, "llm": {"model": llm}}


class FakeReranker:
    """Scores passages by the fraction of query words they contain, mapped to logits in [-8, 8]."""

    id = "fake-reranker"

    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        if self.fail:
            raise self.fail
        import re
        q = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
        out = []
        for p in passages:
            words = set(re.findall(r"\w+", p.lower()))
            out.append(-8.0 + 16.0 * (len(q & words) / max(len(q), 1)))
        return out


def hit_paths(hits: Sequence[Hit]) -> list[str]:
    return [h.chunk.doc_path for h in hits]


def collect(it: Iterator) -> tuple[str, object]:
    text, final = "", None
    for x in it:
        if isinstance(x, str):
            text += x
        else:
            final = x
    return text, final
