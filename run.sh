#!/usr/bin/env bash
# One-command local run (mock LLM, SQLite). GUI at http://localhost:8000
set -e
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload --port "${PORT:-8000}"
