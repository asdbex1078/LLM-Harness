#!/usr/bin/env bash
# Day-Info 提交助手：git add day-info + 提交 + 推送（HTTPS 凭证 → SSH 双通道自动切换）。
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
SSH_URL="git@github.com:asdbex1078/Knowrary.git"

# 通道 1：HTTPS + 凭证文件（PAT）
if [ -s "$CREDS" ]; then
  git config credential.helper "store --file=$CREDS"
  if GIT_TERMINAL_PROMPT=0 timeout 90 git push -q origin day-info-for-autoclaw 2>/dev/null; then
    echo "== 已推送 origin/day-info-for-autoclaw（HTTPS） =="
    exit 0
  fi
  echo "== HTTPS 推送未成功，改试 SSH… =="
else
  echo "== 未配置 HTTPS 凭证，尝试 SSH… =="
fi

# 通道 2：SSH + Deploy Key（~/.ssh/config 指向 ssh.github.com:443 + 专用密钥）
if [ -f /root/.openclaw-autoclaw/workspace/.secrets/github_deploy_key ]; then
  if GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=20" timeout 90 git push -q "$SSH_URL" day-info-for-autoclaw 2>/dev/null; then
    echo "== 已推送 origin/day-info-for-autoclaw（SSH） =="
    exit 0
  fi
fi

echo "== 推送未成功（已保留本地提交，下次自动重试）。检查：A) PAT 写入 .secrets/git-credentials；或 B) Deploy Key 已添加到 GitHub 并启用写权限 =="
exit 0
