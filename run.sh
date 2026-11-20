#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is required. Install FFmpeg and add it to PATH, then run this script again."
  exit 1
fi
[ -f .env ] || cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
