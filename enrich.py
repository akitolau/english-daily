#!/usr/bin/env python3
"""
enrich.py — 给词库补充例句（英文 + 中文），供"在文段里记"使用。

用法:
  python3 enrich.py --batch 40            # 补 40 个还没有例句的词
  python3 enrich.py --batch 40 --exam IELTS
  python3 enrich.py --status              # 看进度

输出: data/lexicon/examples.json   (word -> {en, zh})
设计:
  - 幂等：已有例句的词不会重复生成
  - 断点续跑：随时中断，下次接着来
  - 优先级：IELTS > TOEFL > GRE，且越"高频/基础"越先（按考试标签数倒序）
"""
import json, os, sys, time, urllib.request, argparse, re

ROOT = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(ROOT, 'data', 'lexicon')
MASTER = os.path.join(LEX, '_master.json')
POOL = os.path.join(LEX, 'examples.json')
ENV_FILE = os.path.expanduser('~/.hermes/.env')
API = 'https://api.deepseek.com/chat/completions'


def load_key():
    if os.environ.get('DEEPSEEK_API_KEY'):
        return os.environ['DEEPSEEK_API_KEY']
    try:
        for line in open(ENV_FILE):
            line = line.strip()
            if line.startswith('DEEPSEEK_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def load_pool():
    if os.path.exists(POOL):
        with open(POOL, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_pool(p):
    tmp = POOL + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=0)
    os.replace(tmp, POOL)


def clean_def(defs):
    """取最干净的一条中文释义"""
    for d in defs:
        d = re.sub(r'\s+', ' ', d).strip()
        if d:
            return d[:70]
    return ''


def build_prompt(words):
    lines = []
    for w in words:
        lines.append(f"- {w['w']}  ({clean_def(w['defs'])})")
    return (
        "You are an IELTS/TOEFL/GRE vocabulary teacher writing study material for a Chinese learner.\n"
        "For EACH word below, write ONE natural English sentence (12-22 words) that:\n"
        "1. uses the word in its most common exam-appropriate sense;\n"
        "2. sounds like real IELTS/TOEFL/GRE reading or writing, not a textbook cliché;\n"
        "3. gives enough context that a learner can infer the meaning;\n"
        "4. uses varied academic topics (environment, technology, education, society, science, culture).\n"
        "Then give a natural Chinese translation of that sentence.\n\n"
        "WORD LIST:\n" + "\n".join(lines) + "\n\n"
        "Return ONLY a JSON array, no markdown fence, no commentary:\n"
        '[{"word":"...","en":"...","zh":"..."}, ...]\n'
        "One object per word, in the same order. Use the exact word spelling given."
    )


def call_api(key, prompt, retries=3):
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "temperature": 0.8,
    }
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
            return data['choices'][0]['message']['content'], data.get('usage', {})
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last if last else RuntimeError('API 调用失败')


def parse_json_array(text):
    """解析 JSON 数组；如果被 max_tokens 截断，尽量抢救出完整的对象。"""
    text = text.strip()
    text = re.sub(r'^```(?:json)?', '', text).strip()
    text = re.sub(r'```$', '', text).strip()
    i = text.find('[')
    if i < 0:
        return []
    body = text[i:]
    # 先试完整解析
    j = body.rfind(']')
    if j > 0:
        try:
            return json.loads(body[:j + 1])
        except Exception:
            pass
    # 截断抢救：逐个取出完整的 {...} 对象
    out = []
    depth = 0
    start = None
    in_str = False
    esc = False
    for idx, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            if depth == 0:
                start = idx
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                frag = body[start:idx + 1]
                try:
                    out.append(json.loads(frag))
                except Exception:
                    pass
                start = None
    return out


def priority_key(w):
    # 多考试共有 > IELTS 专有 > TOEFL > GRE；同学历内短词优先（更基础）
    exams = w.get('exams', [])
    rank = 0
    if 'IELTS' in exams:
        rank += 100
    if 'TOEFL' in exams:
        rank += 40
    if 'GRE' in exams:
        rank += 10
    rank += len(exams) * 15
    return (-rank, len(w['w']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', type=int, default=60)
    ap.add_argument('--exam', default=None)
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args()

    with open(MASTER, encoding='utf-8') as f:
        master = json.load(f)
    pool = load_pool()

    if args.status:
        have = len(pool)
        total = len(master)
        print(f'例句进度: {have}/{total}  ({have*100//total}%)')
        by = {}
        for w in master:
            for e in w['exams']:
                by.setdefault(e, [0, 0])
                by[e][1] += 1
                if w['w'].lower() in pool:
                    by[e][0] += 1
        for e, (h, t) in sorted(by.items()):
            print(f'  {e:6s} {h:5d}/{t:5d}')
        return

    todo = [w for w in master if w['w'].lower() not in pool]
    if args.exam:
        todo = [w for w in todo if args.exam in w['exams']]
    todo.sort(key=priority_key)
    todo = todo[:args.batch]
    if not todo:
        print('没有待补充的词了 🎉')
        return

    key = load_key()
    if not key:
        print('缺少 DEEPSEEK_API_KEY')
        sys.exit(1)

    print(f'本次生成 {len(todo)} 个词…')
    prompt = build_prompt(todo)
    raw, usage = call_api(key, prompt)
    items = parse_json_array(raw)

    added = 0
    want = {w['w'].lower() for w in todo}
    for it in items:
        wd = (it.get('word') or '').strip().lower()
        en = (it.get('en') or '').strip()
        zh = (it.get('zh') or '').strip()
        if not wd or not en or not zh:
            continue
        if wd not in want:
            continue
        pool[wd] = {'en': en, 'zh': zh}
        added += 1

    save_pool(pool)
    print(f'✅ 新增 {added} 条例句 | tokens={usage.get("total_tokens")} | 累计 {len(pool)}/{len(master)}')


if __name__ == '__main__':
    main()
