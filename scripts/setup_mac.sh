#!/usr/bin/env bash
# Local developer setup on a Mac (Python 3.11 required).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3.11}"
"$PY" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
echo "Done. Run: source .venv/bin/activate && python main.py"
