#!/usr/bin/env bash
# Day-Info 提交助手：git add day-info + 提交 +（有凭证则）推送。
# 用法：bash day-info/scripts/publish.sh "提交信息"
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
MSG="${1:-day-info: 更新 $(date +%F)}"

git add day-info
if git diff --cached --quiet; then
  echo "== 无变更需要提交 =="
else
  git commit -q -m "$MSG"
  echo "== 已本地提交：$(git log -1 --format='%h %s') =="
fi

CREDS="${KNOWRARY_DAYINFO_CREDS:-/root/.openclaw-autoclaw/workspace/.secrets/git-credentials}"
if [ -s "$CREDS" ]; then
  if GIT_TERMINAL_PROMPT=0 timeout 90 git push -q origin day-info-for-autoclaw 2>/dev/null; then
    echo "== 已推送 origin/day-info-for-autoclaw =="
  else
    echo "== 推送未成功（保留本地提交，下次再试）=="
  fi
else
  echo "== 未配置推送凭证：已本地提交，待配置后自动推送 =="
fi
