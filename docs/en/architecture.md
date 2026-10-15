# Architecture

[Українська](../uk/architecture.md) · [Docs index](README.md)

Kovcheg has two halves: **indexing**, which turns documents into a module, and **answering**, which turns a question into sources and an answer. They meet in the module format, a folder of plain files that can be copied between machines.

## Package map

| Module | Responsibility |
|---|---|
| `config.py` | settings (`kovcheg.toml`, legacy `config.json`), home-folder layout |
| `readers.py` | PDF (one section per page), DOCX and Markdown (sections by heading), HTML, text formats, ZIM (every article) |
| `chunking.py` | structure-aware chunks: paragraphs → lines → sentences, never across a page or section boundary |
| `embedding.py` | `Encoder` protocol; BGE-M3 (dense + sparse); a model-free hashing encoder for tests |
| `builder.py` | incremental, atomic module builds |
| `store.py` | module format v2: writer and read-only `ModuleIndex` |
| `security.py` | Ed25519 keys, signing, deep verification with a cache |
| `migrate.py` | conversion of prototype (`search_bge.db`) modules without re-encoding |
| `retrieval.py` | BM25, dense and sparse retrieval, weighted RRF, dedup, diversity, context expansion |
| `rerank.py` | cross-encoder reranking (BGE reranker v2-m3) |
| `generation.py` | prompt construction within a token budget, llama.cpp generation, citation checking |
| `engine.py` | the `Kovcheg` facade used by the CLI and the UI: lazy models, evidence gate, statuses |
| `cli.py`, `ui/` | command line and Streamlit interface |

Heavy libraries (PyTorch, llama.cpp, Streamlit, PDF/DOCX/ZIM readers, cryptography) are imported only inside the functions that need them. `import kovcheg` and keyword search need numpy alone.

## Indexing

1. **Reading.** Each file becomes a list of sections `(text, page, heading)`. PDFs keep their page numbers, which every citation then shows. DOCX and Markdown keep headings. HTML and ZIM pages are cleaned of scripts, navigation and footers with the standard-library HTML parser. Files that cannot be read (binary, scanned PDF without text) are skipped and listed with the reason in the build report.
2. **Chunking.** Sections are split into paragraphs, lines and sentences (including CJK punctuation) and packed into chunks of about 1,000 characters (at most 1,600), with one sentence of overlap. Chunks never cross a page or a section. The text sent to the embedding model is prefixed with `title — section:` so that a chunk such as "apply pressure for 10 minutes" is embedded together with its context ("Bleeding — Limb wounds"). The stored text stays unchanged.
3. **Encoding (optional).** BGE-M3 produces a 1024-dimensional dense vector and sparse lexical weights per chunk. Without an encoder (`--no-embed`), only the full-text index is built.
4. **Storing.** One SQLite database (documents, chunks, FTS5 full-text index, per-chunk sparse weights), a float16 vector matrix (`dense.f16.npy`) and a sparse inverted index (`sparse.npz`). Both arrays are uncompressed so they can be memory-mapped.
5. **Incremental updates.** Documents are matched by path and SHA-256. Unchanged documents keep their vectors, which are copied from the previous matrix without re-encoding. Changed documents are re-indexed, and deleted ones are removed. ZIM articles are tracked individually, so a re-run never duplicates them. A change of encoder or chunking settings triggers a full re-index, with a message saying why.
6. **Atomic finalisation.** A build works in a hidden folder next to the module and replaces the module by renaming only after everything is written: the database is switched to rollback-journal mode, the manifest with SHA-256 hashes of all files is written, and the module is signed if a private key exists. An exception or Ctrl-C deletes the work folder and leaves the previous module untouched.

## Answering

```
question
  ├─ BM25 (SQLite FTS5)          always available
  ├─ dense (BGE-M3, float16)     if the module was built with the loaded encoder
  └─ sparse (BGE-M3 lexical)     idem
        │  weighted Reciprocal Rank Fusion (default weights dense 1.0, bm25 0.8, sparse 0.6)
        ▼
  dedup (identical text, near-identical vectors) → at most 3 hits per document
        ▼
  cross-encoder rerank of the top 20 (optional)
        ▼
  evidence gate ── fail ──► status "no_evidence": no LLM call; closest passages shown as low relevance
        │ pass
  context expansion: neighbouring chunks of each hit merged into its context
        ▼
  prompt with numbered sources, fitted to the token budget ──► local LLM (llama.cpp, model's own chat template)
        ▼
  citation check: every [n] must refer to a provided source
```

**Why three retrievers.** Dense vectors find paraphrases and work across languages ("як зупинити кровотечу" finds "control of haemorrhage"). Sparse BGE-M3 weights and BM25 find rare exact strings that dense vectors blur: drug names, ICD codes such as `J18.9`, part numbers, doses such as `500 mg`. BM25 also works with no model at all, which is what makes Kovcheg usable on any computer.

**Fusion.** Reciprocal Rank Fusion combines ranks rather than raw scores, so retrievers with incomparable score scales can be mixed without calibration. Each retriever's contribution is weighted. A module that offers only BM25 is normalised by the weight it can offer, so it competes fairly with fully embedded modules. Raw BM25 scores are not comparable between modules of different sizes, so BM25 candidates are ordered first by how many content words of the question they contain.

**FTS5 query.** The question is tokenised. Each token is quoted, so punctuation such as `J18.9` cannot break the query syntax, and the tokens are joined with OR. Phrase matches are added for codes, numbers with units, and the whole question when it is short.

**Low memory.** Dense search multiplies the query by the float16 matrix in blocks (about 64 MB of float32 scratch space at a time) and keeps a running top-k. RAM use therefore does not grow with the size of the library. The sparse index is read through memory-mapped arrays. Opened modules are kept in a small LRU cache that notices when a module is rebuilt (file identity, size and modification time) and reopens it.

**Evidence gate.** With a reranker, a best logit below `rerank.min_score` (default −6) means there is nothing relevant. Without a reranker or dense retrieval, at least one content word of the question (ignoring inflectional endings) must occur in a source. Otherwise the keyword OR-query would match almost anything through one common word. When the gate fails, the LLM is not called. Saying "not in the library" is safer than a fluent guess.

**Generation.** Sources are numbered `[1] … [n]` in rank order, each with its citation (document, page, section) and its text plus neighbouring chunks. If the prompt would exceed `context_window − max_tokens`, the lowest-ranked sources first lose their neighbours and are then dropped. The model's own tokenizer measures the budget when available. Kovcheg uses llama.cpp's chat-completion API, so the chat template stored in the GGUF file is applied: any instruction model works. Models without a system role get the instructions merged into the user turn. The system prompt asks for answers only from the sources, a citation after each claim, numbers and doses copied exactly, an explicit statement when the sources are insufficient, and the answer in the language of the question.

**Citation check.** After generation, every `[n]` is parsed. Numbers outside the provided sources are flagged as invalid, and an answer with no citations gets a warning to verify it against the sources. `Answer.hits[n-1]` is always source `[n]` in the CLI, the UI and the JSON output.

**Statuses.** `ok`, `no_evidence`, `search_only` (no language model, or search-only requested), `llm_unavailable` (configured but failed to load; the sources are still returned), `error` (generation failed; the sources are kept). Missing models never stop the system; they show up as warnings and in `kovcheg doctor`.

## Concurrency

One `Kovcheg` engine serves the whole web interface. Locks serialise calls into the encoder, the reranker and the LLM, which are not thread-safe and would not run faster in parallel on a small CPU anyway. Modules are opened read-only (`immutable=1`), so the app never changes a file, and hashes stay valid.
