#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

AUTOPOSTS_PYTHON="${AUTOPOSTS_PYTHON:-python3}"
"$AUTOPOSTS_PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12 ou superior é necessário."'

for executable in ffmpeg ffprobe; do
  if ! command -v "$executable" >/dev/null 2>&1; then
    printf '%s\n' "Falta $executable. Instale os pacotes ffmpeg, fonts-dejavu-core e tzdata do seu sistema e execute novamente." >&2
    exit 1
  fi
done
if ! ffmpeg -hide_banner -encoders 2>/dev/null | grep 'libx264' >/dev/null; then
  printf '%s\n' 'O FFmpeg precisa incluir o encoder libx264.' >&2
  exit 1
fi
"$AUTOPOSTS_PYTHON" - <<'PY'
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    ZoneInfo('America/Sao_Paulo')
except ZoneInfoNotFoundError:
    raise SystemExit('Instale tzdata para suportar os horários das campanhas.')

font_pairs = (
    (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')),
    (Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'), Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf')),
)
if not any(all(font.is_file() for font in pair) for pair in font_pairs):
    raise SystemExit('Instale fonts-dejavu-core para renderizar os vídeos.')
PY

if command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/autoposts-uv-cache}"
  export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
  if [[ ! -x .venv/bin/python ]]; then
    uv venv --python "$AUTOPOSTS_PYTHON" .venv
  fi
  uv pip sync --python .venv/bin/python requirements.txt
  uv pip check --python .venv/bin/python
else
  if [[ ! -x .venv/bin/python ]]; then
    "$AUTOPOSTS_PYTHON" -m venv .venv
  fi
  if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip --upgrade
  fi
  PIP_CACHE_DIR="${PIP_CACHE_DIR:-/tmp/autoposts-pip-cache}" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    .venv/bin/python -m pip install --requirement requirements.txt
  .venv/bin/python -m pip check
fi

printf '%s\n' 'Dependências prontas. Inicie com ./scripts/start.sh; valide com GET /health e .venv/bin/python -m pytest -q.'
