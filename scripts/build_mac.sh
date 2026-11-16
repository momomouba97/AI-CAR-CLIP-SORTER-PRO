#!/usr/bin/env bash
# Build "dist/YouTube Downloader Studio.app" (Intel x86_64, macOS 11+). Run inside the venv.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(uname -s)" = "Darwin" ] || { echo "This script must run on macOS."; exit 1; }
export MACOSX_DEPLOYMENT_TARGET=11.0
APP="dist/YouTube Downloader Studio.app"

if [ ! -f resources/app.icns ]; then
  ICONSET="$(mktemp -d)/app.iconset"; mkdir -p "$ICONSET"
  for s in 16 32 64 128 256 512; do
    sips -z $s $s resources/logo.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2))
    sips -z $d $d resources/logo.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o resources/app.icns
fi

rm -rf build dist
python -m PyInstaller --noconfirm --clean YouTubeDownloaderStudio.spec

# PyInstaller ad-hoc signs; verify (Intel Macs do not require a signature, so this is advisory).
codesign --verify --deep --strict "$APP" || echo "WARNING: codesign verification reported a problem"

python scripts/check_macho.py "$APP" --min 11.0
echo "Built: $APP"
