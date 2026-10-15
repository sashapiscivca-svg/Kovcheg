"""Convert a legacy v1 module (`search_bge.db`, table `docs` with float32 dense blobs and JSON sparse weights) to format v2
in place, without re-encoding. Dense vectors become float16 (re-normalised), sparse JSON becomes int32/float16 blobs,
documents are derived from distinct filenames (page/section unknown → NULL). The keyword graph is dropped.
Duplicate chunks of one document (same text, produced by re-runs of the old builder) are removed.
The old database is kept as `search_bge.db.v1` unless delete_old=True.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import __version__
from .store import DB_NAME, FORMAT, LEGACY_DB_NAME, MANIFEST_NAME, SIG_NAME, ModuleWriter, file_entries, write_json_atomic

LEGACY_ENCODER_ID = "bge-m3"


@dataclass
class MigrateReport:
    path: Path
    documents: int = 0
    chunks: int = 0
    duplicates_removed: int = 0
    dim: int = 0
    signed_by: str | None = None
    messages: list[str] = field(default_factory=list)


def _kind(filename: str) -> str:
    if filename.startswith("Wiki: "):
        return "zim"
    ext = Path(filename).suffix.lower().lstrip(".")
    return {"md": "markdown", "markdown": "markdown", "htm": "html", "html": "html", "pdf": "pdf", "docx": "docx"}.get(ext, "text")


def _sparse(js: str | None) -> dict[int, float]:
    if not js:
        return {}
    try:
        d = json.loads(js)
    except ValueError:
        return {}
    out: dict[int, float] = {}
    for k, v in d.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def migrate_module(path: Path, *, delete_old: bool = False, keys_dir: Path | None = None, block: int = 2048) -> MigrateReport:
    """Migrate the v1 module in folder `path` to v2 in place. Signs the result if keys_dir has a private key."""
    path = Path(path)
    old_db = path / LEGACY_DB_NAME
    if not old_db.exists():
        raise FileNotFoundError(f"{path}: no legacy {LEGACY_DB_NAME} to migrate")
    if (path / DB_NAME).exists():
        raise FileExistsError(f"{path}: already contains a v2 {DB_NAME}")
    report = MigrateReport(path)
    old_manifest: dict = {}
    try:
        old_manifest = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    name = path.name
    work = path / ".migrate.tmp"
    if work.exists():
        shutil.rmtree(work)
    src = sqlite3.connect(old_db.resolve().as_uri() + "?mode=ro", uri=True)
    w: ModuleWriter | None = None
    try:
        cols = {r[1] for r in src.execute("PRAGMA table_info(docs)")}
        if not {"filename", "content", "dense_vec"} <= cols:
            raise ValueError(f"{old_db}: not a v1 Kovcheg database (table docs is missing columns)")
        has_idx, has_hash, has_sparse = "chunk_idx" in cols, "file_hash" in cols, "sparse_vec" in cols
        w = ModuleWriter(work, name=name)
        dim = 0
        filenames = [r[0] for r in src.execute("SELECT DISTINCT filename FROM docs ORDER BY filename")]
        order = "COALESCE(chunk_idx, 0), id" if has_idx else "id"
        any_sparse = False
        for fn in filenames:
            q = (f"SELECT content, dense_vec, {'sparse_vec' if has_sparse else 'NULL'}, {'file_hash' if has_hash else 'NULL'} "
                 f"FROM docs WHERE filename = ? ORDER BY {order}")
            rows = src.execute(q, (fn,)).fetchall()
            seen: set[str] = set()
            texts, dense, sparse = [], [], []
            file_hash = None
            for content, dv, sv, fh in rows:
                if not content or content in seen:
                    report.duplicates_removed += bool(content)
                    continue
                seen.add(content)
                v = np.frombuffer(dv, np.float32) if dv else None
                if v is None or v.size == 0:
                    raise ValueError(f"{fn}: chunk without dense vector")
                if dim == 0:
                    dim = v.size
                elif v.size != dim:
                    raise ValueError(f"{fn}: inconsistent vector size {v.size} (expected {dim})")
                texts.append(content)
                dense.append(v)
                s = _sparse(sv)
                any_sparse |= bool(s)
                sparse.append(s)
                file_hash = file_hash or fh
            if not texts:
                continue
            sha = file_hash or hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
            title = fn[len("Wiki: "):] if fn.startswith("Wiki: ") else Path(fn).stem or fn
            _, ids = w.add_document(fn, title=title, kind=_kind(fn), sha256=sha, size=None, chunks=[(t, None, None) for t in texts])
            d = np.vstack(dense)
            d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)
            w.dim = dim
            w.add_vectors(ids, d, sparse)
            report.documents += 1
            report.chunks += len(ids)
        if report.chunks == 0:
            raise ValueError(f"{old_db}: no chunks to migrate")
        if dim != 1024:
            report.messages.append(f"vector size is {dim}, not 1024: the module may not have been built with BGE-M3")
        w.set_meta(encoder_id=LEGACY_ENCODER_ID, dim=dim, chunking="legacy-v1")
        stats = w.finalize(old_dense=None, encoder_id=LEGACY_ENCODER_ID, has_sparse=any_sparse, block=block)
        w = None
        report.dim = dim
        now = datetime.now(UTC).isoformat(timespec="seconds")
        manifest = {
            "format": FORMAT, "version": 2, "name": name,
            "title": old_manifest.get("title") or old_manifest.get("name") or name,
            "description": old_manifest.get("description", ""), "language": old_manifest.get("language", ""),
            "created_at": old_manifest.get("created_at") or old_manifest.get("created") or now, "updated_at": now,
            "kovcheg_version": __version__,
            "encoder": {"id": LEGACY_ENCODER_ID, "dim": dim, "sparse": any_sparse},
            "chunking": {"legacy": "v1"}, "stats": stats, "files": file_entries(work), "signer": None,
            "migrated_from": "v1",
        }
        write_json_atomic(work / MANIFEST_NAME, manifest)
    except BaseException:
        if w is not None:
            w.abort()
        src.close()
        shutil.rmtree(work, ignore_errors=True)
        raise
    src.close()
    # move the new files in; the stale v1 signature and manifest are replaced
    (path / SIG_NAME).unlink(missing_ok=True)
    for f in sorted(work.iterdir()):
        if f.name != MANIFEST_NAME:
            os.replace(f, path / f.name)
    if delete_old:
        old_db.unlink()
    else:
        os.replace(old_db, path / (LEGACY_DB_NAME + ".v1"))
    for side in ("-wal", "-shm", "-journal"):
        (path / (LEGACY_DB_NAME + side)).unlink(missing_ok=True)
    os.replace(work / MANIFEST_NAME, path / MANIFEST_NAME)
    shutil.rmtree(work, ignore_errors=True)
    (path / ".verified.json").unlink(missing_ok=True)
    from .security import has_private_key, sign_module
    if has_private_key(keys_dir):
        try:
            report.signed_by = sign_module(path, keys_dir)
        except Exception as e:  # noqa: BLE001
            report.messages.append(f"module NOT signed: {e}")
    return report
