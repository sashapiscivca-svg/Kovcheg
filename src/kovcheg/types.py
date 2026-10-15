"""Shared data types of Kovcheg. Plain dataclasses; no heavy imports."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage of a document, as stored in a module index."""
    id: int                     # chunk id, unique within its module
    doc_id: int
    idx: int                    # position of the chunk within its document (0-based)
    text: str
    module: str = ""            # module (knowledge base) name
    doc_path: str = ""          # path of the source file relative to the module's source folder (posix), or ZIM path
    doc_title: str = ""
    page: int | None = None     # 1-based page number for paginated sources (PDF), else None
    section: str | None = None  # nearest heading / section title, if known

    @property
    def citation(self) -> str:
        """Human-readable location, e.g. 'manual.pdf, p. 12 — Bleeding control'."""
        s = self.doc_title or self.doc_path
        if self.page is not None:
            s += f", p. {self.page}"
        if self.section:
            s += f" — {self.section}"
        return s


@dataclass
class Hit:
    """A retrieved chunk with the scores that produced its rank."""
    chunk: Chunk
    score: float                          # final score used for ordering (fused or reranked)
    dense: float | None = None            # cosine similarity
    sparse: float | None = None           # lexical (BGE-M3 sparse) score, normalised to [0, 1]
    bm25: float | None = None             # SQLite FTS5 bm25 score (higher is better)
    rerank: float | None = None           # cross-encoder logit
    context: list[Chunk] = field(default_factory=list)   # neighbouring chunks merged for the LLM (context expansion)

    @property
    def key(self) -> tuple[str, int]:
        return (self.chunk.module, self.chunk.id)


@dataclass
class Citation:
    number: int        # [n] as written in the answer
    valid: bool        # n refers to a provided source
    hit: Hit | None


@dataclass
class Answer:
    question: str
    text: str                                        # answer text ('' if generation disabled or unavailable)
    hits: list[Hit]                                  # numbered sources: hits[i] is source [i + 1]
    citations: list[Citation] = field(default_factory=list)
    status: str = "ok"                               # ok | no_evidence | search_only | llm_unavailable | error
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)   # seconds per stage
