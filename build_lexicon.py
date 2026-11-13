#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_lexicon.py — 把 10,352 词的 master 词库切成分册 JSON，供前端按需加载。

产物 (data/lexicon/):
  index.json        —— 分册清单 + 每个分册的词数/考试分布 + 全书统计
  vol_a.json ...    —— 按首字母分册，每册含该字母下全部词条
  daily.json        —— 每日 10 词的排期（持久化，只增不减）

单词条目字段：
  w     单词
  ipa   音标（可能为空）
  pos   词性（可能为空）
  defs  中文释义数组（去重后可能多条，取第一条为主）
  ex    英文例句（来自 examples.json）
  zh    例句中文翻译
  exams 所属考试 ["IELTS","TOEFL","GRE"]
"""
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, 'data', 'lexicon')
MASTER = os.path.join(LEX, '_master.json')
EXAMPLES = os.path.join(LEX, 'examples.json')
OUT_INDEX = os.path.join(LEX, 'index.json')

EXAM_META = {
    'IELTS': {'label': '雅思 IELTS', 'color': '#2f6f5e'},
    'TOEFL': {'label': '托福 TOEFL', 'color': '#8a5a2b'},
    'GRE':   {'label': 'GRE', 'color': '#5b4a7a'},
}


def clean_def(d):
    d = re.sub(r'\s+', ' ', str(d)).strip()
    return d


def main():
    master = json.load(open(MASTER, encoding='utf-8'))
    ex = json.load(open(EXAMPLES, encoding='utf-8')) if os.path.exists(EXAMPLES) else {}

    words = []
    for w in master:
        key = w['w'].lower()
        defs = []
        seen = set()
        for d in w.get('defs', []):
            c = clean_def(d)
            if c and c not in seen:
                seen.add(c)
                defs.append(c)
        if not defs:
            continue
        e = ex.get(key, {})
        words.append({
            'w': w['w'].strip(),
            'ipa': w.get('ipa', ''),
            'pos': w.get('pos', ''),
            'defs': defs,
            'ex': e.get('en', '') or w.get('ex', ''),
            'zh': e.get('zh', ''),
            'exams': w.get('exams', []),
        })

    # 按首字母分册
    vols = {}
    for w in words:
        c = w['w'][0].lower()
        if not c.isalpha():
            c = 'other'
        vols.setdefault(c, []).append(w)

    index = {'vols': [], 'total': len(words), 'exams': {}, 'updated': date.today().isoformat()}
    for e in ('IELTS', 'TOEFL', 'GRE'):
        index['exams'][e] = sum(1 for w in words if e in w['exams'])
    index['exams']['multi'] = sum(1 for w in words if len(w['exams']) > 1)
    index['exams']['all3'] = sum(1 for w in words if len(w['exams']) == 3)

    for c in sorted(vols):
        items = sorted(vols[c], key=lambda x: x['w'].lower())
        fn = f'vol_{c}.json'
        with open(os.path.join(LEX, fn), 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, separators=(',', ':'))
        index['vols'].append({'key': c, 'file': fn, 'count': len(items)})

    with open(OUT_INDEX, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    print(f'词库分册: {len(index["vols"])} 册, 共 {index["total"]} 词')
    print(f'  雅思 {index["exams"]["IELTS"]} / 托福 {index["exams"]["TOEFL"]} / GRE {index["exams"]["GRE"]}')
    print(f'  同时属于 3 个考试: {index["exams"]["all3"]} 词')
    have_ex = sum(1 for w in words if w['ex'])
    print(f'  带例句: {have_ex}/{index["total"]} ({have_ex*100//index["total"]}%)')


if __name__ == '__main__':
    main()
