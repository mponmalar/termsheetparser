#!/usr/bin/env bash
# One-command local run (mock LLM, SQLite). GUI at http://localhost:8000
# Dependencies are kept inside .venv/ — nothing is installed globally.
set -e

VENV_DIR="$(dirname "$0")/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in .venv/ ..."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet -r "$(dirname "$0")/requirements.txt"

exec uvicorn backend.app.main:app --reload --port "${PORT:-8000}"
