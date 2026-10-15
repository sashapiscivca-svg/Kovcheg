# Contributing to Kovcheg

[Українська](docs/uk/CONTRIBUTING.md)

Thank you for helping. Kovcheg improves most from real use: questions it failed to answer, documents it read badly, machines it was too slow on.

## Ways to help

- **Report failures** with the question, the module and, if you can share them, the documents involved. Label safety-relevant problems `safety`.
- **Benchmarks:** run `kovcheg doctor` and time `kovcheg ask` on your hardware, and send the numbers.
- **Evaluation sets:** JSONL files of questions with the document (and page) that answers them, for openly licensed documents. They make retrieval changes measurable (`kovcheg eval`).
- **Code:** readers for more formats, OCR integration, faster indexing on weak CPUs, translations of the interface.

## Ground rules

1. **Offline first.** No feature may require network access at run time, and nothing may phone home.
2. **Degrade, don't fail.** Every optional component (embedder, reranker, LLM, readers) must stay optional. `pip install kovcheg` with numpy alone must keep working.
3. **Honest answers.** Changes to prompting or ranking must keep citations exact and must not weaken the evidence gate.
4. **Measure.** Claims of better retrieval need `kovcheg eval` numbers before and after on a shared evaluation set.
5. **No model weights or copyrighted documents in the repository.**

## Development

```bash
git clone https://github.com/sashapiscivca-svg/Kovcheg && cd Kovcheg
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                 # fast, uses fake models; downloads nothing
ruff check src tests
```

Code and comments are in English. User documentation is kept in English (`docs/en`, `*.md`) and Ukrainian (`docs/uk`, `*.uk.md`); if you can only update one language, say so in the pull request. By contributing you agree that your contribution is licensed under the MIT License.
