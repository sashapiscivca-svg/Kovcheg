#!/usr/bin/env sh
# Kovcheg launcher for a portable kit: runs Kovcheg with this folder as its home.
# Usage: ./kovcheg.sh            -> web interface
#        ./kovcheg.sh <command>  -> any kovcheg command (doctor, ask, build, ...)
HERE="$(cd "$(dirname "$0")" && pwd)"
export KOVCHEG_HOME="$HERE"
BIN="$HERE/.venv/bin/kovcheg"
[ -x "$BIN" ] || BIN="kovcheg"
if [ $# -eq 0 ]; then exec "$BIN" ui; else exec "$BIN" "$@"; fi
