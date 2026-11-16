#!/usr/bin/env bash
# Create dist/YouTube-Downloader-Studio.dmg from the built .app and verify it.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:-dist/YouTube Downloader Studio.app}"
OUT="${2:-dist/YouTube-Downloader-Studio.dmg}"
VOL="YouTube Downloader Studio"
[ -d "$APP" ] || { echo "App not found: $APP (run scripts/build_mac.sh first)"; exit 1; }

STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp packaging/INSTALL.txt "$STAGE/INSTALL.txt"

rm -f "$OUT"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$OUT"
hdiutil verify "$OUT"

# Mount it and re-check the app that is actually inside the image.
MNT="$(mktemp -d)"
hdiutil attach "$OUT" -nobrowse -readonly -mountpoint "$MNT" >/dev/null
trap 'hdiutil detach "$MNT" -quiet || true' EXIT
ls -la "$MNT"
python3 scripts/check_macho.py "$MNT/YouTube Downloader Studio.app" --min 11.0
echo "Created: $OUT ($(du -h "$OUT" | cut -f1))"
