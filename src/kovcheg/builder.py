"""Build or update a module from a folder of documents.

Incremental: every document (a file, or one article of a ZIM archive keyed `<zim path>/<entry path>`) is identified by
its path and sha256; unchanged documents keep their chunks and vectors, changed ones are re-read and re-encoded, removed
ones are deleted. A change of encoder (or of the chunking settings) re-indexes everything.

Atomic: the module is built in a hidden work folder `<modules>/.<name>.building/` (the previous database is copied
there; previous dense vectors are read from the old module). Only after the work folder is complete (database
finalized, journal_mode DELETE, manifest written, optionally signed) is it swapped in by two renames. A crash or
Ctrl-C leaves the previous module untouched; a crash in between the two renames is repaired at the next build.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import __version__
from .chunking import chunk_sections, embedding_text
from .config import Settings
from .readers import SkipFile, iter_zim, read_file
from .store import (
    DB_NAME,
    DENSE_NAME,
    FORMAT,
    LEGACY_DB_NAME,
    MANIFEST_NAME,
    SIG_NAME,
    ModuleWriter,
    connect_ro,
    file_entries,
    sha256_file,
    write_json_atomic,
)

ProgressFn = Callable[[str, int, int | None, str], None]
"""progress(stage, done, total, item): stage is 'scan' | 'index' | 'finalize'; total is None when unknown (ZIM)."""

_NAME_OK = re.compile(r"^[\w\-]+$", re.UNICODE)
_COMMIT_EVERY = 2000          # chunks
_ENCODE_BATCH = 64            # chunks per encoder call


class BuildError(Exception):
    pass


def sanitize_module_name(name: str) -> str:
    """Validate a module name: Unicode letters, digits, '-' and '_' only (no dots, slashes or path traversal)."""
    s = unicodedata.normalize("NFC", (name or "").strip())
    if not s or not _NAME_OK.match(s) or s.startswith("-"):
        raise ValueError(f"invalid module name {name!r}: use letters, digits, '-' and '_' only")
    return s


@dataclass
class BuildReport:
    name: str
    path: Path
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)     # (relative path, reason)
    documents: int = 0
    chunks: int = 0
    new_chunks: int = 0
    encoder_id: str | None = None
    signed_by: str | None = None
    up_to_date: bool = False
    messages: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def summary(self) -> str:
        s = (f"{self.name}: {self.documents} documents, {self.chunks} chunks "
             f"(+{self.added} new, {self.updated} updated, {self.removed} removed, {self.unchanged} unchanged, {len(self.skipped)} skipped)")
        if self.up_to_date:
            s += " — already up to date"
        return s


def _iter_source(source: Path) -> list[Path]:
    out = []
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.startswith("."):
                out.append(Path(root) / f)
    return out


def _chunking_sig(settings: Settings) -> str:
    c = settings.chunking
    return f"{c.target_chars}/{c.max_chars}/{c.overlap_sentences}/{c.min_chars}"


def _recover(module_dir: Path) -> None:
    """Finish or undo an interrupted swap from a previous run."""
    old = module_dir.with_name(f".{module_dir.name}.old")
    if old.exists():
        if module_dir.exists():
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(old, module_dir)


class _Builder:
    def __init__(self, settings: Settings, name: str, source: Path, encoder, progress: ProgressFn | None, report: BuildReport):
        self.settings, self.name, self.source, self.encoder = settings, name, source, encoder
        self.progress = progress or (lambda *a: None)
        self.report = report
        self.pending: list[tuple[int, str]] = []      # (chunk id, embedding text)
        self.since_commit = 0
        self.w: ModuleWriter | None = None

    # ---- encoding -----------------------------------------------------------------------------
    def queue(self, ids: list[int], texts: list[str]) -> None:
        if self.encoder is not None:
            self.pending.extend(zip(ids, texts, strict=True))
            if len(self.pending) >= _ENCODE_BATCH:
                self.flush()
        self.since_commit += len(ids)
        if self.since_commit >= _COMMIT_EVERY:
            self.flush()
            self.w.commit()
            self.since_commit = 0

    def flush(self) -> None:
        if not self.pending or self.encoder is None:
            return
        ids = [i for i, _ in self.pending]
        enc = self.encoder.encode([t for _, t in self.pending])
        self.w.add_vectors(ids, enc.dense, enc.sparse if self.encoder.has_sparse else None)
        self.pending.clear()

    def index_document(self, path: str, doc, sha: str, size: int | None, existed: bool) -> None:
        pieces = chunk_sections(doc.sections, self.settings.chunking)
        if not pieces:
            self.report.skipped.append((path, "no text after chunking"))
            old = self.w.find_document(path)
            if old:                                    # it changed to empty: remove the stale version
                self.w.delete_document(old[0])
            return
        _, ids = self.w.add_document(path, title=doc.title, kind=doc.kind, sha256=sha, size=size,
                                     chunks=[(p.text, p.page, p.section) for p in pieces])
        self.queue(ids, [embedding_text(p.text, doc.title, p.section) for p in pieces])
        self.report.new_chunks += len(ids)
        if existed:
            self.report.updated += 1
        else:
            self.report.added += 1

    # ---- sources ------------------------------------------------------------------------------
    def file(self, f: Path, rel: str) -> None:
        try:
            sha = sha256_file(f)
        except OSError as e:
            self.report.skipped.append((rel, f"unreadable: {e}"))
            return
        old = self.w.find_document(rel)
        if old and old[1] == sha:
            self.w.mark_seen(old[0])
            self.report.unchanged += 1
            return
        try:
            doc = read_file(f)
        except SkipFile as e:
            self.report.skipped.append((rel, str(e)))
            return
        except Exception as e:  # noqa: BLE001 — a broken file must not abort the build
            self.report.skipped.append((rel, f"read error: {type(e).__name__}: {e}"))
            return
        self.index_document(rel, doc, sha, f.stat().st_size, existed=old is not None)

    def zim(self, f: Path, rel: str) -> None:
        try:
            sha = sha256_file(f)
        except OSError as e:
            self.report.skipped.append((rel, f"unreadable: {e}"))
            return
        meta_key = f"zim:{rel}"
        prefix = rel + "/"
        if self.w.get_meta(meta_key) == sha:
            n = self.w.mark_seen_prefix(prefix)
            self.report.unchanged += n
            return
        try:
            articles = iter_zim(f)
            n_art = 0
            for art in articles:
                path = prefix + art.path
                old = self.w.find_document(path)
                if old and old[1] == art.sha256:
                    self.w.mark_seen(old[0])
                    self.report.unchanged += 1
                    continue
                try:
                    doc = art.parse()
                except Exception as e:  # noqa: BLE001
                    self.report.skipped.append((path, f"parse error: {e}"))
                    continue
                self.index_document(path, doc, art.sha256, art.size, existed=old is not None)
                n_art += 1
                if n_art % 100 == 0:
                    self.progress("index", n_art, None, path)
        except SkipFile as e:
            self.report.skipped.append((rel, str(e)))
            self.w.mark_seen_prefix(prefix)          # keep previously indexed articles if the archive cannot be read now
            return
        self.w.set_meta(**{meta_key: sha})


def _open_old(module_dir: Path) -> tuple[dict, np.ndarray | None]:
    """meta and dense memmap of an existing v2 module ({} if none)."""
    db = module_dir / DB_NAME
    if not db.exists():
        if (module_dir / LEGACY_DB_NAME).exists():
            raise BuildError(f"{module_dir.name} is a legacy v1 module: run `kovcheg migrate {module_dir.name}` first, or rebuild")
        return {}, None
    conn = connect_ro(db)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if meta.get("format") != FORMAT or ver != 2:
        raise BuildError(f"{module_dir.name}: unknown module format; use rebuild")
    dense = np.load(module_dir / DENSE_NAME, mmap_mode="r") if (module_dir / DENSE_NAME).exists() else None
    return meta, dense


def build_module(settings: Settings, name: str, source: Path | None = None, *, title: str | None = None,
                 description: str | None = None, language: str | None = None, rebuild: bool = False,
                 encoder="auto", progress: ProgressFn | None = None, keys_dir: Path | None = None,
                 vacuum: bool | None = None) -> BuildReport:
    """Create or incrementally update module `name` from `source` (default: <sources>/<name>).

    encoder: "auto" = load_encoder(settings) (None if disabled), None = BM25 only, or an Encoder instance.
    keys_dir: where to look for private_key.pem to sign the module (default: settings.keys_dir).
    """
    t0 = time.monotonic()
    name = sanitize_module_name(name)
    source = Path(source) if source is not None else settings.sources_dir / name
    if not source.is_dir():
        raise BuildError(f"source folder not found: {source}")
    if encoder == "auto":
        from .embedding import load_encoder
        encoder = load_encoder(settings)
    keys_dir = Path(keys_dir) if keys_dir is not None else settings.keys_dir
    modules_dir = settings.modules_dir
    modules_dir.mkdir(parents=True, exist_ok=True)
    module_dir = modules_dir / name
    work = modules_dir / f".{name}.building"
    report = BuildReport(name=name, path=module_dir, encoder_id=encoder.id if encoder else None)
    _recover(module_dir)
    if work.exists():
        shutil.rmtree(work)

    old_meta, old_dense, old_manifest = {}, None, {}
    if module_dir.exists() and not rebuild:
        old_meta, old_dense = _open_old(module_dir)
        try:
            old_manifest = json.loads((module_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old_manifest = {}
    enc_id = encoder.id if encoder else ""
    enc_dim = int(encoder.dim) if encoder else 0
    fresh = not old_meta
    if old_meta:
        prev_enc, prev_dim = old_meta.get("encoder_id", ""), int(old_meta.get("dim") or 0)
        if (prev_enc, prev_dim if prev_enc else 0) != (enc_id, enc_dim):
            report.messages.append(f"encoder changed ({prev_enc or 'none'} -> {enc_id or 'none'}): re-indexing all documents")
            fresh = True
        elif old_meta.get("chunking") != _chunking_sig(settings):
            report.messages.append("chunking settings changed: re-indexing all documents")
            fresh = True

    b = _Builder(settings, name, source, encoder, progress, report)
    try:
        work.mkdir(parents=True)
        if not fresh:
            shutil.copyfile(module_dir / DB_NAME, work / DB_NAME)
        else:
            old_dense = None
        w = b.w = ModuleWriter(work, name=name)
        w.set_meta(chunking=_chunking_sig(settings), encoder_id=enc_id, dim=enc_dim)
        if encoder is not None:
            w.dim = enc_dim
        w.conn.execute("DELETE FROM _seen")

        files = _iter_source(source)
        b.progress("scan", 0, len(files), "")
        for i, f in enumerate(files):
            rel = f.relative_to(source).as_posix()
            b.progress("index", i, len(files), rel)
            if f.suffix.lower() == ".zim":
                b.zim(f, rel)
            else:
                b.file(f, rel)
        b.flush()
        removed = w.delete_unseen()
        report.removed = len(removed)
        for k in [r[0] for r in w.conn.execute("SELECT key FROM meta WHERE key LIKE 'zim:%'")]:
            if not (source / k[4:]).exists():
                w.conn.execute("DELETE FROM meta WHERE key = ?", (k,))
        w.commit()

        meta_same = all(v is None or old_manifest.get(k) == v for k, v in (("title", title), ("description", description), ("language", language)))
        if (not fresh and report.added == 0 and report.updated == 0 and report.removed == 0 and meta_same
                and (module_dir / MANIFEST_NAME).exists()):
            w.abort()
            shutil.rmtree(work, ignore_errors=True)
            report.up_to_date = True
            report.documents = report.unchanged
            report.chunks = int(old_manifest.get("stats", {}).get("chunks", 0))
            report.signed_by = old_manifest.get("signer")
            report.seconds = time.monotonic() - t0
            return report

        b.progress("finalize", 0, None, "")
        stats = w.finalize(old_dense=old_dense, encoder_id=enc_id, has_sparse=bool(encoder and encoder.has_sparse), vacuum=vacuum)
        old_dense = None
        report.documents, report.chunks = stats["documents"], stats["chunks"]
        now = datetime.now(UTC).isoformat(timespec="seconds")
        c = settings.chunking
        manifest = {
            "format": FORMAT, "version": 2, "name": name,
            "title": title if title is not None else old_manifest.get("title", name),
            "description": description if description is not None else old_manifest.get("description", ""),
            "language": language if language is not None else old_manifest.get("language", ""),
            "created_at": old_manifest.get("created_at", now) if not rebuild else now,
            "updated_at": now, "kovcheg_version": __version__,
            "encoder": {"id": enc_id or None, "dim": enc_dim, "sparse": bool(encoder and encoder.has_sparse)},
            "chunking": {"target_chars": c.target_chars, "max_chars": c.max_chars, "overlap_sentences": c.overlap_sentences,
                         "min_chars": c.min_chars, "embedding_prefix": "title — section: "},
            "stats": stats, "files": file_entries(work), "signer": None,
        }
        write_json_atomic(work / MANIFEST_NAME, manifest)
        from .security import has_private_key, sign_module
        if has_private_key(keys_dir):
            try:
                report.signed_by = sign_module(work, keys_dir)
            except Exception as e:  # noqa: BLE001
                report.messages.append(f"module NOT signed: {e}")
        _swap(work, module_dir)
    except BaseException:
        if b.w is not None:
            b.w.abort()
        shutil.rmtree(work, ignore_errors=True)
        raise
    report.seconds = time.monotonic() - t0
    return report


def _swap(work: Path, module_dir: Path) -> None:
    old = module_dir.with_name(f".{module_dir.name}.old")
    if old.exists():
        shutil.rmtree(old)
    if module_dir.exists():
        os.replace(module_dir, old)
    os.replace(work, module_dir)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    (module_dir / f"{SIG_NAME}.tmp").unlink(missing_ok=True)
