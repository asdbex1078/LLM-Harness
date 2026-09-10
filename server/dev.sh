#!/usr/bin/env bash
# 启动本地服务：./server/dev.sh [端口]
# vault 默认取仓库根目录，可用 KNOWRARY_VAULT 覆盖。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8765}"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "缺少 .venv：python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt"; exit 1; }
export KNOWRARY_VAULT="${KNOWRARY_VAULT:-$REPO}"
echo "vault = $KNOWRARY_VAULT"
echo "打开 http://127.0.0.1:$PORT/  （前端产物 web/dist；开发前端用 cd web && npm run dev）"
exec "$PY" -m uvicorn server.app:app --host 127.0.0.1 --port "$PORT" --reload --app-dir "$REPO"
