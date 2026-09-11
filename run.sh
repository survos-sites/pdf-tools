#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-5001}"
HOST="${HOST:-127.0.0.1}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN" >&2
  exit 1
fi

# Read API needs no Tesseract/Ghostscript. Install full requirements.txt for legacy OCR.
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip --version >/dev/null 2>&1 || python -m ensurepip
python -m pip install -r "$ROOT_DIR/requirements-read.txt"
cd "$ROOT_DIR"
exec python -m uvicorn app:app --reload --host "$HOST" --port "$PORT"
