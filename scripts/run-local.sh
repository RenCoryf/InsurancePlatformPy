#!/bin/bash
# Local dev runner — starts FastAPI backend on :8000.
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
unset VIRTUAL_ENV PYTHONPATH PYTHONHOME 2>/dev/null || true
exec uv run --project . python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
