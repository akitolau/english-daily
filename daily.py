#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日自动出稿

逻辑：
1. 看今天是否已有帖子 → 有就直接退出（幂等，重复跑不会重样）
2. 从 wordbanks.json 里挑今天还没用过的词组组
3. 从口语题库 topics.json 里挑 3 道（2 小题 + 1 大题）
4. 组装成一条新 post，追加进 data/posts.json
5. 调 build.py 重建 index.html

用法：
  python3 daily.py            # 出今天
  python3 daily.py 2026-12-01 # 指定日期
"""

import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jdump(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    datetime.strptime(target, "%Y-%m-%d")

    posts_path = os.path.join(DATA, "posts.json")
    posts_doc = jload(posts_path)
    posts = posts_doc["posts"]

    if any(p["date"] == target for p in posts):
        print(f"SKIP: {target} 已有帖子")
        return 0

    wb = jload(os.path.join(DATA, "wordbanks.json"))
    topics = jload(os.path.join(DATA, "topics.json"))

    # ---- 选词组：优先挑没在近期用过的 ----
    used_recent = set()
    for p in posts[-6:]:
        used_recent.update(p.get("chunks", []))

    all_chunks = []
    for exam, block in wb.items():
        if exam.startswith("_"):
            continue
        for c in block["chunks"]:
            all_chunks.append((exam, c))

    fresh = [c for c in all_chunks if c[1]["id"] not in used_recent]
    pool = fresh if len(fresh) >= 1 else all_chunks

    # 用日期做种子：同一天跑到结果一样，不同天不一样
    seed = int(target.replace("-", ""))
    rnd = random.Random(seed)
    picked = rnd.choice(pool)
    chunk = picked[1]

    # ---- 选口语题 ----
    small = [q for q in topics["part1"] if q["id"] not in used_recent]
    big = [q for q in topics["part2"] + topics["part3"] if q["id"] not in used_recent]
    if len(small) < 2:
        small = topics["part1"]
    if not big:
        big = topics["part2"] + topics["part3"]

    rnd.shuffle(small)
    rnd.shuffle(big)
    speak = small[:2] + big[:1]
    rnd.shuffle(speak)

    # ---- 组装 ----
    post = {
        "date": target,
        "title": f"{chunk['topic']} · {topics['titles'][seed % len(topics['titles'])]}",
        "chunks": [chunk["id"]],
        "reading": {
            "source": f"{chunk['id']} passage",
            "why": chunk.get("readingWhy") or (
                f"这段覆盖今天全部 {len(chunk['words'])} 个词。读的时候别查字典——"
                f"先猜，读完再回头看词表，你会发现它们在句子里有了位置。"
            ),
        },
        "speaking": [
            {
                "part": q.get("part", "Part 1"),
                "q": q["q"],
                "ans": q["ans"],
                "note": q.get("note", ""),
                "swap": q.get("swap", ""),
            }
            for q in speak
        ],
        "wordtips": chunk.get("tip") or (
            f"今天这 {len(chunk['words'])} 个词里，优先掌握出现频率最高的那三四个；"
            f"其余的先做到「见到能认出来」，写作时自然会用上。"
        ),
    }

    posts.append(post)
    posts.sort(key=lambda p: p["date"])
    jdump(posts_path, posts_doc)
    print(f"OK: 已生成 {target} — {post['title']}")
    print(f"    词组组 {chunk['id']}（{len(chunk['words'])} 词）｜口语 {len(speak)} 道")

    # ---- 重建 ----
    r = subprocess.run([sys.executable, os.path.join(HERE, "build.py")],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print("BUILD FAILED:", r.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
