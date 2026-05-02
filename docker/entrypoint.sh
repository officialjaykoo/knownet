#!/bin/sh
set -eu

mkdir -p "$DATA_DIR" "$DATA_DIR/backups" "$DATA_DIR/pages" "$DATA_DIR/tmp" "$DATA_DIR/logs"

cd /app/apps/api
uvicorn knownet_api.main:app --host 127.0.0.1 --port 8000 > "$DATA_DIR/logs/api.log" 2>&1 &
api_pid="$!"

cd /app/apps/web
npm run start -- --hostname 0.0.0.0 --port 3000 > "$DATA_DIR/logs/web.log" 2>&1 &
web_pid="$!"

term_handler() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}

trap term_handler INT TERM

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 2
done

term_handler
exit 1
