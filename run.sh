#!/usr/bin/env bash
# Build the UI if needed, then serve API + UI on one port.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

# The web API needs Python 3.10+: FastAPI's models are evaluated by Pydantic at
# runtime, and `str | None` annotations are a syntax error before 3.10. macOS
# still ships 3.9 as `python3`, so pick a suitable interpreter rather than
# assuming the default one works. Override with PYTHON=/path/to/python.
find_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      echo "$candidate"; return
    fi
  done
  return 1
}

if [ ! -d .venv ]; then
  PY=$(find_python) || {
    echo "error: Python 3.10 or newer is required (found $(python3 -V 2>&1))." >&2
    echo "       Install it, or point PYTHON at one:  PYTHON=/path/to/python3.12 ./run.sh" >&2
    exit 1
  }
  echo "Creating virtualenv with $("$PY" -V)…"
  "$PY" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

# An existing venv built with an older Python fails later and less clearly, so
# check it up front.
if ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "error: .venv uses $(.venv/bin/python -V 2>&1), but 3.10+ is required." >&2
  echo "       Remove it and re-run:  rm -rf .venv && ./run.sh" >&2
  exit 1
fi

if [ ! -d ui/node_modules ]; then
  echo "Installing UI dependencies…"
  (cd ui && npm install --silent)
fi

if [ ! -d ui/dist ] || [ -n "$(find ui/src ui/index.html -newer ui/dist/index.html 2>/dev/null)" ]; then
  echo "Building UI…"
  (cd ui && npm run build)
fi

echo "→ http://localhost:${PORT}"
exec .venv/bin/python -m uvicorn videogen.api:app --port "${PORT}"
