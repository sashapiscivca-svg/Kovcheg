# Models

[Українська](../uk/models.md) · [Docs index](README.md)

Kovcheg uses up to three models. Each is optional, each is a local file or folder you download once, and Kovcheg never downloads anything by itself.

| Component | Without it | With it |
|---|---|---|
| **Embedding model** (BGE-M3) | BM25 keyword search only; the question must share words with the answer; no cross-language search | semantic and multilingual search, plus learned lexical weights (sparse) |
| **Reranker** (BGE reranker v2-m3) | candidates are ordered by fused retrieval scores | a cross-encoder re-reads the top candidates together with the question; better top results and a reliable "no evidence" signal |
| **Language model** (any instruction GGUF) | the answer is the list of matching passages | a short written answer citing the passages as [1], [2] |

## Recommended files

Put everything under `models/` in the Kovcheg home folder (paths are configurable in `kovcheg.toml`).

| Model | Licence | Size | Put it at |
|---|---|---:|---|
| [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT | 2.3 GB | `models/bge-m3/` |
| [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Apache-2.0 | 2.3 GB | `models/bge-reranker-v2-m3/` |
| [Qwen2.5-1.5B-Instruct Q4_K_M](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) | Apache-2.0 | 1.1 GB | `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| [Phi-3.5-mini-instruct Q4_K_M](https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF) | MIT | 2.4 GB | `models/Phi-3.5-mini-instruct-Q4_K_M.gguf` |
| [Qwen2.5-7B-Instruct Q4_K_M](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF) (two parts) | Apache-2.0 | 4.7 GB | `models/qwen2.5-7b-instruct-q4_k_m-0000{1,2}-of-00002.gguf` |

## Download (on a machine with internet)

With the Hugging Face command-line tool (`pip install huggingface_hub`):

```bash
huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3 --exclude "onnx/*" "imgs/*"
huggingface-cli download BAAI/bge-reranker-v2-m3 --local-dir models/bge-reranker-v2-m3
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir models
huggingface-cli download bartowski/Phi-3.5-mini-instruct-GGUF Phi-3.5-mini-instruct-Q4_K_M.gguf --local-dir models
```

Or with `git` (requires Git LFS): `git clone https://huggingface.co/BAAI/bge-m3 models/bge-m3`.

Then copy the `models/` folder to the offline machine. Run `kovcheg doctor` there: it lists which models it finds, their sizes, and the tier your hardware supports.

## Choosing a language model

- Small models (1–2 B parameters) are fast on a mini PC (roughly 5–15 tokens per second on a 4-core CPU, so a 300-token answer takes 20–60 s), but they misread passages more often. Medium models (3–8 B) are better readers but 2–5× slower and need more RAM.
- Prefer models with good support for the languages of your documents and questions. Multilingual quality of small models varies, so test with your own questions (`kovcheg eval` measures retrieval; read a sample of answers yourself).
- Q4_K_M quantisation is a good default. Q5_K_M or Q8_0 read numbers a little more reliably, at a higher RAM cost.
- Check the licence: Qwen2.5-3B-Instruct (Qwen Research licence), Llama and Gemma models have terms that may not allow your use.

## Memory budget

As a rule of thumb, RAM in use ≈ embedding model (BGE-M3 ≈ 2.3 GB in fp32 on CPU) + reranker (≈ 2.3 GB, only if enabled) + GGUF file size + context (≈ 0.3–1 GB for 4–8 k tokens) + 0.3 GB. The module vectors are memory-mapped and do not count fully against RAM.

On an 8 GB machine, do not enable all three large models together. The [tier A example](../../examples/tier-a-minipc.toml) leaves the reranker off.

## Installing the inference libraries

```bash
pip install -e ".[embed]"     # FlagEmbedding + PyTorch, for BGE-M3 and the reranker
pip install -e ".[llm]"       # llama-cpp-python, for GGUF models
```

On Linux without a GPU, install the CPU build of PyTorch first. It is about ten times smaller than the default CUDA build: `pip install torch --index-url https://download.pytorch.org/whl/cpu`. `llama-cpp-python` compiles from source when no prebuilt wheel exists for your platform. See its documentation for prebuilt CPU wheels.
