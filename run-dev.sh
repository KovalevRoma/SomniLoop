#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  echo "Run ./install.sh first."
  exit 1
fi
exec "$PROJECT_DIR/.venv/bin/python" -m somniloop

