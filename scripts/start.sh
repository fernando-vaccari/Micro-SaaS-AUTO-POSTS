#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
exec npx wrangler dev --ip 127.0.0.1 --port "${AUTOPOSTS_PORT:-8787}" --test-scheduled
