#!/usr/bin/env bash
# One-command local run.  All settings are read from .env in this folder.
# Dependencies stay inside .venv/ — nothing is installed globally.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment in .venv/ ..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --quiet -r "$DIR/requirements.txt"

# Read server settings from .env (dotenv syntax: KEY=VALUE, blank lines / # ignored)
get_env() {
  grep -E "^${1}=" "$DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' '
}
HOST="${TSP_HOST:-$(get_env TSP_HOST)}"
PORT="${TSP_PORT:-$(get_env TSP_PORT)}"
RELOAD_FLAG="${TSP_RELOAD:-$(get_env TSP_RELOAD)}"
LOG_LEVEL="${TSP_LOG_LEVEL:-$(get_env TSP_LOG_LEVEL)}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"

RELOAD_ARG=""
if [ "${RELOAD_FLAG:-true}" = "true" ]; then RELOAD_ARG="--reload"; fi

echo "Starting Term Sheet Parser on http://${HOST}:${PORT}  (log=${LOG_LEVEL})"
exec uvicorn backend.app.main:app \
  --host "$HOST" --port "$PORT" \
  --log-level "$LOG_LEVEL" \
  $RELOAD_ARG
