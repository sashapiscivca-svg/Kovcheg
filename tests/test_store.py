import sqlite3

import numpy as np
import pytest
from build_helpers import ENC, make_settings, write_sources

from kovcheg.builder import build_module
from kovcheg.store import ModuleFormatError, ModuleIndex, fts_query


@pytest.fixture
def module(tmp_path):
    s = make_settings(tmp_path, target_chars=60, max_chars=120, overlap_sentences=0, min_chars=10)
    src = write_sources(tmp_path / "src")
    rep = build_module(s, "med", src, encoder=ENC, title="Medical")
    idx = ModuleIndex.open(rep.path)
    yield idx
    idx.close()


def test_fts_query_sanitises():
    assert fts_query('J18.9 "oops" AND (x*') == '"J18.9" OR "oops" OR "AND" OR "(x*"'
    assert fts_query("  ... ;; ") == ""
    assert fts_query('a"b') == '"a" OR "b"'


def test_open_attributes(module):
    assert module.name == "med"
    assert module.manifest["title"] == "Medical"
    assert module.encoder_id == ENC.id and module.dim == ENC.dim
    assert module.has_dense and module.has_sparse
    assert module.n_chunks == len(module.row_chunk_ids())


def test_bm25_exact_code(module):
    hits = module.bm25("what is J18.9?", 5)
    assert hits
    top = module.chunks([hits[0][0]])[0]
    assert "J18.9" in top.text and top.doc_path == "codes.txt"
    assert all(a[1] >= b[1] for a, b in zip(hits, hits[1:], strict=False))
    assert module.bm25("", 5) == [] and module.bm25('"(', 5) == []
    assert module.bm25("NAVJUNK SCRIPTJUNK FOOTERJUNK", 5) == []      # boilerplate stripped


def test_dense_top1_is_same_chunk(module):
    d = module.dense()
    assert d.dtype == np.float16 and d.shape == (module.n_chunks, ENC.dim)
    assert np.allclose(np.linalg.norm(d.astype(np.float32), axis=1), 1, atol=1e-2)
    rows = module.row_chunk_ids()
    from kovcheg.chunking import embedding_text
    for cid in rows:
        ch = module.chunks([int(cid)])[0]
        q = ENC.encode([embedding_text(ch.text, ch.doc_title, ch.section)]).dense[0]
        best = int(np.argmax(d.astype(np.float32) @ q))
        assert rows[best] == cid


def test_sparse_postings(module):
    sp = module.sparse_postings()
    assert sp.token_ids.dtype == np.int32 and sp.weights.dtype == np.float16
    assert np.all(np.diff(sp.token_ids) > 0) and sp.indptr[-1] == len(sp.chunk_ids)
    tok = ENC._tok("J18")
    cids, w = sp.lookup(tok)
    texts = [c.text for c in module.chunks(cids)]
    assert texts and all("J18" in t for t in texts)
    assert sp.lookup(-5)[0].size == 0


def test_chunks_order_and_fields(module):
    ids = [int(x) for x in module.row_chunk_ids()][::-1]
    chs = module.chunks(ids + [999999])
    assert [c.id for c in chs] == ids
    fa = [c for c in chs if c.doc_path == "first-aid.md"]
    assert fa and all(c.doc_title == "First aid" and c.module == "med" for c in fa)
    assert {c.section for c in fa} >= {"Bleeding control", "Burns"}


def test_neighbors(module):
    fa = sorted((c for c in module.chunks(module.row_chunk_ids()) if c.doc_path == "first-aid.md"), key=lambda c: c.idx)
    assert len(fa) >= 3
    mid = fa[1]
    nb = module.neighbors(mid.id, 1, 1)
    assert [c.idx for c in nb] == [mid.idx - 1, mid.idx + 1]
    assert [c.idx for c in module.neighbors(fa[0].id, 2, 0)] == []
    assert [c.idx for c in module.neighbors(fa[0].id, 0, 5)] == [c.idx for c in fa[1:6]]
    assert module.neighbors(123456, 1, 1) == []


def test_documents(module):
    docs = {d["path"]: d for d in module.documents()}
    assert set(docs) == {"first-aid.md", "codes.txt", "notes/water.txt", "page.html"}
    assert docs["page.html"]["title"] == "Field guide" and docs["page.html"]["kind"] == "html"
    assert all(d["n_chunks"] >= 1 for d in docs.values())


def test_readonly_and_no_wal(module):
    assert not list(module.path.glob("*-wal")) and not list(module.path.glob("*-journal"))
    with pytest.raises(sqlite3.OperationalError):
        module._conn.execute("DELETE FROM chunks")


def test_bm25_only_module(tmp_path):
    s = make_settings(tmp_path)
    rep = build_module(s, "lex", write_sources(tmp_path / "src"), encoder=None)
    with ModuleIndex.open(rep.path) as m:
        assert not m.has_dense and not m.has_sparse and m.encoder_id is None and m.dim == 0
        assert m.bm25("J18.9", 3)
        assert len(m.row_chunk_ids()) == 0
        with pytest.raises(ModuleFormatError):
            m.dense()
    assert not (rep.path / "dense.f16.npy").exists()


def test_open_errors(tmp_path):
    with pytest.raises(ModuleFormatError, match="not a Kovcheg module"):
        ModuleIndex.open(tmp_path)
    (tmp_path / "search_bge.db").write_bytes(b"")
    with pytest.raises(ModuleFormatError, match="kovcheg migrate"):
        ModuleIndex.open(tmp_path)
    (tmp_path / "kovcheg.db").write_bytes(b"not sqlite at all" * 100)
    with pytest.raises(ModuleFormatError):
        ModuleIndex.open(tmp_path)
