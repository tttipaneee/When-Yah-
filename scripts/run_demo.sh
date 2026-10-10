#!/usr/bin/env bash
# Start the When Yah? API (port 8000) and web app (port 3000) together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
PY="$(command -v python3 || command -v python)"   # macOS often has only python3
"$PY" -c "import fastapi, lightgbm" 2>/dev/null || "$PY" -m pip install -r requirements.txt
[ -d web/node_modules ] || (cd web && npm install)
echo "When Yah? -> open http://localhost:$WEB_PORT  (API docs: http://localhost:$API_PORT/docs)"
"$PY" -m uvicorn api.main:app --port "$API_PORT" &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
cd web && npx vite --port "$WEB_PORT" --strictPort
