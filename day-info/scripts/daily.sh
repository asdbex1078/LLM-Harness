#!/usr/bin/env bash
# Day-Info 每日收集：采集入池 + 本地提交 +（凭证/密钥就绪时）推送。
# 供「Day-Info 每日收集（静默入池）」定时任务调用；也可手动执行。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

python3 day-info/scripts/collect.py --repo-dir "$ROOT"
bash day-info/scripts/publish.sh "day-info: 收集池 $(date +%F)"
