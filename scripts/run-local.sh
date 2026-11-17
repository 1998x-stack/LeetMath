#!/usr/bin/env sh
# Local dev server on SQLite with demo seed data: http://127.0.0.1:8000
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/backend"
python -m leetmath.cli seed
exec python -m leetmath.cli serve --host 127.0.0.1 --port "${PORT:-8000}"
