# Using Kovcheg: command line and web interface

[Українська](../uk/usage.md) · [Docs index](README.md)

Every command accepts `--home DIR` (default: `$KOVCHEG_HOME`, else the current folder) and `--set KEY=VALUE` to override a setting for one run, for example `--set llm.model=models/other.gguf` or `--set rerank.enabled=false`.

## Commands

| Command | What it does |
|---|---|
| `kovcheg init` | create `modules/`, `sources/`, `models/`, `keys/` and a commented `kovcheg.toml` |
| `kovcheg build NAME [--source DIR] [--title T] [--description D] [--language L] [--rebuild] [--no-embed] [-q]` | create or update a module from `sources/NAME/` (or `--source`) |
| `kovcheg search QUESTION [-m MODULE]… [-k N] [--no-rerank] [--json]` | show the most relevant passages |
| `kovcheg ask QUESTION [-m MODULE]… [-k N] [--no-rerank] [--search-only] [--json]` | answer with numbered sources |
| `kovcheg ui [--host H] [--port P]` | start the web interface |
| `kovcheg modules` (`list`) | modules with integrity status, size and encoder |
| `kovcheg inspect NAME` | manifest, files and documents of a module |
| `kovcheg verify [NAME] [--quick]` | check signatures and file hashes (`--quick`: sizes only) |
| `kovcheg keygen` / `kovcheg sign NAME` | create a signing key pair / sign a module |
| `kovcheg migrate NAME [--delete-old]` | convert a prototype module (`search_bge.db`) to format v2 without re-encoding |
| `kovcheg doctor [--json]` | check the computer, libraries, models and modules; recommends a hardware tier |
| `kovcheg eval FILE.jsonl [-m MODULE]… [-k N] [--json]` | measure retrieval quality |

Without `-m`, all modules whose integrity is not INVALID are searched.

On Windows, a module that is open in a running web interface cannot be replaced: `kovcheg build` stops with a clear message and leaves the previous version intact. Close the interface (or press its reload button) and build again.

**Exit codes:** 0 success; 1 error (including an INVALID module in `verify`); 2 usage error; 3 no evidence (nothing relevant found); 4 missing component (module, model, library or key). Scripts can rely on them.

## Output

```
$ kovcheg ask "як зупинити сильну кровотечу" -m first-aid
Притисніть рану чистою тканиною і тисніть щонайменше 10 хвилин [1]. Якщо пряме притискання не допомагає,
накладіть турнікет на 5–7 см вище рани і запишіть час [1].

Sources:
[1] Зупинка кровотечі — Сильна кровотеча з кінцівки  (first-aid: bleeding.md)
    Притисніть рану чистою тканиною і тисніть сильно щонайменше 10 хвилин. …
```

With `--json`, the output is one JSON object with `question`, `status`, `answer`, `sources` (each with `n`, `module`, `path`, `title`, `page`, `section`, `citation`, `text`, `context` and the scores `score`, `dense`, `sparse`, `bm25`, `rerank`, `relevance`), `citations` (`n`, `valid`), `warnings` and `timings`.

## Web interface

`kovcheg ui` starts a local web page (default http://127.0.0.1:8501).

- **Left panel:** the modules with integrity badges (valid / unsigned / untrusted / INVALID), the number of documents, and toggles for search-only mode and reranking. INVALID modules are unchecked by default and show a red warning.
- **Answer:** streamed as it is generated, with `[n]` citations. A citation that does not match a source is highlighted with ⚠.
- **Sources:** numbered exactly as cited, with document, page, section, the passage and the neighbouring text. Sources that the answer actually cites are marked.
- **Status line:** which models are active (embedding, reranker, LLM) and why a model is off.
- **Language:** Ukrainian by default, English with `[ui] language = "en"`.

To let phones and laptops on the same Wi-Fi use one Kovcheg machine, set `[ui] host = "0.0.0.0"` and open `http://<machine-ip>:8501` on the other devices. There is no authentication, so do this only on a network you control.

## Measuring retrieval quality

Create a JSONL file with one question per line and the document that answers it:

```json
{"question": "How long should water be boiled?", "expected": "water.txt"}
{"question": "Код J18.9", "expected": ["medicine:icd10.pdf", "medicine:pneumonia.md"]}
```

`kovcheg eval questions.jsonl` reports hit@1, hit@3, hit@k and MRR. Run it before and after changing settings, models or documents.
