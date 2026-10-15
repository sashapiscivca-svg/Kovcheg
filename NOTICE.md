# NOTICE — third-party components

[Українська](NOTICE.uk.md)

Kovcheg is released under the [MIT License](LICENSE), Copyright (c) 2026 The Kovcheg authors. It does not include any model weights or documents. The components below are installed separately by the user (through `pip` extras or manual downloads) and remain under their own licences.

## Models (recommended, downloaded by the user)

| Model | Licence | Notes |
|---|---|---|
| BAAI/bge-m3 | MIT | dense and sparse embeddings |
| BAAI/bge-reranker-v2-m3 | Apache-2.0 | cross-encoder reranker |
| Qwen/Qwen2.5-1.5B-Instruct, Qwen/Qwen2.5-7B-Instruct (GGUF) | Apache-2.0 | answer generation |
| microsoft/Phi-3.5-mini-instruct (GGUF conversion by bartowski) | MIT | answer generation |

Licences were read from the model cards on the Hugging Face Hub (October 2026). Not every instruction model is open for commercial use: for example, Qwen2.5-3B-Instruct uses the Qwen Research licence, and Llama and Gemma models have their own terms. Check the card of any model you use.

## Python libraries

| Package | Licence | Used for | Extra |
|---|---|---|---|
| numpy | BSD-3-Clause | vectors, ranking | core |
| SQLite (Python standard library, FTS5) | public domain | storage, BM25 | core |
| Python `html.parser` (standard library) | PSF | HTML and ZIM articles | core |
| pdfplumber | MIT | PDF text with page numbers | `docs` |
| pypdf | BSD-3-Clause | PDF fallback reader | `docs` |
| python-docx | MIT | DOCX | `docs` |
| libzim | **GPL-3.0-or-later** | ZIM archives | `zim` (optional) |
| FlagEmbedding | MIT | BGE-M3 and reranker inference | `embed` |
| PyTorch (via FlagEmbedding) | BSD-style | model inference | `embed` |
| llama-cpp-python | MIT | GGUF language models | `llm` |
| streamlit | Apache-2.0 | web interface | `ui` |
| cryptography | Apache-2.0 OR BSD-3-Clause | Ed25519 signatures | `sign` |

Kovcheg's own code calls `libzim` only when the `zim` extra is installed. If you distribute a bundle that contains `libzim`, the GPL terms apply to that bundle.

## Ideas

Reciprocal Rank Fusion (Cormack, Clarke and Büttcher, 2009); BM25 (Robertson and Zaragoza, 2009); BGE-M3 hybrid retrieval (Chen et al., 2024); contextual chunk headers and context expansion are common practice in retrieval-augmented generation. All code in this repository was written for Kovcheg.
