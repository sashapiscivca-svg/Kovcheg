# A portable, offline USB kit

[Українська](../uk/portable.md) · [Docs index](README.md)

A Kovcheg deployment is a single folder. Prepare it once on a computer with internet access, copy it to a USB stick or SSD, and run it on any machine with the same operating system and CPU architecture, with no internet and no administrator rights.

```
KOVCHEG/
├── kovcheg.toml          settings (start from examples/tier-*.toml)
├── models/               downloaded models (see models.md)
├── modules/              built knowledge modules
├── keys/trusted/         public keys of module authors you trust
├── wheelhouse/           Python packages for offline installation
├── src/, pyproject.toml  Kovcheg itself (a copy of this repository)
├── kovcheg.sh            launcher for Linux / macOS
└── kovcheg.bat           launcher for Windows
```

## 1. Prepare (online, on the same OS and architecture as the target)

```bash
git clone https://github.com/sashapiscivca-svg/Kovcheg KOVCHEG && cd KOVCHEG
cp examples/tier-a-minipc.toml kovcheg.toml                     # or tier-s / tier-b
# Linux: CPU-only PyTorch keeps the kit small
python3 -m pip download -d wheelhouse torch --index-url https://download.pytorch.org/whl/cpu
python3 -m pip download -d wheelhouse ".[docs,ui,sign,embed,llm]" setuptools wheel   # setuptools: needed to install Kovcheg itself offline
```

Download the models into `models/` ([models.md](models.md)) and build your modules (`kovcheg build ...`), or copy modules built elsewhere into `modules/`.

`llama-cpp-python` may be built from source during `pip download`. In that case the downloaded file is a source archive, and the target would need a compiler. To avoid that, build a wheel on the preparation machine (`pip wheel llama-cpp-python -w wheelhouse`) and copy it.

## 2. Install on the target (offline)

The target needs Python 3.11 or newer. Windows: install it from python.org for the current user, which needs no administrator rights. Most Linux distributions already include it.

```bash
cd /media/usb/KOVCHEG
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links wheelhouse -e ".[docs,ui,sign,embed,llm]"
```

Windows: `py -3 -m venv .venv` and `.venv\Scripts\pip install --no-index --find-links wheelhouse -e ".[docs,ui,sign,embed,llm]"`.

## 3. Run

`kovcheg.sh` and `kovcheg.bat` set `KOVCHEG_HOME` to the kit folder and start the web interface:

```bash
./kovcheg.sh            # same as: KOVCHEG_HOME=$PWD .venv/bin/kovcheg ui
./kovcheg.sh doctor     # any kovcheg command can follow
```

## Tips for field use

- **Test the kit on the target hardware before you need it.** Run `kovcheg doctor` and a few typical questions.
- Keep a **search-only fallback**: if the machine has too little RAM, start with `kovcheg ui` after setting `[llm] model = ""` and `[embedding] model = ""` (BM25 needs no models, but modules built with an embedder still work: their full-text index is always present).
- USB 2.0 sticks are slow. Loading a 2.3 GB model can take a minute, so copy the kit to the internal disk when you can.
- Keep a second copy of the kit, and a printed list of the documents it contains.
