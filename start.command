#!/bin/bash
# Kil Capital Terminal launcher. Double-click in Finder.
# Finds Python 3.12+, creates .venv, installs requirements, starts the server on 127.0.0.1:8000
# and opens the browser. Recommend-only: it never connects to a Kalshi account and needs no keys.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.12+ not found. Install it from https://www.python.org/downloads/macos/ and double-click again."
  read -r -p "Press Return to close." _; exit 1
fi

if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt


PORT="${KIL_PORT:-8000}"
( sleep 2; open "http://127.0.0.1:${PORT}" ) &
exec python -m kil_capital.api.app
