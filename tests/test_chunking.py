from kovcheg.chunking import chunk_sections, chunk_text, embedding_text
from kovcheg.config import ChunkingSettings
from kovcheg.readers import Section, parse_markdown

C = ChunkingSettings(target_chars=120, max_chars=200, overlap_sentences=1, min_chars=20)


def test_empty_and_whitespace():
    assert chunk_text("", C) == []
    assert chunk_text("   \n\n  \t", C) == []
    assert chunk_text("... --- !!!", C) == []


def test_short_text_kept_even_below_min_chars():
    assert chunk_text("J18.9 pneumonia", C) == ["J18.9 pneumonia"]


def test_packing_and_overlap():
    sents = [f"Sentence number {i} is here." for i in range(20)]
    chunks = chunk_text(" ".join(sents), C)
    assert len(chunks) > 1
    assert all(len(c) <= C.max_chars for c in chunks)
    for a, b in zip(chunks, chunks[1:], strict=False):
        last = a.split(". ")[-1].rstrip(".")
        assert b.startswith(last)                       # one-sentence overlap
    joined = " ".join(chunks)
    assert all(s in joined for s in sents)


def test_huge_sentence_split_at_words():
    words = [f"w{i:04d}" for i in range(300)]
    chunks = chunk_text(" ".join(words), C)
    assert all(len(c) <= C.max_chars for c in chunks)
    got = [w for c in chunks for w in c.split()]
    assert set(got) == set(words)                        # never mid-word
    assert all(len(w) == 5 for w in got)


def test_cjk_and_cyrillic():
    cjk = "这是一个句子。" * 80
    chunks = chunk_text(cjk, C)
    assert len(chunks) > 1 and all(len(c) <= C.max_chars for c in chunks)
    assert "".join(chunks).count("这是一个句子。") >= 80
    uk = "Зупиніть кровотечу тиском. Накладіть джгут вище рани. Запишіть час накладання джгута. " * 5
    chunks = chunk_text(uk, C)
    assert chunks and all(len(c) <= C.max_chars for c in chunks)
    assert all(c[0].isupper() for c in chunks)          # starts at a sentence boundary


def test_no_cjk_giant_token_exceeds_max():
    chunks = chunk_text("x" * 1000, C)
    assert all(len(c) <= C.max_chars for c in chunks) and "".join(chunks) == "x" * 1000


def test_markdown_headings_become_sections():
    md = "# Guide\n\nIntro text.\n\n## Bleeding\n\nApply pressure.\n\nBurns\n-----\n\nCool with water.\n\n```\n# not a heading\n```\n"
    doc = parse_markdown(md, "file")
    assert doc.title == "Guide"
    pieces = chunk_sections(doc.sections, C)
    by_sec = {p.section: p.text for p in pieces}
    assert by_sec["Guide"] == "Intro text."
    assert by_sec["Bleeding"] == "Apply pressure."
    assert "Cool with water." in by_sec["Burns"] and "# not a heading" in by_sec["Burns"]


def test_page_boundaries_respected():
    secs = [Section("Page one text. " * 3, page=1), Section("Page two text. " * 3, page=2)]
    pieces = chunk_sections(secs, C)
    assert [p.page for p in pieces] == [1, 2]
    assert "two" not in pieces[0].text and "one" not in pieces[1].text


def test_tiny_tail_merged():
    c = ChunkingSettings(target_chars=50, max_chars=200, overlap_sentences=0, min_chars=20)
    chunks = chunk_text("A first fairly long sentence goes here. And another long one is here. Ok.", c)
    assert chunks[-1].endswith("Ok.") and len(chunks[-1]) > 3


def test_embedding_text_header():
    assert embedding_text("body", "Manual", "Burns") == "Manual — Burns: body"
    assert embedding_text("body", "Manual", None) == "Manual: body"
    assert embedding_text("body", "", None) == "body"
    assert embedding_text("body", "Same", "Same") == "Same: body"
