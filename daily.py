#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日自动出稿 —— 从 10,000+ 词全量词库里按游标取词，永不重复。

逻辑：
1. 今天已有帖子 → 直接退出（幂等）
2. 全量词库按「优先级」排序（IELTS > TOEFL > GRE，多考试共有优先，短词优先）
3. 读 data/lexicon/daily.json 里的游标 cursor，往后取 10 个没用过的词
4. 用这 10 个词，让 DeepSeek 写一段把它们全串起来的英文文段 + 中文翻译
5. 从 topics.json 挑 3 道口语题（2 小题 + 1 大题）
6. 追加进 data/posts.json，重建站点

词库共 10,349 词，每天 10 个 → 可连续 1,034 天不重复。

用法：
  python3 daily.py                # 出今天
  python3 daily.py 2026-12-01     # 指定日期
  python3 daily.py --no-llm       # 跳过 AI 文段（用规则拼装）
"""

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LEX = os.path.join(DATA, "lexicon")
DAILY_STATE = os.path.join(LEX, "daily.json")
MASTER = os.path.join(LEX, "_master.json")
EXAMPLES = os.path.join(LEX, "examples.json")
ENV_FILE = os.path.expanduser("~/.hermes/.env")
API = "https://api.deepseek.com/chat/completions"

PER_DAY = 10


def jload(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jdump(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def load_key():
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    try:
        sys.path.insert(0, HERE)
        from enrich import load_key as _lk
        return _lk()
    except Exception:
        return None


def call_llm(key, prompt, max_tokens=1200, retries=3, temperature=0.85):
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            last = e
            time.sleep(2 * (a + 1))
    print("LLM 失败:", last)
    return None


# ---------------- 词库排序（决定每天先学哪些词） ----------------
def word_priority(w):
    exams = w.get("exams", [])
    rank = 0
    if "IELTS" in exams:
        rank += 100
    if "TOEFL" in exams:
        rank += 40
    if "GRE" in exams:
        rank += 10
    rank += len(exams) * 20          # 多考试共有 = 更核心
    return (-rank, len(w["w"]))


def clean_def(d):
    return re.sub(r"\s+", " ", str(d)).strip()


def build_word_entry(w, ex_pool):
    key = w["w"].lower()
    defs = []
    seen = set()
    for d in w.get("defs", []):
        c = clean_def(d)
        if c and c not in seen:
            seen.add(c)
            defs.append(c)
    e = ex_pool.get(key, {})
    return {
        "w": w["w"].strip(),
        "ipa": w.get("ipa", ""),
        "pos": w.get("pos", ""),
        "defs": defs,
        "ex": e.get("en", "") or w.get("ex", ""),
        "zh": e.get("zh", ""),
        "exams": w.get("exams", []),
    }


# ---------------- 生成每日文段 ----------------
def make_passage(key, words):
    """让模型把这 10 个词串成一段连贯的学术英文 + 中文翻译。带质量校验与重试。"""
    if not key:
        return None
    lines = []
    for w in words:
        lines.append(f"- {w['w']}: {w['defs'][0] if w['defs'] else ''}")
    prompt = (
        "You are an IELTS/TOEFL writing teacher. Write ONE connected academic paragraph "
        f"in English (110-160 words) that naturally uses ALL of these {len(words)} words:\n"
        + "\n".join(lines) +
        "\n\nRequirements:\n"
        "- One coherent topic (education / environment / technology / society / science), not a list of sentences.\n"
        "- Use each word EXACTLY ONCE — never repeat a target word. Do not repeat any target word in a different form.\n"
        "- Use each word in its natural exam-appropriate sense.\n"
        "- Academic register suitable for IELTS Writing Task 2.\n"
        "- Strictly 110-160 words total.\n"
        "- Bold each target word with **word** so a learner can spot it.\n\n"
        "Return ONLY this JSON, no fence:\n"
        '{"title":"a short Chinese topic name","topic":"one of: 教育/环境/科技/社会/科学/文化",'
        '"en":"the paragraph with **word** bolded","zh":"完整中文翻译"}\n'
    )

    best = None
    for attempt in range(3):
        raw = call_llm(key, prompt, max_tokens=1400,
                       temperature=0.85 + attempt * 0.05)
        if not raw:
            continue
        raw = re.sub(r"^```(?:json)?", "", raw.strip()).strip()
        raw = re.sub(r"```$", "", raw).strip()
        i, j = raw.find("{"), raw.rfind("}")
        if i < 0 or j < 0:
            continue
        try:
            d = json.loads(raw[i:j + 1])
        except Exception:
            continue
        if not d.get("en") or not d.get("zh"):
            continue
        ok, score = check_passage(d["en"], words)
        d["_score"] = score
        if best is None or score > best.get("_score", -1):
            best = d
        if ok:
            break
    if best:
        best.pop("_score", None)
    return best


def check_passage(en, words, lo=95, hi=210):
    """校验：每个目标词都出现、且基本不重复；长度在区间内。返回 (是否合格, 得分)"""
    score = 0
    ok = True
    wc = len(re.findall(r"[A-Za-z']+", en))
    if lo <= wc <= hi:
        score += 3
    else:
        score -= 2
    for w in words:
        root = w["w"].replace("**", "")
        hits = len(re.findall(r"\b" + re.escape(root) + r"[a-z]*", en, re.I))
        if hits == 0:
            score -= 5
            ok = False
        elif hits == 1:
            score += 3
        else:
            score += 1        # 重复扣分但不算硬失败

    return ok, score


def fallback_passage(words):
    """没有 LLM 时，用每个词自己的例句拼成一页（保证内容不缺）。"""
    parts = []
    for w in words:
        if w.get("ex"):
            parts.append(w["ex"])
    return {
        "title": words[0]["w"] + " 等词",
        "topic": "综合",
        "en": "  ".join(parts) if parts else "",
        "zh": "",
    }


# ---------------- 主流程 ----------------
def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_llm = "--no-llm" in sys.argv
    target = argv[0] if argv else date.today().isoformat()
    datetime.strptime(target, "%Y-%m-%d")

    posts_path = os.path.join(DATA, "posts.json")
    posts_doc = jload(posts_path, {"posts": []})
    posts = posts_doc["posts"]

    if any(p["date"] == target for p in posts):
        print(f"SKIP: {target} 已有帖子")
        return 0

    master = jload(MASTER)
    if not master:
        print("缺少 data/lexicon/_master.json")
        return 1
    ex_pool = jload(EXAMPLES, {})

    state = jload(DAILY_STATE, {"cursor": 0, "used": [], "days": []})
    ordered = sorted(master, key=word_priority)

    # 按游标取 10 个没用过的
    used = set(state.get("used", []))
    picked = []
    idx = state.get("cursor", 0)
    scan = 0
    while len(picked) < PER_DAY and scan < len(ordered):
        w = ordered[idx % len(ordered)]
        k = w["w"].lower()
        if k not in used:
            picked.append(build_word_entry(w, ex_pool))
            used.add(k)
        idx += 1
        scan += 1
    if len(picked) < PER_DAY:
        # 全集用完了（理论上 1000 天后），重置
        state["used"] = []
        used = set()
        idx = 0
        picked = []
        while len(picked) < PER_DAY:
            w = ordered[idx % len(ordered)]
            picked.append(build_word_entry(w, ex_pool))
            used.add(w["w"].lower())
            idx += 1

    # 生成文段
    key = None if no_llm else load_key()
    passage = None
    if key:
        passage = make_passage(key, picked)
    if not passage:
        passage = fallback_passage(picked)

    # 口语题
    topics = jload(os.path.join(DATA, "topics.json"), {})
    seed = int(target.replace("-", ""))
    rnd = random.Random(seed)
    recent_speak = set()
    for p in posts[-8:]:
        for s in p.get("speaking", []):
            recent_speak.add(s.get("q", ""))
    small = [q for q in topics.get("part1", []) if q["q"] not in recent_speak] or topics.get("part1", [])
    big = [q for q in topics.get("part2", []) + topics.get("part3", [])
           if q["q"] not in recent_speak] or (topics.get("part2", []) + topics.get("part3", []))
    rnd.shuffle(small)
    rnd.shuffle(big)
    speak = small[:2] + big[:1]
    rnd.shuffle(speak)

    chunk_id = f"d{target.replace('-', '')}"
    post = {
        "date": target,
        "title": f"{passage.get('topic', '综合')} · {passage.get('title', '')}",
        "chunks": [chunk_id],
        "words": picked,
        "reading": {
            "source": "每日词段",
            "en": passage.get("en", ""),
            "zh": passage.get("zh", ""),
            "why": (f"这段把你今天的 {len(picked)} 个词全串起来了。"
                    "读第一遍别查词——先按上下文猜；读完再看上面的词表，"
                    "你会发现这些词在句子里各自有了位置。"),
        },
        "speaking": [
            {"part": q.get("part", "Part 1"), "q": q["q"], "ans": q["ans"],
             "note": q.get("note", ""), "swap": q.get("swap", "")}
            for q in speak
        ],
        "wordtips": (f"今天这 {len(picked)} 个词里，"
                     f"{'、'.join(w['w'] for w in picked[:3])} 最值得先吃透；"
                     "其余的做到「见到能认出来」，写作时自然会想起来。"),
    }

    posts.append(post)
    posts.sort(key=lambda p: p["date"])
    jdump(posts_path, posts_doc)

    # 更新游标
    state["cursor"] = idx
    state["used"] = sorted(used)
    state.setdefault("days", []).append(target)
    jdump(DAILY_STATE, state)

    total = len(master)
    remaining = total - len(state["used"])
    print(f"OK: {target} — {post['title']}")
    print(f"    今日 {len(picked)} 词 | 游标 {idx} | 已用 {len(state['used'])}/{total}"
          f" | 还能 {remaining // PER_DAY} 天不重复")

    r = subprocess.run([sys.executable, os.path.join(HERE, "build.py")],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print("BUILD FAILED:", r.stderr[:500])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
