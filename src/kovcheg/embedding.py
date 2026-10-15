"""Text encoders. Every encoder returns L2-normalised dense vectors and, optionally, sparse lexical weights.

`BGEM3Encoder` wraps BAAI/bge-m3 (MIT) through FlagEmbedding, imported lazily so that a search-only (BM25) deployment
never needs PyTorch. `HashingEncoder` is a deterministic, model-free encoder used by the tests and for smoke checks;
it has no semantic power and must not be used for real modules.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Encoded:
    dense: np.ndarray                    # (n, dim) float32, rows L2-normalised
    sparse: list[dict[int, float]]       # per text: token id -> weight (empty dicts if unsupported)


class Encoder(Protocol):
    id: str                              # stable identifier stored in module manifests, e.g. "bge-m3"
    dim: int
    has_sparse: bool

    def encode(self, texts: Sequence[str], *, query: bool = False) -> Encoded: ...


def _normalise(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(n, 1e-12)


class BGEM3Encoder:
    """BAAI/bge-m3 dense (1024-d) + sparse lexical weights. Loads only from a local folder; never downloads."""

    id = "bge-m3"
    dim = 1024
    has_sparse = True

    def __init__(self, model_dir: str | Path, *, device: str = "cpu", fp16: bool = False, batch_size: int = 16,
                 max_length: int = 1024, query_max_length: int = 256):
        model_dir = Path(model_dir)
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(f"BGE-M3 is not installed in {model_dir}; semantic search is off (see docs/en/models.md)")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as e:
            raise ImportError('BGE-M3 needs the "embed" extra: pip install "kovcheg[embed]"') from e
        self._m = BGEM3FlagModel(str(model_dir), use_fp16=fp16, device=device)
        self.batch_size, self.max_length, self.query_max_length = batch_size, max_length, query_max_length

    def encode(self, texts: Sequence[str], *, query: bool = False) -> Encoded:
        if not texts:
            return Encoded(np.zeros((0, self.dim), np.float32), [])
        out = self._m.encode(list(texts), batch_size=1 if query else self.batch_size,
                             max_length=self.query_max_length if query else self.max_length,
                             return_dense=True, return_sparse=True, return_colbert_vecs=False)
        sparse = [{int(k): float(v) for k, v in w.items()} for w in out["lexical_weights"]]
        return Encoded(_normalise(out["dense_vecs"]), sparse)


class HashingEncoder:
    """Deterministic bag-of-words hashing encoder (tests, smoke checks). No semantics beyond shared words."""

    has_sparse = True

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.id = f"hashing-{dim}"

    @staticmethod
    def _tok(word: str) -> int:
        return int.from_bytes(hashlib.blake2b(word.lower().encode(), digest_size=4).digest(), "little") & 0x7FFFFFFF

    def encode(self, texts: Sequence[str], *, query: bool = False) -> Encoded:
        dense = np.zeros((len(texts), self.dim), np.float32)
        sparse: list[dict[int, float]] = []
        for i, t in enumerate(texts):
            counts: dict[int, float] = {}
            for w in _WORD.findall(t):
                tok = self._tok(w)
                counts[tok] = counts.get(tok, 0.0) + 1.0
                dense[i, tok % self.dim] += 1.0
            total = sum(counts.values()) or 1.0
            sparse.append({k: v / total for k, v in counts.items()})
        dense[np.all(dense == 0, axis=1), 0] = 1.0
        return Encoded(_normalise(dense), sparse)


def load_encoder(settings) -> Encoder | None:
    """Encoder configured in `settings.embedding`, or None when disabled. Raises if configured but unavailable."""
    e = settings.embedding
    if not e.model:
        return None
    if e.model.startswith("hashing"):
        return HashingEncoder(int(e.model.split("-")[1]) if "-" in e.model else 256)
    return BGEM3Encoder(settings.path(e.model), device=e.device, fp16=e.fp16, batch_size=e.batch_size,
                        max_length=e.max_length, query_max_length=e.query_max_length)
