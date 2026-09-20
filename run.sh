#!/usr/bin/env bash
# Starts both halves of ContractLens. Ctrl-C stops both.
set -e
cd "$(dirname "$0")"

if [ ! -f backend/.env ]; then
  echo "backend/.env is missing. Copy backend/.env.example and add your ANTHROPIC_API_KEY."
  exit 1
fi

( cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000 ) &
BACK=$!
trap "kill $BACK 2>/dev/null" EXIT
( cd frontend && npm run dev )
