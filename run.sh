#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f backend/.env ]; then
  echo "backend/.env is missing. Copy backend/.env.example to backend/.env and add GEMINI_API_KEY."
  exit 1
fi

( cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000 ) &
BACK=$!
trap 'kill $BACK 2>/dev/null || true' EXIT
( cd frontend && npm run dev )
