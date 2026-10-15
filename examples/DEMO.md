# Demo library (`examples/demo-library/`)

Three short documents (English in `demo-library/`, the same three in Ukrainian in `demo-library-uk/`) for trying Kovcheg and for the screenshots in the README. They are summaries written for this project and released under the project's MIT licence. Each one names the public guidance it summarises. They are **examples, not authoritative guidance**: for real use, put the official, current documents of your country into your library.

```bash
kovcheg build demo --source examples/demo-library --no-embed --title "Demo library"
kovcheg ask "how long to boil water" -m demo
```

Ukrainian:

```bash
kovcheg build demo --source examples/demo-library-uk --no-embed --title "Демо-бібліотека"
kovcheg ask "скільки кип'ятити воду" -m demo
```
