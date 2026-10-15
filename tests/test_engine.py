import shutil
import sys
import threading

import pytest
from helpers import FakeReranker, collect, hit_paths, make_home, make_module, overrides

from kovcheg.embedding import HashingEncoder
from kovcheg.engine import Kovcheg, _integrity_of
from kovcheg.generation import NO_CITATIONS_WARNING, EchoGenerator
from kovcheg.types import Answer

ENC = HashingEncoder(128)


def _engine(tmp_path, encoder=None, generator=None, reranker=None, **ov):
    home = make_home(tmp_path, encoder=encoder)
    o = overrides(encoder)
    for k, v in ov.items():
        sec, key = k.split("__")
        o.setdefault(sec, {})[key] = v
    return Kovcheg.from_home(home, o, encoder=encoder, reranker=reranker, generator=generator)


@pytest.mark.parametrize("encoder", [None, ENC], ids=["bm25-only", "hybrid"])
def test_ask_grounded_answer_with_citations(tmp_path, encoder):
    gen = EchoGenerator()
    k = _engine(tmp_path, encoder, gen)
    ans = k.ask("What is the ICD-10 code J18.9?")
    assert ans.status == "ok", ans.warnings
    assert ans.hits[0].chunk.doc_path == "codes.txt"
    assert ans.text.endswith("[1]") and "J18.9" in ans.text
    assert [(c.number, c.valid) for c in ans.citations] == [(1, True)] and ans.citations[0].hit is ans.hits[0]
    assert {"retrieve", "generate", "total"} <= set(ans.timings)
    # the prompt numbers sources exactly as Answer.hits
    user = gen.calls[0][1]["content"]
    for i, h in enumerate(ans.hits, 1):
        assert f"[{i}] {h.chunk.citation}" in user


def test_no_evidence_skips_llm(tmp_path):
    gen = EchoGenerator()
    k = _engine(tmp_path, None, gen)
    ans = k.ask("zzzz qqqq")
    assert ans.status == "no_evidence" and ans.hits == [] and gen.calls == []
    assert k.ask("   ").status == "no_evidence"


def test_rerank_orders_and_gate_blocks_llm(tmp_path):
    gen, rr = EchoGenerator(), FakeReranker()
    k = _engine(tmp_path, None, gen, rr, rerank__min_score=-6.0)
    ans = k.ask("tourniquet limb wound")
    assert ans.status == "ok" and rr.calls
    assert ans.hits[0].rerank is not None and ans.hits[0].rerank == max(h.rerank for h in ans.hits if h.rerank is not None)
    assert "tourniquet" in ans.hits[0].chunk.text
    # reranker passages are the hits' own chunks, never their context
    assert all("\n" in p for p in rr.calls[0][1])
    gen2 = EchoGenerator()
    k2 = _engine(tmp_path / "b", None, gen2, FakeReranker(), rerank__min_score=7.9)
    ans2 = k2.ask("burns ice and other words")
    assert ans2.status == "no_evidence" and gen2.calls == [] and ans2.hits
    assert any("rerank.min_score" in w for w in ans2.warnings)


def test_reranker_failure_degrades(tmp_path):
    k = _engine(tmp_path, None, EchoGenerator(), FakeReranker(fail=RuntimeError("boom")))
    ans = k.ask("J18.9")
    assert ans.status == "ok" and any("reranking failed" in w for w in ans.warnings)


def test_search_only_and_llm_unavailable(tmp_path):
    k = _engine(tmp_path, None, None)
    ans = k.ask("J18.9")
    assert ans.status == "search_only" and ans.text == "" and ans.hits
    k2 = _engine(tmp_path / "b", None, llm__model="models/missing.gguf")
    k2._llm.state = "not_loaded"           # let the real loader try (and fail: file missing)
    ans = k2.ask("J18.9")
    assert ans.status == "llm_unavailable" and ans.hits
    assert any("LLM unavailable" in w and "missing.gguf" in w for w in ans.warnings)
    k3 = _engine(tmp_path / "c", None, EchoGenerator())
    assert k3.ask("J18.9", search_only=True).status == "search_only"


def test_missing_models_reported_not_fatal(tmp_path):
    home = make_home(tmp_path)
    k = Kovcheg.from_home(home, {"embedding": {"model": "models/bge-m3"}, "rerank": {"model": "models/rr"}, "llm": {"model": ""}})
    st = k.status(verify=False)
    assert st["encoder"]["state"] == "not_loaded" and "not found" in st["encoder"]["error"]
    ans = k.search("J18.9")
    assert ans.status == "ok" and hit_paths(ans.hits)[0] == "codes.txt"
    st = k.status(verify=False)
    assert st["encoder"]["state"] == "error" and st["reranker"]["state"] == "error" and st["llm"]["state"] == "disabled"
    assert any("embedding model unavailable" in w for w in ans.warnings)


def test_invalid_and_missing_citations_flagged(tmp_path):
    k = _engine(tmp_path, None, EchoGenerator("Apply pressure [1] and see [42]."))
    ans = k.ask("bleeding")
    assert [(c.number, c.valid) for c in ans.citations] == [(1, True), (42, False)]
    assert any("[42]" in w for w in ans.warnings)
    k2 = _engine(tmp_path / "b", None, EchoGenerator("Apply pressure."))
    assert NO_CITATIONS_WARNING in k2.ask("bleeding").warnings


def test_generation_error_keeps_sources(tmp_path):
    k = _engine(tmp_path, None, EchoGenerator(fail=RuntimeError("oom")))
    ans = k.ask("bleeding")
    assert ans.status == "error" and ans.hits and any("oom" in w for w in ans.warnings)


def test_streaming(tmp_path):
    k = _engine(tmp_path, None, EchoGenerator("One two [1]."))
    items = list(k.ask_stream("bleeding"))
    assert all(isinstance(x, str) for x in items[:-1]) and isinstance(items[-1], Answer)
    text, final = collect(iter(items))
    assert text == "One two [1]." and final.text == text
    got = []
    k.ask("bleeding", on_token=got.append)
    assert "".join(got) == "One two [1]."


def test_context_expansion_in_answers(tmp_path):
    k = _engine(tmp_path, None, EchoGenerator("x [1]"), retrieval__context_neighbors=1, retrieval__top_k=1)
    ans = k.ask("tourniquet")
    assert len(ans.hits) == 1 and ans.hits[0].context
    assert all(c.doc_id == ans.hits[0].chunk.doc_id for c in ans.hits[0].context)


def test_module_selection_and_integrity(tmp_path):
    k = _engine(tmp_path, None, EchoGenerator())
    mods = {m.name: m for m in k.modules()}
    assert set(mods) == {"medical", "water"} and mods["medical"].integrity == "unsigned" and mods["medical"].documents == 3
    # tamper with a module: integrity INVALID -> excluded by default, warning when selected explicitly
    db = tmp_path / "modules" / "water" / "kovcheg.db"
    with open(db, "ab") as f:
        f.write(b"\0" * 10)
    k.reload()
    mods = {m.name: m for m in k.modules()}
    assert mods["water"].integrity == "invalid" and not mods["water"].enabled_by_default
    assert all(h.chunk.module != "water" for h in k.search("boil water").hits)
    ans = k.search("boil water", ["water"])
    assert any("FAILED integrity" in w for w in ans.warnings)


def test_legacy_and_temp_folders(tmp_path):
    k = _engine(tmp_path)
    (tmp_path / "modules" / "old").mkdir()
    (tmp_path / "modules" / "old" / "search_bge.db").write_bytes(b"")
    (tmp_path / "modules" / ".medical.building").mkdir()
    (tmp_path / "modules" / ".x.old").mkdir()
    mods = {m.name: m for m in k.modules()}
    assert set(mods) == {"medical", "water", "old"}
    assert "migrate" in mods["old"].error and not mods["old"].enabled_by_default
    ans = k.search("J18.9", ["old", "medical", "nope"])
    assert ans.hits and any("'nope' not found" in w for w in ans.warnings) and any("'old' cannot be opened" in w for w in ans.warnings)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot replace files of an open module; the build reports it")
def test_rebuilt_module_is_reloaded(tmp_path):
    k = _engine(tmp_path)
    assert k.search("springs", ["water"]).status == "no_evidence"
    shutil.rmtree(tmp_path / "modules" / "water")
    make_module(tmp_path / "modules", "water", {"s.txt": ["Mountain springs are usually safe after boiling."]})
    assert hit_paths(k.search("springs", ["water"]).hits) == ["s.txt"]


def test_concurrent_asks(tmp_path):
    k = _engine(tmp_path, ENC, EchoGenerator())
    results, errors = [], []

    def run(q):
        try:
            results.append(k.ask(q))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=run, args=(q,)) for q in ["J18.9", "bleeding", "burn", "boil water"] * 2]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors and len(results) == 8 and all(r.status == "ok" for r in results)


def test_integrity_adapter():
    from types import SimpleNamespace as N
    assert _integrity_of(N(status="valid", message="ok", key_id="ab"))[::2] == ("valid", "ab")
    assert _integrity_of(N(status="missing_files", message="m"))[0] == "invalid"
    assert _integrity_of(N(status="untrusted", message="m"))[0] == "untrusted"
    assert _integrity_of(N(status="error", message="m"))[0] == "unknown"
    assert _integrity_of((False, "bad"))[:2] == ("invalid", "bad")
    assert _integrity_of(None)[0] == "unsigned"


def test_with_builder_and_signing(tmp_path):
    builder = pytest.importorskip("kovcheg.builder")
    pytest.importorskip("cryptography")
    from kovcheg.config import load_settings
    from kovcheg.security import keygen, sign_module
    src = tmp_path / "sources" / "kb"
    src.mkdir(parents=True)
    (src / "a.md").write_text("# Water\n\nBoil water for one minute before drinking.", encoding="utf-8")
    s = load_settings(tmp_path, overrides(ENC))
    builder.build_module(s, "kb", encoder=ENC)
    keygen(s.keys_dir)
    sign_module(s.modules_dir / "kb", s.keys_dir)
    k = Kovcheg(s, encoder=ENC, reranker=None, generator=EchoGenerator())
    assert k.modules()[0].integrity == "valid"
    ans = k.ask("how long to boil water")
    assert ans.status == "ok" and ans.hits[0].chunk.doc_path == "a.md" and ans.hits[0].chunk.section


def test_keyword_only_gate_rejects_unrelated_question(tmp_path):
    """Without a reranker or dense retrieval, a question that shares only function words with the library is 'no evidence'."""
    k = _engine(tmp_path)
    ans = k.search("how to fix a car engine")
    assert ans.status == "no_evidence" and any("content word" in w for w in ans.warnings)


def test_keyword_gate_tolerates_inflection():
    from kovcheg.retrieval import matches_any_term, query_terms
    from kovcheg.types import Chunk
    c = Chunk(id=1, doc_id=1, idx=0, text="Сильна кровотеча з кінцівки: притисніть рану.")
    assert matches_any_term(query_terms("як зупинити кровотечу"), c)
    assert not matches_any_term(query_terms("how to fix a car engine"), c)
