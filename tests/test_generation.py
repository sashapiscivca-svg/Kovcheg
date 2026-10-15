import sys
import types

import pytest

from kovcheg.config import LLMSettings
from kovcheg.generation import (
    NO_CITATIONS_WARNING,
    SYSTEM_PROMPT,
    EchoGenerator,
    LlamaCppGenerator,
    build_prompt,
    check_citations,
    cited_numbers,
    estimate_tokens,
    load_generator,
)
from kovcheg.types import Chunk, Hit


def _hits(n=3, size=200, context=False):
    hits = []
    for i in range(n):
        c = Chunk(i + 1, i + 1, 1, f"Source {i + 1} text. " + "word " * size, module="m", doc_path=f"d{i}.pdf", doc_title=f"Doc {i}",
                  page=i + 2, section=f"Sec {i}")
        h = Hit(c, 1.0 - i / 10)
        if context:
            h.context = [Chunk(100 + i, i + 1, 0, f"Before {i}. " + "ctx " * size, module="m"), Chunk(200 + i, i + 1, 2, f"After {i}.")]
        hits.append(h)
    return hits


def test_prompt_numbers_sources_with_citations():
    hits = _hits(3, 10, context=True)
    p = build_prompt("Як зупинити кровотечу?", hits, context_window=4096, max_tokens=500)
    sys_msg, user = p.messages
    assert sys_msg == {"role": "system", "content": SYSTEM_PROMPT}
    assert "same language as the question" in SYSTEM_PROMPT and "[n]" in SYSTEM_PROMPT
    assert p.n_sources == 3 and not p.trimmed
    for i in range(3):
        assert f"[{i + 1}] Doc {i}, p. {i + 2} — Sec {i} (m)\nBefore {i}." in user["content"]
    assert user["content"].index("[1]") < user["content"].index("[2]") < user["content"].index("[3]")
    assert user["content"].rstrip().endswith("Answer with citations [n]:")
    assert "Question: Як зупинити кровотечу?" in user["content"]


def test_budget_drops_context_then_lowest_ranked_sources():
    hits = _hits(4, 150, context=True)
    full = build_prompt("q", hits, context_window=100_000, max_tokens=100)
    assert full.n_sources == 4
    p = build_prompt("q", hits, context_window=1100, max_tokens=300)
    assert 1 <= p.n_sources < 4
    assert p.tokens <= 1100 - 300 + 5
    assert any("sources fit" in x for x in p.trimmed)
    assert "[1] Doc 0" in p.messages[1]["content"]
    assert f"[{p.n_sources + 1}]" not in p.messages[1]["content"]


def test_single_huge_source_is_truncated():
    hits = _hits(1, 5000)
    p = build_prompt("q", hits, context_window=1024, max_tokens=200)
    assert p.n_sources == 1 and any("truncated" in x for x in p.trimmed)
    assert estimate_tokens(p.messages[1]["content"]) < 1024


def test_tokenizer_from_generator_is_used():
    seen = []

    def count(text):
        seen.append(text)
        return len(text.split())

    build_prompt("q", _hits(2, 5), context_window=4096, max_tokens=100, count=count)
    assert seen


def test_cited_numbers_forms():
    assert cited_numbers("A [1]. B [2-3], C [1, 4][5]; D [2–2] E [ 7 ] [x]") == [1, 2, 3, 4, 5]
    assert cited_numbers("no citations") == []


def test_check_citations_valid_invalid_and_missing():
    hits = _hits(2, 1)
    cites, warns = check_citations("Fact [1]. Other [3].", hits, 2)
    assert [(c.number, c.valid) for c in cites] == [(1, True), (3, False)]
    assert cites[0].hit is hits[0] and cites[1].hit is None
    assert any("[3]" in w for w in warns)
    # a source that exists in the list but was not given to the model (trimmed) is invalid
    cites, warns = check_citations("Fact [2].", hits, 1)
    assert not cites[0].valid and warns
    cites, warns = check_citations("An answer without any citation.", hits, 2)
    assert cites == [] and warns == [NO_CITATIONS_WARNING]
    assert check_citations("", hits, 2) == ([], [])


def test_echo_generator_quotes_first_source():
    p = build_prompt("q", _hits(2, 3), context_window=4096, max_tokens=100)
    g = EchoGenerator()
    out = "".join(g.stream(p.messages))
    assert out == "Source 1 text. [1]" and g.calls == [p.messages]
    assert "".join(EchoGenerator("Fixed [2].").stream(p.messages)) == "Fixed [2]."


def test_estimate_tokens_is_conservative_for_cyrillic():
    assert estimate_tokens("a" * 400) == 101
    assert estimate_tokens("б" * 400) > estimate_tokens("a" * 400)


def test_load_generator_modes(tmp_path):
    from kovcheg.config import Settings
    s = Settings(home=tmp_path)
    assert load_generator(s) is None
    s.llm.model = "echo"
    assert isinstance(load_generator(s), EchoGenerator)
    s.llm.model = "models/none.gguf"
    with pytest.raises(FileNotFoundError):
        load_generator(s)


class _FakeLlama:
    instances: list = []

    def __init__(self, model_path, **kw):
        self.kw = kw
        self.calls = []
        _FakeLlama.instances.append(self)

    def tokenize(self, b, add_bos=False, special=False):
        return b.split()

    def create_chat_completion(self, messages, **kw):
        self.calls.append((messages, kw))
        if any(m["role"] == "system" for m in messages):
            raise ValueError("System role not supported")

        def gen():
            yield {"choices": [{"delta": {"role": "assistant"}}]}
            for t in ["Pressure ", "stops ", "bleeding [1]."]:
                yield {"choices": [{"delta": {"content": t}}]}
        return gen()


def test_llamacpp_generator_with_fake_backend(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=_FakeLlama))
    f = tmp_path / "m.gguf"
    f.write_bytes(b"GGUF")
    g = LlamaCppGenerator(f, LLMSettings(model=str(f), threads=2, chat_format=""))
    llm = _FakeLlama.instances[-1]
    assert llm.kw["n_ctx"] == 4096 and llm.kw["n_threads"] == 2 and llm.kw["chat_format"] is None
    assert g.count_tokens("a b c") == 3
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Q"}]
    assert "".join(g.stream(msgs)) == "Pressure stops bleeding [1]."
    # retried without a system role: system text merged into the first user message
    assert llm.calls[-1][0] == [{"role": "user", "content": "SYS\n\nQ"}]
    assert llm.calls[-1][1]["stream"] is True and llm.calls[-1][1]["max_tokens"] == 600
    assert "".join(g.stream(msgs)) == "Pressure stops bleeding [1]."     # remembered: no second failure
    assert len(llm.calls) == 3


def test_llamacpp_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        LlamaCppGenerator(tmp_path / "nope.gguf", LLMSettings())
