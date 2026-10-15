"""Structure-aware chunking: sections → paragraphs → lines → sentences, packed up to `target_chars` (never above
`max_chars`), with `overlap_sentences` sentences repeated at the start of the next chunk of the same section.
Chunks never cross a section (page / heading) boundary, so each keeps its page and section. Oversized sentences are
split at whitespace; text without whitespace (CJK, long tokens) is split at `max_chars`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .config import ChunkingSettings
from .readers import Section

_SENT_SPLIT = re.compile(r"(?<=[.!?…;])\s+(?=\S)|(?<=[。！？；])")
_PARA_SPLIT = re.compile(r"\n\s*\n")
_WORD = re.compile(r"\w", re.UNICODE)


@dataclass
class Piece:
    text: str
    page: int | None
    section: str | None


@dataclass
class _Unit:
    text: str
    sep: str        # joiner placed before this unit when it follows another: " ", "\n" or "\n\n"


def _split_long(s: str, max_chars: int) -> list[str]:
    """Split a sentence longer than max_chars at whitespace (never mid-word); hard split only when no whitespace is in
    reach (CJK text or a single giant token)."""
    out: list[str] = []
    while len(s) > max_chars:
        cut = s.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        out.append(s)
    return [x for x in out if x]


def _units(text: str, max_chars: int) -> list[_Unit]:
    units: list[_Unit] = []
    for pi, para in enumerate(_PARA_SPLIT.split(text.strip())):
        for li, line in enumerate(para.split("\n")):
            line = line.rstrip()
            if not line.strip():
                continue
            for si, sent in enumerate(_SENT_SPLIT.split(line)):
                sent = sent.strip() if si else sent.rstrip()
                if not sent.strip():
                    continue
                for ki, part in enumerate(_split_long(sent, max_chars) if len(sent) > max_chars else [sent]):
                    first = si == 0 and ki == 0
                    sep = ("\n\n" if pi and li == 0 else "\n") if first and (pi or li) else " "
                    units.append(_Unit(part, sep))
    if units:
        units[0].sep = ""
    return units


def _join(units: list[_Unit]) -> str:
    out = units[0].text
    for u in units[1:]:
        out += (u.sep or " ") + u.text
    return out.strip()


def _len(units: list[_Unit]) -> int:
    return sum(len(u.text) + len(u.sep) for u in units)


def chunk_text(text: str, settings: ChunkingSettings) -> list[str]:
    """Chunk one block of text (no page/section bookkeeping)."""
    target = max(1, settings.target_chars)
    max_chars = max(target, settings.max_chars)
    units = _units(text, max_chars)
    chunks: list[tuple[list[_Unit], int]] = []      # (units, number of leading overlap units)
    cur: list[_Unit] = []
    n_ov = 0
    for u in units:
        if len(cur) > n_ov and _len(cur) + len(u.sep or " ") + len(u.text) > target:
            chunks.append((cur, n_ov))
            ov = cur[-settings.overlap_sentences:] if settings.overlap_sentences > 0 else []
            while ov and _len(ov) + len(u.text) + 1 > target:      # overlap must leave room for new text
                ov = ov[1:]
            cur, n_ov = list(ov), len(ov)
        cur.append(u)
    if len(cur) > n_ov:
        chunks.append((cur, n_ov))
    texts = [_join(c) for c, _ in chunks]
    # a tiny tail is merged into the previous chunk when that still fits under max_chars
    if len(texts) > 1 and len(texts[-1]) < settings.min_chars:
        last, k = chunks[-1]
        merged = texts[-2] + (last[k].sep or " ") + _join(last[k:])
        if len(merged) <= max_chars:
            texts[-2:] = [merged]
    return [t for t in texts if _WORD.search(t)]


def chunk_sections(sections: Iterable[Section], settings: ChunkingSettings) -> list[Piece]:
    """Chunk a parsed document; every piece keeps the page and heading of the section it came from."""
    out: list[Piece] = []
    for s in sections:
        for t in chunk_text(s.text, settings):
            out.append(Piece(t, s.page, s.heading))
    return out


def embedding_text(piece_text: str, title: str | None, section: str | None) -> str:
    """Text given to the encoder: 'title — section: text'. The stored chunk text stays raw (no header)."""
    head = " — ".join(x for x in ((title or "").strip(), (section or "").strip()) if x)
    if section and title and section.strip() == title.strip():
        head = title.strip()
    return f"{head}: {piece_text}" if head else piece_text
