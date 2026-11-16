#!/bin/bash
# تشغيل مباشر بدون GitHub (يتطلب Python 3.10+ من python.org)
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "❌ يلزم Python 3.10 أو أحدث. نزّله من https://www.python.org/downloads/macos/ ثم أعد التشغيل."
  read -n 1 -s -r -p "اضغط أي زر للإغلاق"; exit 1
fi

[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

mkdir -p bin
if [ ! -x bin/deno ]; then
  echo "⬇️ تنزيل deno (مرة واحدة)…"
  curl -fsSL -o bin/deno.zip "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-apple-darwin.zip" \
    && unzip -oq bin/deno.zip -d bin && chmod +x bin/deno && rm -f bin/deno.zip
fi
export PATH="$PWD/bin:$PATH"

python app.py
