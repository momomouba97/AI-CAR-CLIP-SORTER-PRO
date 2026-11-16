#!/usr/bin/env bash
# Usage: scripts/check_compatibility.sh [path-to-.app]  (default: dist/YouTube Downloader Studio.app)
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-dist/YouTube Downloader Studio.app}"
python3 scripts/check_macho.py "$TARGET" --min 11.0
