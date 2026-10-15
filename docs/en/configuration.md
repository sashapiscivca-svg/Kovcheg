# Configuration

[Українська](../uk/configuration.md) · [Docs index](README.md)

All settings live in `kovcheg.toml` in the Kovcheg home folder. Every key is optional; `kovcheg init` writes a commented file with the defaults. Ready-made files for each hardware tier are in [`examples/`](../../examples). Paths are relative to the home folder. A prototype `config.json` is still read when no `kovcheg.toml` exists.

Override any key for a single command with `--set section.key=value`, e.g. `kovcheg ask "..." --set llm.temperature=0`.

## `[embedding]`

| Key | Default | Meaning |
|---|---|---|
| `model` | `"models/bge-m3"` | folder with BAAI/bge-m3; `""` disables semantic search (BM25 only) |
| `device` | `"cpu"` | `"cuda"` if a GPU and a CUDA build of PyTorch are present |
| `fp16` | `false` | half precision; useful on GPU only |
| `batch_size` | `16` | chunks per batch when indexing; lower it on machines with little RAM |
| `max_length` | `1024` | tokens per chunk when indexing |
| `query_max_length` | `256` | tokens per question |

## `[rerank]`

| Key | Default | Meaning |
|---|---|---|
| `model` | `"models/bge-reranker-v2-m3"` | folder with the cross-encoder; `""` disables it |
| `enabled` | `true` | turn reranking on or off without removing the model |
| `top_n` | `20` | candidates scored per question; time grows linearly |
| `max_length` | `512` | tokens per question+passage pair |
| `batch_size` | `8` | pairs per batch |
| `min_score` | `-6.0` | logit below which the best passage counts as "no evidence"; raise it (e.g. −3) to be stricter |

## `[llm]`

| Key | Default | Meaning |
|---|---|---|
| `model` | `""` | path to a `.gguf` file; `""` = search-only mode. For split files, point to the first part |
| `context_window` | `4096` | tokens; sources are trimmed to fit `context_window − max_tokens` |
| `max_tokens` | `600` | maximum answer length |
| `temperature` | `0.1` | low values keep answers close to the sources |
| `top_p` | `0.9` | nucleus sampling |
| `repeat_penalty` | `1.1` | discourages repetition |
| `threads` | `0` | CPU threads; 0 = llama.cpp default (physical cores) |
| `gpu_layers` | `0` | layers offloaded to a GPU, if llama.cpp was built with GPU support |
| `chat_format` | `""` | override the chat template; `""` = the template stored in the GGUF file |

## `[retrieval]`

| Key | Default | Meaning |
|---|---|---|
| `top_k` | `8` | sources shown and given to the LLM |
| `candidates` | `50` | candidates per retriever before fusion |
| `rrf_k` | `60` | Reciprocal Rank Fusion constant |
| `weights` | `{ dense = 1.0, sparse = 0.6, bm25 = 0.8 }` | contribution of each retriever to the fused rank |
| `max_per_document` | `3` | diversity: at most this many sources from one document |
| `context_neighbors` | `1` | chunks before and after each source added to the LLM context; 0 disables |
| `dedup_threshold` | `0.95` | cosine similarity above which two passages count as duplicates |

## `[chunking]` (applies when building; changing it re-indexes modules on the next build)

| Key | Default | Meaning |
|---|---|---|
| `target_chars` | `1000` | preferred chunk length |
| `max_chars` | `1600` | hard upper limit |
| `overlap_sentences` | `1` | sentences repeated between consecutive chunks |
| `min_chars` | `40` | shorter tails are merged into the previous chunk |

## `[ui]`

| Key | Default | Meaning |
|---|---|---|
| `host` | `"127.0.0.1"` | `"0.0.0.0"` serves other devices on the network (no authentication) |
| `port` | `8501` | |
| `language` | `"uk"` | interface language: `uk` or `en` |

## Environment variables

- `KOVCHEG_HOME`: the home folder (legacy name `KOVCHEG_ROOT` is also accepted).
- Kovcheg sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` before loading embedding models, so no network access is attempted.
