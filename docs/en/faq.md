# FAQ

[Українська](../uk/faq.md) · [Docs index](README.md)

**Does Kovcheg need the internet?**
No. Nothing in Kovcheg makes network requests. You need the internet only once, to download Kovcheg, its Python packages and the models, and that can be done on another computer (see [portable.md](portable.md)).

**What is the minimum hardware?**
For keyword search: any computer that runs Python 3.11, with about 2 GB of RAM. For semantic search with written answers: about 8 GB of RAM and a recent 4-core CPU. A GPU is not needed. Run `kovcheg doctor` for a recommendation for your machine.

**Can I use it without any AI model?**
Yes. Build modules with `--no-embed` and leave `[llm] model` empty. Kovcheg is then a fast full-text search engine with page references, and it tolerates word endings, so «кровотечу» finds «кровотеча».

**Which languages does it support?**
Documents and questions in any language that SQLite tokenises by spaces, which covers Ukrainian, English, other European languages and Russian. With BGE-M3, questions can be in a different language from the documents. The answer is written in the language of the question if the language model can do it. The interface is in Ukrainian and English.

**Why did Kovcheg say "not in the library" when the answer is in my documents?**
Either retrieval did not find the passage, or the reranker judged it irrelevant. Try other words. Use `kovcheg search` to see the closest passages. Lower `rerank.min_score` slightly, or check that the document was indexed (`kovcheg inspect`). Scanned PDFs without a text layer are skipped and need OCR first.

**Can I trust the generated answer?**
Treat it as a pointer to the sources, not as the authority. Small models can misread numbers. Kovcheg shows the exact passages and their pages so that you can check, which matters most for doses and technical limits.

**How big can a library be?**
Vectors are memory-mapped float16 (about 2 KB per chunk with BGE-M3), so millions of chunks fit on disk without needing the same amount of RAM. Building the sparse index of a very large module (a full Wikipedia) needs several GB of RAM once, at build time. Index such libraries on a strong machine and copy the module.

**Can several people use one Kovcheg?**
Yes. Set `[ui] host = "0.0.0.0"` and they open the address in a browser on the same network. Questions are processed one at a time on the model side, so expect queues on a small machine.

**How do I move from the old `ark-system` prototype?**
Run `kovcheg migrate <module>` for each module in `modules/`. The vectors are reused, so no model is needed for the conversion. Your old `config.json` is read automatically; for new features, start a `kovcheg.toml` (`kovcheg init` writes one).
