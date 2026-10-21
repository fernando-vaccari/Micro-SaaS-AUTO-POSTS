#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-/tmp/autoposts-npm-cache}"
npm ci
if [[ ! -f .dev.vars ]]; then
  node --input-type=module -e "import { randomBytes } from 'node:crypto'; import { writeFileSync } from 'node:fs'; writeFileSync('.dev.vars', 'APP_SECRET=' + randomBytes(48).toString('base64url') + '\\n', {flag:'wx',mode:0o600})"
fi
npm run build
npm run db:migrate:local
