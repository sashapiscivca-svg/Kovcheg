"""Record the README terminal animation from the real output of `kovcheg ask` (nothing is staged or edited).

    python scripts/make_cli_gif.py --home DEMO_HOME --out docs/assets/kovcheg-cli.gif \
        --question "how long should I boil water" --question "how do I repair a car engine"

DEMO_HOME is a Kovcheg home with the demo library built as module `demo` (see examples/DEMO.md). Needs Pillow and the
DejaVu Sans Mono font.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
W, H, LINE, COLS = 1000, 560, 21, 108
BG, FG, DIM = (24, 26, 31), (220, 223, 228), (140, 146, 155)
GREEN, YELLOW, BLUE, RED = (126, 211, 135), (240, 200, 100), (120, 180, 255), (240, 130, 110)


def kovcheg(home: str, question: str, top_k: int) -> list[str]:
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    out = subprocess.run([sys.executable, "-m", "kovcheg", "--home", home, "ask", question, "-m", "demo", "-k", str(top_k)],
                         capture_output=True, text=True, env=env).stdout
    return out.rstrip("\n").split("\n")


def colour(line: str, font, bold):
    if line.startswith("$ "):
        return [(line[:2], GREEN, bold), (line[2:], FG, font)]
    if line.startswith("[") and "]" in line[:4]:
        return [(line, YELLOW, bold)]
    if line.startswith(("Sources:", "Closest passages", "Джерела:", "Найближчі фрагменти")):
        return [(line, BLUE, bold)]
    if line.startswith(("Kovcheg can be wrong", "Search-only", "Ковчег може", "екстрені служби", "Режим пошуку")):
        return [(line, DIM, font)]
    if line.startswith(("The selected modules", "У вибраних модулях")):
        return [(line, RED, font)]
    return [(line, FG, font)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--question", action="append", required=True)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--title", default="kovcheg — search-only, no AI model")
    a = ap.parse_args()
    font = ImageFont.truetype(str(FONT_DIR / "DejaVuSansMono.ttf"), 15)
    bold = ImageFont.truetype(str(FONT_DIR / "DejaVuSansMono-Bold.ttf"), 15)

    def frame(lines: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 28], fill=(38, 41, 48))
        for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
            d.ellipse([12 + i * 20, 9, 24 + i * 20, 21], fill=c)
        d.text((W // 2 - d.textlength(a.title, font=font) // 2, 6), a.title, fill=DIM, font=font)
        y = 40
        for line in lines[-((H - 44) // LINE):]:
            x = 14
            for text, col, f in colour(line, font, bold):
                d.text((x, y), text, fill=col, font=f)
                x += d.textlength(text, font=f)
            y += LINE
        return im

    frames, durations, history = [], [], []
    for q in a.question:
        cmd = f'kovcheg ask "{q}" -m demo -k {a.top_k}'
        for k in range(0, len(cmd) + 1, 2):
            frames.append(frame(history + ["$ " + cmd[:k] + "▌"]))
            durations.append(45)
        shown = history + ["$ " + cmd]
        frames.append(frame(shown))
        durations.append(500)
        for raw in kovcheg(a.home, q, a.top_k):
            indent = len(raw) - len(raw.lstrip(" "))
            for line in textwrap.wrap(raw, COLS, subsequent_indent=" " * indent) or [""]:
                shown = shown + [line]
                frames.append(frame(shown))
                durations.append(90)
        durations[-1] = 4500
        history = shown + [""]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(a.out, len(frames), "frames")


if __name__ == "__main__":
    main()
