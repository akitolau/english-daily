#!/bin/bash
# 每日增量：补 30 个词的例句 + 出今天一期帖子 + 重建 + 推送
# 设计：慢速稳定，每天只推进一小步，词库靠日积月累长起来
cd "$(dirname "$0")" || exit 1

LOG=".publish.log"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 开始 =====" >> "$LOG"

# 1) 补 30 个词的例句（断点续跑，已有的自动跳过）
python3 enrich.py --batch 30 >> "$LOG" 2>&1

# 2) 重新切分册（把新例句带进去）
python3 build_lexicon.py >> "$LOG" 2>&1

# 3) 出今天这一期（幂等，已出过就跳过）
python3 daily.py >> "$LOG" 2>&1

# 4) 推送
git add -A >> "$LOG" 2>&1
if git diff --cached --quiet; then
  echo "无改动，跳过推送" >> "$LOG"
else
  git commit -m "daily: $(date '+%Y-%m-%d') 更新" >> "$LOG" 2>&1
  for i in 1 2 3 4 5; do
    if git push origin main >> "$LOG" 2>&1; then
      echo "推送成功（第 $i 次）" >> "$LOG"
      break
    fi
    echo "推送失败，第 $i 次重试…" >> "$LOG"
    sleep 5
  done
fi

echo "===== $(date '+%H:%M:%S') 结束 =====" >> "$LOG"
