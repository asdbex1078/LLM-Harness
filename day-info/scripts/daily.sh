#!/usr/bin/env bash
# Day-Info 每日收集：采集入池 + 本地提交（有推送凭证则推送）。
# 供「Day-Info 每日收集（静默入池）」定时任务调用；也可手动执行。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

python3 day-info/scripts/collect.py --repo-dir "$ROOT"

git add day-info
if git diff --cached --quiet; then
  echo "== 无变更需要提交 =="
else
  git commit -q -m "day-info: 收集池 $(date +%F)"
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
