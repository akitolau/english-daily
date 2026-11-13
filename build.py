#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英语学习站构建脚本

数据源：
  data/wordbanks.json  词汇/词组库（IELTS / TOEFL / GRE）
  data/posts.json      每日帖子
  source/IELTS_2026_outline.md  雅思考纲（转成 HTML）

产物：index.html（单页应用，所有页面在同一文件里，靠 hash 路由切换）
"""

import json
import os
import re
import html as H
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(HERE, "source")
OUT = os.path.join(HERE, "index.html")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def esc(s):
    return H.escape(str(s))


# ---------------- Markdown → HTML（够用的最小实现） ----------------
def md_to_html(md):
    lines = md.split("\n")
    out = []
    in_table = False
    in_list = False
    in_code = False

    def inline(t):
        t = esc(t)
        # 行内代码
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        # 粗体
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        # 链接
        t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
        # 裸 URL
        t = re.sub(r"(?<![=\"'>])(https?://[^\s<）)]+)",
                   r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)
        return t

    for raw in lines:
        line = raw.rstrip()

        if line.startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre class='code'>")
                in_code = True
            continue
        if in_code:
            out.append(esc(line))
            continue

        # 表格
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # 分隔行
            if not in_table:
                out.append("<div class='tw'><table><thead>")
                out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>")
                out.append("</thead><tbody>")
                in_table = True
                continue
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        elif in_table:
            out.append("</tbody></table></div>")
            in_table = False

        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = len(m.group(1))
            out.append(f"<h{lvl+1}>{inline(m.group(2))}</h{lvl+1}>")
            continue

        if line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
            continue

        if re.match(r"^[-*]\s+", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            body = re.sub(r"^[-*]\s+", "", line)
            out.append("<li>" + inline(body) + "</li>")
            continue

        if re.match(r"^\d+\.\s+", line):
            if in_list:
                out.append("</ul>")
                in_list = False
            body = re.sub(r"^\d+\.\s+", "", line)
            out.append("<li class='ol'>" + inline(body) + "</li>")
            continue

        if line.strip() == "---":
            out.append("<hr>")
            continue

        out.append(f"<p>{inline(line)}</p>")

    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</tbody></table></div>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


# ---------------- 数据整形 ----------------
def build_chunk_index(wb):
    idx = {}
    for exam, block in wb.items():
        if exam.startswith("_"):
            continue
        for c in block["chunks"]:
            idx[c["id"]] = {**c, "exam": exam, "examLabel": block["label"]}
    return idx


def render_words_table(chunk):
    rows = []
    for i, w in enumerate(chunk["words"], 1):
        rows.append(
            f"<tr><td class='num'>{i}</td>"
            f"<td class='w'>{esc(w['w'])}</td>"
            f"<td class='pos'>{esc(w['pos'])}</td>"
            f"<td class='cn'>{esc(w['cn'])}</td>"
            f"<td class='note'>{esc(w['note'])}</td></tr>"
        )
    return (
        "<div class='tw'><table class='wt'><thead><tr>"
        "<th>#</th><th>词组 / 单词</th><th>词性</th><th>中文</th><th>用法提示</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def render_passage(p):
    return f"""
<div class="passage">
  <div class="p-en">{''.join(f'<p>{esc(par)}</p>' for par in p['en'].split(chr(10)+chr(10)))}</div>
  <details class="p-cn"><summary>中文翻译 <span>读完全文再展开</span></summary>
    <div class="p-cn-body">{''.join(f'<p>{esc(par)}</p>' for par in p['cn'].split(chr(10)+chr(10)))}</div>
  </details>
  {'<div class="p-note">💡 ' + esc(p["note"]) + '</div>' if p.get('note') else ''}
</div>"""


def render_speaking(sp):
    return f"""
<div class="speak">
  <div class="sp-head"><span class="sp-part">{esc(sp['part'])}</span></div>
  <div class="sp-q">{esc(sp['q'])}</div>
  <div class="sp-ans">{''.join(f'<p>{esc(par)}</p>' for par in sp['ans'].split(chr(10)+chr(10)))}</div>
  <div class="sp-foot">
    <div class="sp-note"><b>答题思路</b>{esc(sp['note'])}</div>
    {'<div class="sp-swap"><b>换成你的情况</b>' + esc(sp['swap']) + '</div>' if sp.get('swap') else ''}
  </div>
</div>"""


def render_daily_words(words):
    """渲染 daily.py 生成的 10 词表（每行带独立例句）"""
    if not words:
        return ""
    rows = []
    for i, w in enumerate(words):
        tags = "".join(f'<span class="lex-tag {x}">{x}</span>' for x in w.get("exams", []))
        d = w["defs"][0] if w.get("defs") else ""
        pos = f'<span class="pos">{esc(w["pos"])}</span>' if w.get("pos") else ""
        ipa = f'<span class="lex-ipa">/{esc(w["ipa"])}/</span>' if w.get("ipa") else ""
        rows.append(
            f'<div class="dw">'
            f'<div class="dw-n">{i+1:02d}</div>'
            f'<div class="dw-main">'
            f'<div class="dw-w">{esc(w["w"])}{ipa}</div>'
            f'<div class="lex-tags">{tags}</div></div>'
            f'<div class="dw-body"><div class="lex-def">{pos}{esc(d)}</div>'
            + (f'<div class="lex-ex">{esc(w["ex"])}'
               + (f'<span class="zh">{esc(w["zh"])}</span>' if w.get("zh") else "")
               + '</div>' if w.get("ex") else "")
            + '</div></div>'
        )
    return '<div class="dailywords">' + "".join(rows) + "</div>"


def render_daily_passage(reading):
    """渲染 daily.py 生成的文段（en + zh 折叠）"""
    en = reading.get("en", "")
    zh = reading.get("zh", "")
    if not en:
        return ""
    paras = "".join(f"<p>{esc(p)}</p>" for p in en.split("\n\n") if p.strip())
    # 把 **word** 转成高亮
    def bold(html_frag):
        return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", html_frag)
    paras = bold(paras)
    zh_html = ""
    if zh:
        zh_paras = "".join(f"<p>{esc(p)}</p>" for p in zh.split("\n\n") if p.strip())
        zh_html = ('<details class="p-cn"><summary>中文翻译 <span>读完全文再展开</span></summary>'
                   f'<div class="p-cn-body">{zh_paras}</div></details>')
    return f'<div class="passage"><div class="p-en">{paras}</div>{zh_html}</div>'


def render_post(post, chunk_idx):
    chunks = [chunk_idx[c] for c in post["chunks"] if c in chunk_idx]
    date_obj = datetime.strptime(post["date"], "%Y-%m-%d")
    wd = "一二三四五六日"[date_obj.weekday()]

    # 词组：优先用 post 自带的 daily words，否则回退到 chunks
    if post.get("words"):
        words_html = render_daily_words(post["words"])
    else:
        words_html = ""
        for c in chunks:
            words_html += (
                f'<div class="chunk"><div class="chunk-h">'
                f'<span class="chunk-topic">{esc(c["topic"])}</span>'
                f'<span class="chunk-exam">{esc(c["examLabel"])}</span></div>'
                + render_words_table(c) + "</div>"
            )

    # 阅读：优先用 reading.en / zh
    if post.get("reading", {}).get("en"):
        reading_html = (
            f'<div class="chunk"><div class="chunk-h">'
            f'<span class="chunk-topic">阅读 Reading</span></div>'
            f'<div class="p-why">{esc(post["reading"].get("why",""))}</div>'
            + render_daily_passage(post["reading"]) + "</div>"
        )
    else:
        reading_html = "".join(
            f'<div class="chunk"><div class="chunk-h">'
            f'<span class="chunk-topic">阅读 Reading</span></div>'
            f'<div class="p-why">{esc(post["reading"]["why"])}</div>'
            + render_passage(c["passage"]) + "</div>"
            for c in chunks if c.get("passage")
        )

    speaking_html = "".join(render_speaking(s) for s in post["speaking"])

    return f"""
<article class="post" id="post-{post['date']}">
  <header class="post-h">
    <div class="post-date">
      <span class="pd-day">{date_obj.strftime('%m.%d')}</span>
      <span class="pd-wd">周{wd} · {date_obj.year}</span>
    </div>
    <h2 class="post-t">{esc(post['title'])}</h2>
  </header>

  <section class="sec">
    <div class="sec-h"><span class="sec-n">01</span><h3>今日词组 · 10 个</h3>
      <span class="sec-note">先读下面的文段，再回来对词</span></div>
    {words_html}
    <div class="tip">{esc(post.get('wordtips',''))}</div>
  </section>

  <section class="sec">
    <div class="sec-h"><span class="sec-n">02</span><h3>今日阅读</h3>
      <span class="sec-note">目标不是查字典，是读完能复述</span></div>
    {reading_html}
  </section>

  <section class="sec">
    <div class="sec-h"><span class="sec-n">03</span><h3>今日口语 · 3 题</h3>
      <span class="sec-note">先自己说一遍，再看参考答案</span></div>
    {speaking_html}
  </section>
</article>
"""


# ---------------- 页面组装 ----------------
def main():
    wb = load("wordbanks.json")
    posts = load("posts.json")["posts"]
    chunk_idx = build_chunk_index(wb)
    posts_sorted = sorted(posts, key=lambda p: p["date"], reverse=True)

    # --- 每日页 ---
    posts_html = "".join(render_post(p, chunk_idx) for p in posts_sorted)

    # --- 词库页：按考试分组 ---
    bank_html = ""
    for exam, block in wb.items():
        if exam.startswith("_"):
            continue
        bank_html += f"""
<section class="bank">
  <div class="bank-h"><h2>{esc(block['label'])}</h2>
    <span class="bank-count">{len(block['chunks'])} 组 · {sum(len(c['words']) for c in block['chunks'])} 词</span></div>
  <p class="bank-desc">{esc(block['desc'])}</p>
"""
        for c in block["chunks"]:
            bank_html += f"""
  <div class="chunk">
    <div class="chunk-h"><span class="chunk-topic">{esc(c['topic'])}</span>
      <span class="chunk-exam">{len(c['words'])} 词</span></div>
    {render_words_table(c)}
    {render_passage(c['passage']) if c.get('passage') else ''}
  </div>"""
        bank_html += "</section>"

    # --- 考纲页 ---
    outline_md = open(os.path.join(SRC, "IELTS_2026_outline.md"), encoding="utf-8").read()
    outline_html = md_to_html(outline_md)

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()

    latest = posts_sorted[0]["date"]
    total_words = sum(
        len(c["words"])
        for exam, block in wb.items() if not exam.startswith("_")
        for c in block["chunks"]
    )
    total_chunks = sum(
        len(block["chunks"]) for exam, block in wb.items() if not exam.startswith("_")
    )
    total_speak = sum(len(p["speaking"]) for p in posts)

    out = (tpl.replace("{{POSTS}}", posts_html)
              .replace("{{BANK}}", bank_html)
              .replace("{{OUTLINE}}", outline_html)
              .replace("{{POST_COUNT}}", str(len(posts)))
              .replace("{{WORD_COUNT}}", str(total_words))
              .replace("{{CHUNK_COUNT}}", str(total_chunks))
              .replace("{{SPEAK_COUNT}}", str(total_speak))
              .replace("{{LATEST}}", latest)
              .replace("{{BUILD_DATE}}", date.today().isoformat()))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)

    print(f"OK -> {OUT}")
    print(f"   帖子 {len(posts)} 期 | 最近 {latest} | 词组 {total_chunks} 组 / {total_words} 词 | 口语题 {total_speak} 道")
    print(f"   大小 {len(out)/1024:.0f} KB")


if __name__ == "__main__":
    main()
