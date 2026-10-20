#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'Execute ./scripts/install.sh antes de iniciar o aplicativo.' >&2
  exit 1
fi

exec .venv/bin/python -m uvicorn autoposts.main:app \
  --host "${AUTOPOSTS_HOST:-127.0.0.1}" \
  --port "${AUTOPOSTS_PORT:-8000}" \
  --workers 1 \
  --no-access-log
