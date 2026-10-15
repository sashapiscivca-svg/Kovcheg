"""Settings: one TOML file (`kovcheg.toml`) in the Kovcheg home directory, every key optional.

The home directory holds everything a deployment needs, so it can live on a USB stick:

    <home>/kovcheg.toml   settings (optional)
    <home>/models/        embedding, reranker and LLM files (downloaded separately)
    <home>/modules/       indexed knowledge bases ("modules"), one folder each
    <home>/sources/       raw documents to index, one folder per module (legacy name: modules-raw/)
    <home>/keys/          Ed25519 signing key pair; keys/trusted/*.pem are additional trusted public keys

Home resolution order: explicit argument, $KOVCHEG_HOME (legacy: $KOVCHEG_ROOT), the current directory.
A legacy `config.json` (pre-1.0 layout) is read when no `kovcheg.toml` exists.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


@dataclass
class EmbeddingSettings:
    model: str = "models/bge-m3"                 # folder of BAAI/bge-m3 (MIT); "" disables dense+sparse retrieval
    device: str = "cpu"
    fp16: bool = False                           # fp16 only helps on GPU
    batch_size: int = 16                         # indexing batch
    max_length: int = 1024                       # tokens per passage when indexing
    query_max_length: int = 256


@dataclass
class RerankSettings:
    model: str = "models/bge-reranker-v2-m3"     # folder of BAAI/bge-reranker-v2-m3 (Apache-2.0); "" disables reranking
    enabled: bool = True
    top_n: int = 20                              # candidates scored by the cross-encoder (cost is linear in this)
    max_length: int = 512
    batch_size: int = 8
    min_score: float = -6.0                      # logit below which the best hit counts as "no evidence"


@dataclass
class LLMSettings:
    model: str = ""                              # path to a .gguf file; "" = search-only mode
    context_window: int = 4096
    max_tokens: int = 600
    temperature: float = 0.1
    top_p: float = 0.9
    repeat_penalty: float = 1.1
    threads: int = 0                             # 0 = physical cores (llama.cpp default)
    gpu_layers: int = 0
    chat_format: str = ""                        # "" = use the template stored in the GGUF file


@dataclass
class RetrievalSettings:
    top_k: int = 8                               # sources shown and given to the LLM
    candidates: int = 50                         # per-retriever candidates before fusion
    rrf_k: int = 60
    weights: dict[str, float] = field(default_factory=lambda: {"dense": 1.0, "sparse": 0.6, "bm25": 0.8})
    max_per_document: int = 3                    # diversity: at most this many hits from one document
    context_neighbors: int = 1                   # chunks before/after a hit merged into its LLM context
    dedup_threshold: float = 0.95                # cosine above which two hits count as duplicates


@dataclass
class ChunkingSettings:
    target_chars: int = 1000
    max_chars: int = 1600
    overlap_sentences: int = 1
    min_chars: int = 40


@dataclass
class UISettings:
    host: str = "127.0.0.1"                      # set "0.0.0.0" to serve phones/laptops on the local network
    port: int = 8501
    language: str = "uk"                         # interface language: uk | en


@dataclass
class Settings:
    home: Path = Path(".")
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = field(default_factory=RerankSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    chunking: ChunkingSettings = field(default_factory=ChunkingSettings)
    ui: UISettings = field(default_factory=UISettings)

    # ---- paths -------------------------------------------------------------------------------
    def path(self, p: str | Path) -> Path:
        """Resolve a path from the settings relative to the home directory."""
        p = Path(p).expanduser()
        return p if p.is_absolute() else self.home / p

    @property
    def modules_dir(self) -> Path:
        return self.home / "modules"

    @property
    def sources_dir(self) -> Path:
        legacy = self.home / "modules-raw"
        new = self.home / "sources"
        return legacy if legacy.is_dir() and not new.exists() else new

    @property
    def keys_dir(self) -> Path:
        return self.home / "keys"

    @property
    def models_dir(self) -> Path:
        return self.home / "models"


def resolve_home(home: str | Path | None = None) -> Path:
    h = home or os.environ.get("KOVCHEG_HOME") or os.environ.get("KOVCHEG_ROOT") or "."
    return Path(h).expanduser().resolve()


def _apply(obj: Any, data: dict, where: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for k, v in data.items():
        if k not in known:
            raise ValueError(f"unknown setting {where}{k}")
        cur = getattr(obj, k)
        if is_dataclass(cur):
            if not isinstance(v, dict):
                raise ValueError(f"setting {where}{k} must be a table")
            _apply(cur, v, f"{where}{k}.")
        elif isinstance(cur, bool):
            if not isinstance(v, bool):
                raise ValueError(f"setting {where}{k} must be true or false")
            setattr(obj, k, v)
        elif isinstance(cur, (int, float, str)):
            setattr(obj, k, type(cur)(v))
        else:
            setattr(obj, k, v)


def _from_legacy(cfg: dict) -> dict:
    """Map the pre-1.0 config.json layout onto the TOML layout (unknown legacy keys are ignored)."""
    out: dict = {}
    llm = cfg.get("llm_settings", {})
    if llm:
        out["llm"] = {k2: llm[k1] for k1, k2 in (("model_path", "model"), ("context_window", "context_window"), ("temperature", "temperature"),
                                                 ("max_tokens", "max_tokens"), ("top_p", "top_p"), ("repeat_penalty", "repeat_penalty"),
                                                 ("n_threads", "threads"), ("n_gpu_layers", "gpu_layers")) if k1 in llm}
    emb = cfg.get("embedding_settings", {})
    if "model_path" in emb:
        out["embedding"] = {"model": emb["model_path"]}
    if "reranker_path" in emb:
        out["rerank"] = {"model": emb["reranker_path"]}
    rag = cfg.get("rag_settings", {})
    r = {k2: rag[k1] for k1, k2 in (("top_k_results", "top_k"), ("initial_fetch", "candidates"), ("rrf_k", "rrf_k")) if k1 in rag}
    if rag.get("context_expansion") is False:
        r["context_neighbors"] = 0
    if r:
        out["retrieval"] = r
    return out


def load_settings(home: str | Path | None = None, overrides: dict | None = None) -> Settings:
    """Settings of a Kovcheg home: defaults < kovcheg.toml (or legacy config.json) < overrides."""
    root = resolve_home(home)
    s = Settings(home=root)
    toml_path, legacy = root / "kovcheg.toml", root / "config.json"
    if toml_path.exists():
        _apply(s, tomllib.loads(toml_path.read_text(encoding="utf-8")), "")
    elif legacy.exists():
        _apply(s, _from_legacy(json.loads(legacy.read_text(encoding="utf-8"))), "")
    if overrides:
        _apply(s, overrides, "")
    return s
