"""Cross-encoder reranking of retrieval candidates.

`BGEReranker` wraps BAAI/bge-reranker-v2-m3 (Apache-2.0) through FlagEmbedding, imported lazily. Scores are raw
logits (stored in `Hit.rerank`); `sigmoid` turns them into 0..1 for display. `settings.rerank.min_score` is a
logit threshold used by the engine's no-evidence gate.
"""
from __future__ import annotations

import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .types import Hit


class Reranker(Protocol):
    id: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...   # one logit per passage


def sigmoid(x: float | None) -> float | None:
    if x is None:
        return None
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(x)))))


class BGEReranker:
    """BAAI/bge-reranker-v2-m3 from a local folder; never downloads."""

    id = "bge-reranker-v2-m3"

    def __init__(self, model_dir: str | Path, *, device: str = "cpu", fp16: bool = False, batch_size: int = 8, max_length: int = 512):
        model_dir = Path(model_dir)
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(f"the reranker is not installed in {model_dir}; reranking is off (see docs/en/models.md)")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as e:
            raise ImportError('the reranker needs the "embed" extra: pip install "kovcheg[embed]"') from e
        self._m = FlagReranker(str(model_dir), use_fp16=fp16, device=device)
        self.batch_size, self.max_length = batch_size, max_length

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        out = self._m.compute_score([[query, p] for p in passages], batch_size=self.batch_size, max_length=self.max_length,
                                    normalize=False)
        if isinstance(out, (int, float)):
            out = [out]
        return [float(x) for x in out]


def load_reranker(settings) -> Reranker | None:
    """Reranker from `settings.rerank`, or None when disabled. Raises if configured but unavailable."""
    r = settings.rerank
    if not r.enabled or not r.model:
        return None
    return BGEReranker(settings.path(r.model), device=settings.embedding.device, fp16=settings.embedding.fp16,
                       batch_size=r.batch_size, max_length=r.max_length)


def passage(hit: Hit) -> str:
    """Text scored by the cross-encoder: the hit's own chunk (never its context) with its location as a header."""
    c = hit.chunk
    head = c.doc_title or c.doc_path
    if c.section:
        head += f" — {c.section}"
    return f"{head}\n{c.text}" if head else c.text


def rerank(reranker: Reranker, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
    """Score the first `top_n` hits, order them by logit; hits beyond top_n follow unscored in their old order."""
    head, tail = hits[:max(top_n, 0)], hits[max(top_n, 0):]
    if not head:
        return hits
    scores = reranker.score(query, [passage(h) for h in head])
    if len(scores) != len(head):
        raise ValueError(f"reranker returned {len(scores)} scores for {len(head)} passages")
    for h, s in zip(head, scores, strict=True):
        h.rerank = float(s)
        h.score = float(s)
    head.sort(key=lambda h: -h.rerank)
    return head + tail


def best_rerank(hits: Sequence[Hit]) -> float | None:
    vals = [h.rerank for h in hits if h.rerank is not None]
    return max(vals) if vals else None
