#!/bin/bash
# 英语每天 · 每日自动出稿并上线
# 由 Hermes cron 每天调用；也可手动跑：bash ~/Desktop/英语学习/publish.sh
set -uo pipefail

cd "$(dirname "$0")" || exit 1
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897

LOG="$HOME/Desktop/英语学习/.publish.log"
say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

say "=== 开始 ==="

# 1) 生成今天这一期（幂等：已有则跳过）
GEN=$(python3 daily.py 2>&1)
say "$GEN"
if echo "$GEN" | grep -q "SKIP"; then
  say "今天已有内容，不重复生成（仍检查是否需要推送）"
fi
if echo "$GEN" | grep -qi "BUILD FAILED\|Traceback"; then
  say "❌ 生成失败，中止"
  exit 1
fi

# 2) 有变更才提交
if git diff --quiet && git diff --cached --quiet; then
  say "无变更，跳过推送"
  say "=== 结束 ==="
  exit 0
fi

git add -A
git -c user.name="Akito" -c user.email="akitolau@users.noreply.github.com" \
    commit -q -m "每日更新：$(date '+%Y-%m-%d')" || say "（无新提交）"

# 3) 推送：网络不稳，重试 8 次
PUSHED=0
for i in $(seq 1 8); do
  if git -c http.proxy=http://127.0.0.1:7897 push origin main >/tmp/push_en.log 2>&1; then
    PUSHED=1
    say "✅ 推送成功（第 $i 次尝试）"
    break
  fi
  say "推送第 $i 次失败：$(tail -1 /tmp/push_en.log | cut -c1-80)"
  sleep 6
done

if [ "$PUSHED" -ne 1 ]; then
  say "❌ 推送最终失败，内容已本地提交，等下次重试"
  exit 1
fi

# 4) 线上验证
sleep 20
CODE=000
for i in 1 2 3 4 5; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 -x http://127.0.0.1:7897 \
         "https://akitolau.github.io/english-daily/?v=$(date +%s)")
  say "线上检查 $i：HTTP $CODE"
  if [ "$CODE" = "200" ]; then
    break
  fi
  sleep 15
done

say "=== 结束 ==="
