# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [1.0.1] — 2026-10-15

### Improved
- Keyword search for Ukrainian: words with apostrophes (кип'ятити, м'ясо) are single tokens, and inflected forms meet through a fixed-length prefix (кип'ятити / кип'ятіть / кип'ятіння).
- Ranking of keyword matches: a question word in a passage's section heading counts as a strong topic signal.
- Search-only answers show the sentence that answers the question (query-focused snippets) instead of the first 240 characters.
- The command line shows answers, sources and the safety notice in the interface language (Ukrainian by default, `[ui] language = "en"` for English).
- The web interface hides the Streamlit "Deploy" button and developer menu.

### Added
- A demo library in English and Ukrainian (`examples/demo-library`, `examples/demo-library-uk`) with an evaluation file, and README media: a terminal recording (`scripts/make_cli_gif.py`) and screenshots of the web interface.

## [1.0.0] — 2026-10-15

First public release. A rewrite of the `ark-system` prototype as the installable package `kovcheg`.

### Added
- BM25 full-text search (SQLite FTS5) that works with no ML models at all, fused with dense and sparse BGE-M3 retrieval by weighted Reciprocal Rank Fusion.
- Module format v2: float16 memory-mapped vectors, sparse inverted index, documents/chunks tables with page numbers and section headings, a manifest with SHA-256 hashes of every file.
- Evidence gate: when nothing relevant is found, no language model is called and the user is told the library has no answer. Without a reranker, at least one content word of the question must occur in a source.
- Inflection-tolerant keyword search (prefix terms), so Ukrainian word forms match without a stemmer.
- Citation check: every `[n]` in an answer is validated against the numbered source list.
- Chat-template-aware generation for any GGUF model, with a token budget for the context.
- Command-line interface: `init`, `build`, `search`, `ask`, `ui`, `modules`, `inspect`, `verify`, `keygen`, `sign`, `migrate`, `doctor`, `eval`.
- Readers with structure: PDF pages, DOCX and Markdown headings, HTML, ZIM (all entries), text formats.
- Documentation in English and Ukrainian; test suite with fake models.

### Fixed (relative to the prototype)
- Signatures covered only the manifest, not the index; a modified database went unnoticed. The manifest now contains file hashes.
- Citation numbers in answers did not match the displayed source list.
- ZIM files were re-indexed on every incremental build, duplicating content; only articles with Cyrillic-prefixed titles were reached.
- Files with the same name in different folders overwrote each other in the index.
- The prompt was hard-wired to the Phi-3 template; other GGUF models received a wrong format.
- All vectors were held in RAM as float32; large libraries did not fit on small machines.
- The PyInstaller build excluded PyTorch, which the embedding model needs.
- `check_db.py` and `setup.py` referred to an obsolete layout; `setup.py` downloaded a model whose licence forbids commercial use.

### Removed
- Legacy FAISS / sentence-transformers backend, the unused keyword co-occurrence graph, `setup.py`, `check_db.py`, `build.spec`.

### Migration
- `kovcheg migrate <module>` converts prototype modules (`search_bge.db`) without re-encoding.
