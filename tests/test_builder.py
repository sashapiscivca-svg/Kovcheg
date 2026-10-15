import json
import sqlite3

import numpy as np
import pytest
from build_helpers import ENC, make_settings, write_sources
from test_readers import make_zim

from kovcheg import builder as builder_mod
from kovcheg.builder import BuildError, build_module, sanitize_module_name
from kovcheg.embedding import HashingEncoder
from kovcheg.store import ModuleIndex


def _docs(path):
    with ModuleIndex.open(path) as m:
        return {d["path"]: d for d in m.documents()}


def _texts(path):
    with ModuleIndex.open(path) as m:
        return sorted(c.text for c in m.chunks(range(1, 10_000)))


@pytest.mark.parametrize("bad", ["", " ", ".", "..", "../x", "a/b", "a\\b", "x.y", "-x", "a b"])
def test_sanitize_rejects(bad):
    with pytest.raises(ValueError):
        sanitize_module_name(bad)


def test_sanitize_accepts_unicode():
    assert sanitize_module_name(" медицина_2-ok ") == "медицина_2-ok"


def test_build_report_and_files(tmp_path):
    s = make_settings(tmp_path)
    src = write_sources(tmp_path / "src", {"a.txt": "J18.9 pneumonia code.", "b.bin": b"\x00\x01", "c.exe": b"MZ", ".hidden.txt": "x"})
    events = []
    rep = build_module(s, "m", src, encoder=ENC, progress=lambda *a: events.append(a), description="desc")
    assert rep.added == 1 and rep.documents == 1 and rep.chunks == 1
    assert {p for p, _ in rep.skipped} == {"b.bin", "c.exe"}
    assert any(e[0] == "finalize" for e in events)
    files = {p.name for p in rep.path.iterdir()}
    assert files == {"kovcheg.db", "dense.f16.npy", "sparse.npz", "manifest.json"}
    mf = json.loads((rep.path / "manifest.json").read_text())
    assert mf["version"] == 2 and mf["encoder"] == {"id": ENC.id, "dim": ENC.dim, "sparse": True} and mf["description"] == "desc"
    assert set(mf["files"]) == {"kovcheg.db", "dense.f16.npy", "sparse.npz"} and mf["signer"] is None
    con = sqlite3.connect(rep.path / "kovcheg.db")
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert con.execute("PRAGMA user_version").fetchone()[0] == 2
    assert not con.execute("SELECT name FROM sqlite_master WHERE name = '_seen'").fetchall()
    con.close()
    assert not list(s.modules_dir.glob(".*"))


def test_incremental_add_change_delete(tmp_path):
    s = make_settings(tmp_path)
    src = write_sources(tmp_path / "src")
    r1 = build_module(s, "m", src, encoder=ENC)
    assert r1.added == 4
    ids1 = {p: d["id"] for p, d in _docs(r1.path).items()}

    r2 = build_module(s, "m", src, encoder=ENC)
    assert r2.up_to_date and r2.unchanged == 4 and r2.added == r2.updated == r2.removed == 0

    (src / "codes.txt").write_text("Cholera is coded A00 in ICD-10.")
    (src / "notes/water.txt").unlink()
    (src / "new.md").write_text("# New\n\nSnake bite: keep the limb still.")
    r3 = build_module(s, "m", src, encoder=ENC)
    assert (r3.added, r3.updated, r3.removed, r3.unchanged) == (1, 1, 1, 2)
    docs = _docs(r3.path)
    assert set(docs) == {"first-aid.md", "codes.txt", "page.html", "new.md"}
    assert docs["first-aid.md"]["id"] == ids1["first-aid.md"]          # untouched documents keep their ids
    with ModuleIndex.open(r3.path) as m:
        assert not m.bm25("J18.9", 5) and m.bm25("A00", 5)
        # every chunk has exactly one dense row and dense rows equal a fresh encoding (carried-over rows not scrambled)
        rows = m.row_chunk_ids()
        assert sorted(rows) == sorted(set(rows)) and len(rows) == m.n_chunks
        d = m.dense().astype(np.float32)
        from kovcheg.chunking import embedding_text
        for i, cid in enumerate(rows):
            c = m.chunks([int(cid)])[0]
            ref = ENC.encode([embedding_text(c.text, c.doc_title, c.section)]).dense[0]
            assert np.allclose(d[i], ref, atol=2e-3)
        sp = m.sparse_postings()
        assert set(np.unique(sp.chunk_ids)) == set(int(x) for x in rows)


def test_encoder_change_reencodes(tmp_path):
    s = make_settings(tmp_path)
    src = write_sources(tmp_path / "src")
    build_module(s, "m", src, encoder=ENC)
    r = build_module(s, "m", src, encoder=HashingEncoder(32))
    assert any("encoder changed" in m for m in r.messages) and r.added == 4
    with ModuleIndex.open(r.path) as m:
        assert m.dim == 32 and m.dense().shape[1] == 32
    r = build_module(s, "m", src, encoder=None)
    assert any("encoder changed" in m for m in r.messages)
    with ModuleIndex.open(r.path) as m:
        assert not m.has_dense and not (r.path / "sparse.npz").exists()


def test_chunking_change_reindexes(tmp_path):
    s = make_settings(tmp_path)
    src = write_sources(tmp_path / "src")
    build_module(s, "m", src, encoder=None)
    s.chunking.target_chars = 50
    r = build_module(s, "m", src, encoder=None)
    assert any("chunking" in m for m in r.messages) and r.added == 4


def test_rebuild_flag_and_auto_encoder(tmp_path):
    s = make_settings(tmp_path)           # embedding.model = "" → "auto" means BM25 only
    src = write_sources(tmp_path / "src")
    r = build_module(s, "m", src)
    assert r.encoder_id is None
    r = build_module(s, "m", src, rebuild=True)
    assert r.added == 4 and not r.up_to_date


def test_crash_leaves_previous_module_intact(tmp_path, monkeypatch):
    s = make_settings(tmp_path)
    src = write_sources(tmp_path / "src")
    r1 = build_module(s, "m", src, encoder=ENC)
    before = {p.name: p.read_bytes() for p in r1.path.iterdir()}
    (src / "codes.txt").write_text("Changed content A00.")

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(builder_mod.ModuleWriter, "finalize", boom)
    with pytest.raises(KeyboardInterrupt):
        build_module(s, "m", src, encoder=ENC)
    assert {p.name: p.read_bytes() for p in r1.path.iterdir()} == before
    assert not list(s.modules_dir.glob(".*"))
    monkeypatch.undo()
    r = build_module(s, "m", src, encoder=ENC)
    assert r.updated == 1


def test_recover_interrupted_swap(tmp_path):
    s = make_settings(tmp_path)
    src = write_sources(tmp_path / "src")
    r1 = build_module(s, "m", src, encoder=None)
    r1.path.rename(r1.path.with_name(".m.old"))          # crash after the first rename of the swap
    r = build_module(s, "m", src, encoder=None)
    assert r.up_to_date and not (s.modules_dir / ".m.old").exists()


def test_errors(tmp_path):
    s = make_settings(tmp_path)
    with pytest.raises(BuildError, match="source folder"):
        build_module(s, "m", tmp_path / "nope", encoder=None)
    legacy = s.modules_dir / "old"
    legacy.mkdir(parents=True)
    (legacy / "search_bge.db").write_bytes(b"")
    with pytest.raises(BuildError, match="migrate"):
        build_module(s, "old", write_sources(tmp_path / "src"), encoder=None)


def test_default_source_folder(tmp_path):
    s = make_settings(tmp_path)
    write_sources(s.sources_dir / "kb")
    assert build_module(s, "kb", encoder=None).documents == 4


def test_zim_incremental_no_duplicates(tmp_path):
    s = make_settings(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    arts = [(f"A/{i}", f"Article {i}", f"<html><body><p>Body of article {i} about topic{i}.</p></body></html>") for i in range(4)]
    make_zim(src / "wiki.zim", arts)
    r1 = build_module(s, "w", src, encoder=ENC)
    assert r1.added == 4 and r1.documents == 4
    assert set(_docs(r1.path)) == {f"wiki.zim/A/{i}" for i in range(4)}
    assert _docs(r1.path)["wiki.zim/A/2"]["title"] == "Article 2"

    r2 = build_module(s, "w", src, encoder=ENC)
    assert r2.up_to_date and r2.unchanged == 4

    arts2 = arts[:2] + [("A/2", "Article 2", "<html><body><p>Rewritten article two, topic2.</p></body></html>")]
    (src / "wiki.zim").unlink()
    make_zim(src / "wiki.zim", arts2)
    r3 = build_module(s, "w", src, encoder=ENC)
    assert (r3.added, r3.updated, r3.removed, r3.unchanged) == (0, 1, 1, 2)
    docs = _docs(r3.path)
    assert set(docs) == {"wiki.zim/A/0", "wiki.zim/A/1", "wiki.zim/A/2"}
    texts = _texts(r3.path)
    assert len(texts) == len(set(texts)) == 3 and any("Rewritten" in t for t in texts)


def test_signs_when_private_key_present(tmp_path):
    pytest.importorskip("cryptography")
    from kovcheg.security import keygen, verify_module
    s = make_settings(tmp_path)
    keygen(s.keys_dir)
    r = build_module(s, "m", write_sources(tmp_path / "src"), encoder=None)
    assert r.signed_by and (r.path / "manifest.sig").exists()
    v = verify_module(r.path, s.keys_dir, deep=True)
    assert v.status == "valid" and v.key_id == r.signed_by
