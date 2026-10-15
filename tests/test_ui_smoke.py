import json
from pathlib import Path

import pytest
from helpers import make_home

from kovcheg.generation import NO_CITATIONS_WARNING
from kovcheg.types import Chunk, Hit
from kovcheg.ui import render

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def _hit(**kw):
    c = Chunk(5, 1, 3, kw.pop("text", EVIL), module="med<b>", doc_path="a&b.pdf", doc_title=kw.pop("title", "Manual <i>"), page=12,
              section="Bleeding & burns")
    h = Hit(c, 0.5, rerank=2.0, **kw)
    h.context = [Chunk(4, 1, 2, "before <b>ctx</b>"), Chunk(6, 1, 4, "after")]
    return h


def test_source_card_escapes_everything_and_shows_location():
    html = render.source_card(3, _hit(), "uk", show_scores=True, cited=True)
    assert "<script>" not in html and "<img" not in html and "<b>" not in html and "<i>" not in html
    assert "&lt;script&gt;" in html and "a&amp;b.pdf" in html
    assert "[3] Manual &lt;i&gt;, с. 12 — Bleeding &amp; burns" in html
    assert "цитовано" in html and "88%" in html                   # sigmoid(2.0) = 0.88
    assert html.index("before") < html.index("&lt;script") < html.index("after")
    assert "[3] Manual &lt;i&gt;, p. 12" in render.source_card(3, _hit(), "en")


def test_integrity_badges():
    assert "✓" in render.integrity_badge("valid", "ok", "uk") and "kv-valid" in render.integrity_badge("valid", "", "en")
    bad = render.integrity_badge("invalid", 'x" onmouseover="alert(1)', "uk")
    assert "НЕДІЙСНА" in bad and "kv-invalid" in bad and '" onmouseover' not in bad
    assert "kv-unknown" in render.integrity_badge("weird", "", "en")


def test_answer_markdown_is_safe_and_flags_bad_citations():
    md = render.answer_markdown('Do X [1] and Y [7]. <script>bad()</script> ![p](http://x/y.png) [l](http://x)', 3)
    assert "<script>" not in md and "&lt;script&gt;" in md
    assert "![p](" not in md and "](http" not in md
    assert "[1]" in md and "**[7]⚠**" in md


def test_texts_complete_and_disclaimer():
    assert set(render.TEXTS["uk"]) == set(render.TEXTS["en"])
    assert render.t("uk", "disclaimer").startswith("Ковчег може помилятися")
    assert "emergency services" in render.t("en", "disclaimer")
    assert render.t("xx", "title") == "Ковчег"                 # unknown language falls back to Ukrainian
    assert "«m»" in render.t("uk", "invalid_warning", name="m")


def test_css_has_no_hardcoded_dark_backgrounds():
    import re
    for m in re.finditer(r"background:\s*([^;}]+)", render.CSS):
        val = m.group(1).strip()
        assert val.startswith("rgba(") or val == "#d93025", val


def test_status_and_warnings_helpers():
    assert render.status_notice("no_evidence", "uk")[0] == "warning"
    assert render.status_notice("ok", "uk") is None
    main, tech = render.answer_warnings([NO_CITATIONS_WARNING, "answer cites source(s) [9] that do not exist", "module 'x': y"], "en")
    assert main == [render.t("en", "no_citations"), render.t("en", "bad_citations")] and tech == ["module 'x': y"]
    line = render.model_status_line({"encoder": {"state": "disabled"}, "reranker": {"state": "error", "error": "boom"},
                                     "llm": {"state": "loaded", "id": "echo"}}, "en")
    assert "keyword search only" in line and "error: boom" in line and "on (echo)" in line


def test_streamlit_app_runs(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    home = make_home(tmp_path)
    monkeypatch.setenv("KOVCHEG_HOME", str(home))
    monkeypatch.setenv("KOVCHEG_OVERRIDES", json.dumps({"embedding": {"model": ""}, "rerank": {"enabled": False}, "llm": {"model": "echo"}}))
    app = Path(render.__file__).with_name("app.py")
    at = AppTest.from_file(str(app), default_timeout=30).run()
    assert not at.exception
    assert any("Ковчег може помилятися" in w.value for w in at.warning)
    at.chat_input[0].set_value("J18.9").run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    assert "J18.9" in md and "[1]" in md and "codes" in md


def test_streamlit_invalid_module_disabled_and_english(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    pytest.importorskip("kovcheg.security")
    from streamlit.testing.v1 import AppTest
    home = make_home(tmp_path)
    with open(home / "modules" / "water" / "kovcheg.db", "ab") as f:
        f.write(b"x")
    monkeypatch.setenv("KOVCHEG_HOME", str(home))
    monkeypatch.setenv("KOVCHEG_OVERRIDES", json.dumps({"embedding": {"model": ""}, "rerank": {"enabled": False}, "llm": {"model": ""}}))
    at = AppTest.from_file(str(Path(render.__file__).with_name("app.py")), default_timeout=30).run()
    assert not at.exception
    boxes = {c.key: c.value for c in at.checkbox}
    assert boxes == {"mod::medical": True, "mod::water": False}
    assert any("«water»" in e.value for e in at.error)
    at.selectbox(key="lang").set_value("en").run()
    assert any("Kovcheg can be wrong" in w.value for w in at.warning)
    at.chat_input[0].set_value("J18.9").run()
    assert not at.exception
    assert any("Search mode" in i.value for i in at.info)
