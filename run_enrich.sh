#!/bin/bash
# 批量生成全部词库例句（后台跑，可中断续跑）
cd "$(dirname "$0")" || exit 1
TOTAL=$(python3 -c "import json;print(len(json.load(open('data/lexicon/_master.json'))))")
while :; do
  DONE=$(python3 -c "import json,os;p='data/lexicon/examples.json';print(len(json.load(open(p))) if os.path.exists(p) else 0)")
  if [ "$DONE" -ge "$TOTAL" ]; then echo "ALL DONE $DONE/$TOTAL"; break; fi
  python3 enrich.py --batch 100 >> .enrich.log 2>&1
  code=$?
  if [ $code -ne 0 ]; then echo "$(date '+%H:%M:%S') batch failed code=$code" >> .enrich.log; sleep 10; fi
  sleep 1
done
echo "FINISHED $(date)" >> .enrich.log
