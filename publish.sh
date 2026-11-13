#!/bin/bash
# 英语每天 · 每日自动出稿并上线
# 手动跑：bash ~/Desktop/英语学习/publish.sh
#
# 注意：这台机器只有 8GB 内存，fork 容易失败。所以这里刻意只用
# python 一次调用做完「生成 + 构建」，把子进程数量压到最低。
set -uo pipefail

PROJ="$HOME/Desktop/英语学习"
cd "$PROJ" || exit 1
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897

LOG="$PROJ/.publish.log"

# 生成 + 构建都交给一个 python 进程做（daily.py 内部会调 build）
GEN=$(python3 daily.py 2>&1)
echo "$GEN" >> "$LOG"

if echo "$GEN" | grep -qi "BUILD FAILED\|Traceback"; then
  echo "❌ 失败" >> "$LOG"
  exit 1
fi

# 无变更就不推
if git diff --quiet -- . 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
  echo "无变更，跳过推送 $(date '+%F %T')" >> "$LOG"
  exit 0
fi

git add -A 2>/dev/null
git -c user.name="Akito" -c user.email="akitolau@users.noreply.github.com" \
    commit -q -m "每日更新 $(date '+%F')" 2>/dev/null

for i in 1 2 3 4 5 6; do
  if git -c http.proxy=http://127.0.0.1:7897 push origin main >/dev/null 2>&1; then
    echo "✅ 已上线 $(date '+%F %T') 第${i}次" >> "$LOG"
    exit 0
  fi
  sleep 5
done

echo "⚠️ 推送失败，本地已提交 $(date '+%F %T')" >> "$LOG"
exit 1
