#!/usr/bin/env bash
set -e

# Loads the environment if .venv exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set host and port with defaults if not provided
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"

echo "Starting FastAPI server on ${HOST}:${PORT}..."
exec python3 -m uvicorn src.main:app --host "$HOST" --port "$PORT" "$@"
