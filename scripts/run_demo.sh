#!/usr/bin/env bash
# Start the When Yah? API (port 8000) and web app (port 5173) together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
[ -d web/node_modules ] || (cd web && npm install)
python -m uvicorn api.main:app --port "$API_PORT" &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
cd web && npx vite --port "$WEB_PORT" --strictPort
