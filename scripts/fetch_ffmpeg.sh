#!/usr/bin/env bash
# Download static Intel (x86_64) ffmpeg/ffprobe from evermeet.cx and verify their minimum macOS version.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="${FFMPEG_BASE_URL:-https://evermeet.cx/ffmpeg/getrelease}"
mkdir -p binaries
tmp="$(mktemp -d)"
for tool in ffmpeg ffprobe; do
  curl -fsSL --retry 3 -o "$tmp/$tool.zip" "$BASE/$tool/zip"
  unzip -oq "$tmp/$tool.zip" -d "$tmp"
  mv -f "$tmp/$tool" "binaries/$tool"
  chmod +x "binaries/$tool"
  shasum -a 256 "binaries/$tool"
done
./binaries/ffmpeg -version | head -1
python3 scripts/check_macho.py binaries --min 11.0 --verbose
