#!/usr/bin/env bash
# One-click launcher. The app window uses art/icon.png and art/cover.png.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
ICON="$ROOT/art/icon.png"
COVER="$ROOT/art/cover.png"
if [[ ! -f "$ICON" || ! -f "$COVER" ]]; then
  echo "DataCardForge needs art/icon.png and art/cover.png next to this launcher."
  exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$ROOT/requirements.txt"
echo "Using icon $ICON"
echo "Using cover $COVER"
(
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if python -c 'import socket; s=socket.create_connection(("127.0.0.1", 8767), 1); s.close()' 2>/dev/null; then
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:8767" >/dev/null 2>&1 || true
      fi
      exit 0
    fi
    sleep 0.25
  done
) &
exec python -m datacardforge
