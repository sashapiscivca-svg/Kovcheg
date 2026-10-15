"""Helpers for the indexing tests: a Kovcheg home with a small source folder, built through the real builder."""
from __future__ import annotations

from pathlib import Path

from kovcheg.config import Settings, load_settings
from kovcheg.embedding import HashingEncoder

ENC = HashingEncoder(64)

SOURCES = {
    "first-aid.md": "# First aid\n\n## Bleeding control\n\nApply firm direct pressure on the wound with a clean cloth. "
                    "Keep pressing for at least ten minutes.\n\n## Burns\n\nCool the burn under running water for twenty minutes.\n",
    "codes.txt": "Pneumonia, unspecified organism is coded J18.9 in ICD-10. Acute bronchitis is coded J20.\n",
    "notes/water.txt": "Boil water for at least one minute to make it safe to drink.\n",
    "page.html": "<html><head><title>Field guide</title><script>var x = 'SCRIPTJUNK';</script></head><body><nav>Home | NAVJUNK</nav>"
                 "<h1>Shelter</h1><p>Build a shelter out of the wind.</p><footer>FOOTERJUNK</footer></body></html>",
}


def make_settings(tmp: Path, **chunking) -> Settings:
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    s = load_settings(home, {"embedding": {"model": ""}, "chunking": chunking} if chunking else {"embedding": {"model": ""}})
    return s


def write_sources(root: Path, files: dict[str, str | bytes] = SOURCES) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return root
