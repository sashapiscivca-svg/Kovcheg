import shutil
import sqlite3
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from helpers import MEDICAL, hit_paths, make_module

from kovcheg.config import Settings
from kovcheg.embedding import HashingEncoder
from kovcheg.retrieval import (
    IndexCache,
    Retriever,
    cap_per_document,
    coverage,
    dedup,
    dense_search,
    expand_context,
    fts_query,
    hit_text,
    query_terms,
    select,
    sparse_search,
    stitch,
)
from kovcheg.types import Chunk, Hit

ENC = HashingEncoder(128)


def _settings(tmp_path, **retrieval):
    s = Settings(home=tmp_path)
    for k, v in retrieval.items():
        setattr(s.retrieval, k, v)
    return s


def _search(tmp_path, names, q, encoder=None, n=8, **kw):
    cache = IndexCache()
    handles = [cache.get(tmp_path / "modules" / m) for m in names]
    r = Retriever(_settings(tmp_path, **kw), encoder)
    res = r.candidates(q, handles, n)
    return res, {h.name: h for h in handles}


# ---- FTS query ----------------------------------------------------------------------------------------------------

def test_fts_query_tokens_phrases_and_codes():
    q = fts_query("J18.9 a 500 mg")
    parts = q.split(" OR ")
    assert '"j18 9"' in parts and '"500 mg"' in parts and '"j18"' in parts and '"500"' in parts and '"mg"' in parts
    assert '"a"' not in parts and '"9"' not in parts           # 1-char tokens dropped (but kept inside phrases)
    assert fts_query("  ?! . ") == ""
    assert fts_query("x") == ""


@pytest.mark.parametrize("q", ['foo" OR bar*', "NEAR(a b)", "a AND -b", "col:term ^x", '"""', "(((", "ünïcödé — тест"])
def test_fts_query_is_always_valid_fts5(q):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE f USING fts5(text, tokenize='unicode61 remove_diacritics 2')")
    db.execute("INSERT INTO f VALUES ('foo bar near tést')")
    expr = fts_query(q)
    if expr:
        db.execute("SELECT rowid FROM f WHERE f MATCH ?", (expr,)).fetchall()


def test_query_terms_and_coverage():
    terms = query_terms("How to stop the bleeding?")
    assert terms == {"stop", "bleeding"}
    c = Chunk(1, 1, 0, "Bleeding does not stop", doc_title="t")
    assert coverage(terms, c) == 1.0
    assert query_terms("як і що") == {"як", "що"}            # all stop words: fall back to all words


# ---- vector search ------------------------------------------------------------------------------------------------

def test_dense_search_blocks_match_full_scan(tmp_path):
    rng = np.random.default_rng(0)
    m = rng.normal(size=(1000, 32)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    np.save(tmp_path / "d.npy", m.astype(np.float16))
    mm = np.load(tmp_path / "d.npy", mmap_mode="r")
    q = m[17]
    rows, scores = dense_search(mm, q, 10, block_rows=37)
    full = mm.astype(np.float32) @ q
    assert list(rows) == list(np.argsort(-full, kind="stable")[:10])
    assert rows[0] == 17 and scores[0] == pytest.approx(1.0, abs=1e-2)
    assert dense_search(mm[:0], q, 5)[0].size == 0


def test_sparse_search_matches_brute_force():
    docs = {1: {5: 0.5, 7: 0.1}, 2: {5: 0.2}, 3: {9: 1.0}, 4: {7: 0.9, 5: 0.1}}
    post = {}
    for c, d in docs.items():
        for t, w in d.items():
            post.setdefault(t, []).append((c, w))
    toks = sorted(post)
    indptr = np.cumsum([0] + [len(post[t]) for t in toks])
    p = SimpleNamespace(token_ids=np.array(toks, np.int32), indptr=indptr, chunk_ids=np.array([c for t in toks for c, _ in post[t]]),
                        weights=np.array([w for t in toks for _, w in post[t]], np.float16))
    q = {5: 1.0, 7: 0.5, 123: 9.0}
    ids, scores = sparse_search(p, q, 10)
    brute = {c: sum(q.get(t, 0) * w for t, w in d.items()) for c, d in docs.items()}
    expect = [c for c, s in sorted(brute.items(), key=lambda x: -x[1]) if s > 0]
    assert list(ids) == expect
    assert scores[0] == pytest.approx(max(brute.values()), rel=1e-2)


# ---- hybrid search over modules -----------------------------------------------------------------------------------

@pytest.mark.parametrize("encoder", [None, ENC], ids=["bm25-only", "hybrid"])
@pytest.mark.parametrize("q,expected", [("J18.9", "codes.txt"), ("500 mg", "pharmacy.txt"), ("paracetamol dose", "pharmacy.txt"),
                                        ("how to stop severe bleeding", "first-aid.md"), ("burn cool water", "first-aid.md")])
def test_exact_and_keyword_queries(tmp_path, encoder, q, expected):
    make_module(tmp_path / "modules", "medical", MEDICAL, encoder)
    res, _ = _search(tmp_path, ["medical"], q, encoder)
    assert res.hits and res.hits[0].chunk.doc_path == expected, hit_paths(res.hits)
    assert res.hits[0].bm25 is not None


def test_hybrid_uses_all_retrievers_and_scores(tmp_path):
    make_module(tmp_path / "modules", "medical", MEDICAL, ENC)
    res, _ = _search(tmp_path, ["medical"], "J18.9 pneumonia", ENC)
    assert res.retrievers["medical"] == ["bm25", "dense", "sparse"]
    top = res.hits[0]
    assert top.chunk.doc_path == "codes.txt" and top.dense is not None and top.sparse is not None and 0 < top.sparse <= 1
    assert top.chunk.module == "medical" and top.chunk.section == "Respiratory"


def test_phrase_match_ranks_first(tmp_path):
    docs = {"a.txt": ["water running cool is not for drinking; the burn needs time"], "b.txt": ["cool running water for the burn"]}
    make_module(tmp_path / "modules", "m", docs)
    res, _ = _search(tmp_path, ["m"], "cool running water", None)
    assert hit_paths(res.hits)[0] == "b.txt"


def test_bm25_ranks_across_modules_of_different_size(tmp_path):
    make_module(tmp_path / "modules", "medical", MEDICAL)
    make_module(tmp_path / "modules", "water", {"w.md": ["Boil water for one minute.", "Above 2000 m boil water for three minutes."]})
    res, _ = _search(tmp_path, ["medical", "water"], "boil water minutes")
    assert res.hits[0].chunk.module == "water"


def test_encoder_mismatch_falls_back_to_bm25(tmp_path):
    make_module(tmp_path / "modules", "medical", MEDICAL, HashingEncoder(64))
    res, _ = _search(tmp_path, ["medical"], "J18.9", ENC)
    assert res.retrievers["medical"] == ["bm25"]
    assert any("built with encoder 'hashing-64'" in w for w in res.warnings)
    assert hit_paths(res.hits)[0] == "codes.txt"
    res, _ = _search(tmp_path, ["medical"], "J18.9", None)
    assert any("embedding model not loaded" in w for w in res.warnings)


def test_weights_zero_disables_retriever(tmp_path):
    make_module(tmp_path / "modules", "medical", MEDICAL, ENC)
    res, _ = _search(tmp_path, ["medical"], "J18.9", ENC, weights={"dense": 1.0, "sparse": 0.0, "bm25": 0.0})
    assert res.retrievers["medical"] == ["dense"]
    assert all(h.bm25 is None and h.sparse is None for h in res.hits)


def test_dedup_identical_text_across_modules(tmp_path):
    make_module(tmp_path / "modules", "a", {"x.txt": ["Tourniquet above the wound.", "Unrelated text"]})
    make_module(tmp_path / "modules", "b", {"y.txt": ["Tourniquet  above the WOUND."]})
    res, _ = _search(tmp_path, ["a", "b"], "tourniquet wound")
    assert sum("tourniquet" in h.chunk.text.lower() for h in res.hits) == 1


def test_dedup_by_cosine():
    c = [Chunk(i, i, 0, f"t{i}", module="m") for i in range(3)]
    hits = [Hit(x, 1.0) for x in c]
    v = np.array([1.0, 0.0], np.float32)
    vecs = {("m", 0): v, ("m", 1): np.array([0.999, 0.04], np.float32), ("m", 2): np.array([0.0, 1.0], np.float32)}
    assert [h.chunk.id for h in dedup(hits, vecs, 0.95)] == [0, 2]


def test_cap_per_document_and_select():
    hits = [Hit(Chunk(i, i // 3, i % 3, f"t{i}", module="m"), 1.0) for i in range(9)]
    assert [h.chunk.id for h in cap_per_document(hits, 2)] == [0, 1, 3, 4, 6, 7]
    assert len(select(hits, 4, 1)) == 3
    assert len(cap_per_document(hits, 0)) == 9


def test_per_document_cap_applied_in_search(tmp_path):
    docs = {"long.txt": [f"bleeding control step {i}" for i in range(8)], "other.txt": ["bleeding is dangerous"]}
    make_module(tmp_path / "modules", "m", docs)
    res, _ = _search(tmp_path, ["m"], "bleeding", max_per_document=2)
    assert hit_paths(res.hits).count("long.txt") == 2 and "other.txt" in hit_paths(res.hits)


def test_context_expansion_after_ranking(tmp_path):
    docs = {"d.txt": ["Alpha intro sentence.", "Bravo key fact about tourniquets.", "Charlie follow-up.", "Delta tourniquet again."]}
    make_module(tmp_path / "modules", "m", docs)
    res, handles = _search(tmp_path, ["m"], "tourniquets", max_per_document=5)
    hits = select(res.hits, 1, 5)
    expand_context(hits, handles, 1)
    assert [c.idx for c in hits[0].context] == [0, 2]
    assert hit_text(hits[0]).startswith("Alpha intro") and "Charlie" in hit_text(hits[0])
    # neighbours that are hits themselves are not repeated as context
    both = select(res.hits, 2, 5)
    for h in both:
        h.context = []
    expand_context(both, handles, 1)
    ids = [c.id for h in both for c in h.context] + [h.chunk.id for h in both]
    assert len(ids) == len(set(ids))


def test_stitch_removes_chunk_overlap():
    a = "First sentence here. The overlapping sentence is repeated."
    b = "The overlapping sentence is repeated. Next part."
    assert stitch([a, b]) == "First sentence here. The overlapping sentence is repeated. Next part."
    assert stitch(["one", "two"]) == "one\ntwo"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot replace files of an open module; the build reports it")
def test_index_cache_reopens_after_rebuild(tmp_path):
    mods = tmp_path / "modules"
    make_module(mods, "m", {"a.txt": ["old content about wells"]})
    cache = IndexCache()
    h1 = cache.get(mods / "m")
    assert h1 is cache.get(mods / "m")
    shutil.rmtree(mods / "m")
    make_module(mods, "m", {"b.txt": ["new content about springs"]})
    h2 = cache.get(mods / "m")
    assert h2 is not h1
    res = Retriever(_settings(tmp_path)).candidates("springs", [h2], 5)
    assert hit_paths(res.hits) == ["b.txt"]
    cache.clear()


def test_index_cache_lru_capacity(tmp_path):
    for n in "abc":
        make_module(tmp_path / "modules", n, {"x.txt": ["text"]})
    cache = IndexCache(capacity=2)
    for n in "abc":
        cache.get(tmp_path / "modules" / n)
    assert len(cache._items) == 2


def test_query_encoding_is_cached(tmp_path):
    calls = []

    class CountingEncoder(HashingEncoder):
        def encode(self, texts, *, query=False):
            calls.append(list(texts))
            return super().encode(texts, query=query)

    enc = CountingEncoder(128)
    make_module(tmp_path / "modules", "medical", MEDICAL, enc)
    cache = IndexCache()
    r = Retriever(_settings(tmp_path), enc)
    h = [cache.get(tmp_path / "modules" / "medical")]
    calls.clear()
    r.candidates("bleeding", h)
    r.candidates("bleeding", h)
    assert calls == [["bleeding"]]


def test_with_builder_end_to_end(tmp_path):
    builder = pytest.importorskip("kovcheg.builder")
    src = tmp_path / "src"
    src.mkdir()
    (src / "codes.txt").write_text("Pneumonia, unspecified organism is coded J18.9 in ICD-10.\n\nAcute bronchitis is J20.", encoding="utf-8")
    (src / "aid.md").write_text("# Bleeding\n\nApply firm direct pressure on the wound.\n\n# Burns\n\nCool the burn under running water.",
                                encoding="utf-8")
    s = Settings(home=tmp_path)
    s.embedding.model = ENC.id
    builder.build_module(s, "kb", src, encoder=ENC)
    res, _ = _search(tmp_path, ["kb"], "J18.9", ENC)
    assert hit_paths(res.hits)[0] == "codes.txt"
    res, _ = _search(tmp_path, ["kb"], "burn running water", ENC)
    top = res.hits[0].chunk
    assert top.doc_path == "aid.md" and "Burns" in (top.section or "")


def test_stem_and_prefix_terms_handle_inflection():
    from kovcheg.retrieval import fts_query, stem
    assert stem("кровотечу") == stem("кровотеча") == "кровот" and stem("рану") == "рану" and stem("J18") == "J18"
    q = fts_query("як зупинити кровотечу")
    assert '"кровот"*' in q and '"зупин"*' in q and '"як"*' not in q
