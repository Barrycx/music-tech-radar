#!/usr/bin/env python3
"""渲染站点全部页面:模板 + issue.json + archive.json → index.html / issues/vol-NNN.html / archive.html。

流程:先把当期内容并入存档(不变量:旧条目全部保留、按 URL 去重、
保留最近 90 天且 items ≤ 400 删最旧),写回 archive.json;
再渲染三类页面:
- index.html          最新期(BASE=`.`,往期链接 archive.html)
- issues/vol-NNN.html 存档里每一期各一份(BASE=`..`,往期链接 ../archive.html)
- archive.html        往期索引页(页内 JS fetch 同目录 archive.json 渲染)

期号:--vol 参数,或自动 = 存档最大 vol + 1。
出版日期:--date 参数,或北京时间今天(Asia/Shanghai)。
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template" / "page.html"
ARCH_TEMPLATE = ROOT / "template" / "archive.html"
ARCHIVE = ROOT / "archive.json"
ISSUE = ROOT / "build" / "issue.json"
OUT = ROOT / "index.html"
OUT_ISSUES = ROOT / "issues"
OUT_ARCHIVE = ROOT / "archive.html"
TZ = ZoneInfo("Asia/Shanghai")

WEEKDAYS = "一二三四五六日"
DIFF = {"入门": "▮▯▯", "进阶": "▮▮▯", "硬核": "▮▮▮"}
ITEM_FIELDS = ("vol", "pub", "date", "sec", "tag", "title", "url", "src",
               "orig", "why", "hot", "detail")


def esc(s):
    """正文文本转义(保留引号字面量,与 vol001 一致)。"""
    return html.escape(str(s), quote=False)


def esc_attr(s):
    return html.escape(str(s), quote=True)


def mmdd(date_str):
    """YYYY-MM-DD → MM-DD;解析失败原样返回。"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m-%d")
    except (ValueError, TypeError):
        return date_str or ""


def date_cn(pub):
    """YYYY-MM-DD → (「2026年7月25日」, 「星期六」);解析失败原样、星期为空。"""
    try:
        d = datetime.strptime(pub, "%Y-%m-%d")
        return f"{d.year}年{d.month}月{d.day}日", f"星期{WEEKDAYS[d.weekday()]}"
    except (ValueError, TypeError):
        return pub or "", ""


def bold_last(why):
    """why 末句加粗(对应 vol001 版式:陈述 + <b>论断</b>)。"""
    parts = [p for p in str(why).split("。") if p.strip()]
    if len(parts) >= 2:
        head = "。".join(parts[:-1]) + "。"
        return f"{esc(head)}<b>{esc(parts[-1])}。</b>"
    return esc(why)


def split_hot(why):
    """头条 why 拆成『做了什么』(第一句)与『为什么值得看』(其余)。"""
    parts = [p for p in str(why).split("。") if p.strip()]
    if len(parts) >= 2:
        return parts[0] + "。", "。".join(parts[1:]) + "。"
    return str(why), ""


def meta_line(it, with_date=True):
    mono = esc(it.get("src", ""))
    if with_date and it.get("date"):
        mono += " · " + esc(mmdd(it["date"]))
    return (f'<span class="tag">{esc(it.get("tag", ""))}</span>'
            f'<span class="src-part">{mono}</span>')


def link(it):
    return (f'<a href="{esc_attr(it.get("url", ""))}" target="_blank" '
            f'rel="noopener">{esc(it.get("title", ""))}</a>')


def render_focus(it):
    body, whyline = split_hot(it.get("why", ""))
    hot = f'<span class="hot">{esc(it["hot"])}</span>' if it.get("hot") else ""
    lines = [
        "    <article>",
        f'      <div class="meta">{hot}{meta_line(it)}</div>',
        f"      <h3>{link(it)}</h3>",
    ]
    if it.get("orig"):
        lines.append(f'      <p class="orig">{esc(it["orig"])}</p>')
    lines.append(f'      <p class="body">{esc(body)}</p>')
    if whyline:
        lines.append(f'      <p class="why"><b>为什么值得看:</b>{esc(whyline)}</p>')
    lines.append("    </article>")
    return "\n".join(lines)


def render_paper(it):
    lines = [
        "        <article>",
        f'          <div class="meta">{meta_line(it)}</div>',
        f"          <h3>{link(it)}</h3>",
    ]
    if it.get("orig"):
        lines.append(f'          <p class="orig">{esc(it["orig"])}</p>')
    lines.append(f'          <p class="why">{bold_last(it.get("why", ""))}</p>')
    lines.append("        </article>")
    return "\n".join(lines)


def render_rail(it, with_date):
    return "\n".join([
        '        <div class="rail-item">',
        f'          <div class="meta">{meta_line(it, with_date)}</div>',
        f"          <h3>{link(it)}</h3>",
        f'          <p class="why">{bold_last(it.get("why", ""))}</p>',
        "        </div>",
    ])


def render_idea(idea, vol, base):
    diff = DIFF.get(idea.get("level"), "▮▯▯")
    refs = []
    for b in idea.get("based_on") or []:
        label = esc(b.get("title", ""))
        ref = (f'<a href="{esc_attr(b.get("url", ""))}" target="_blank" '
               f'rel="noopener">{label}</a>')
        if b.get("vol") and b["vol"] != vol:
            # 往期引用:标题链原文,VOL.期号链对应期页
            ref += (f' <a class="volref" href="{base}/issues/vol-{b["vol"]:03d}.html">'
                    f'VOL.{b["vol"]:03d}</a>')
        refs.append(ref)
    # body 以『需要:』拆成正文与技能
    body, _, skills = str(idea.get("body", "")).partition("需要:")
    lines = [
        '      <article class="idea">',
        f'        <div class="diff"><span>{diff} {esc(idea.get("level", ""))}</span>'
        f'<span class="kind">{esc(idea.get("kind", ""))}</span></div>',
        f"        <h3>{esc(idea.get('title', ''))}</h3>",
        f'        <p class="body">{esc(body.strip())}</p>',
    ]
    if refs:
        lines.append(f'        <p class="uses"><b>基于:</b>{" · ".join(refs)}</p>')
    skills = skills.strip().rstrip("。")
    if skills:
        lines.append(f'        <p class="skills"><b>需要:</b>{esc(skills)}</p>')
    lines.append("      </article>")
    return "\n".join(lines)


def merge_archive(archive, issue, vol, pub):
    """并入当期内容。不变量:旧条目全部保留(除非触发 90 天/400 条清理)、按 URL 去重。"""
    old_items = archive.get("items", [])
    old_urls = {it.get("url") for it in old_items if it.get("url")}
    new_items = []
    for it in issue["items"]:
        row = {k: it[k] for k in ITEM_FIELDS if k in it}
        row["vol"], row["pub"] = vol, pub
        if row.get("url") in old_urls:
            print(f"[build] 警告:URL 已在存档中,跳过 {row.get('url')}", file=sys.stderr)
            continue
        new_items.append(row)

    merged, seen = [], set()
    for it in old_items + new_items:
        u = it.get("url")
        if u and u in seen:
            continue
        seen.add(u)
        merged.append(it)
    missing = old_urls - {it.get("url") for it in merged}
    if missing:
        raise RuntimeError(f"存档不变量被破坏,丢失旧条目: {missing}")

    # 清理:保留最近 90 天;items 超过 400 删最旧
    cutoff = (datetime.strptime(pub, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    kept = [it for it in merged if (it.get("pub") or it.get("date") or "") >= cutoff]
    dropped = len(merged) - len(kept)
    if len(kept) > 400:
        kept = sorted(kept, key=lambda it: (it.get("pub") or "", it.get("date") or ""))[-400:]
        dropped = len(merged) - len(kept)
    if dropped:
        print(f"[build] 存档清理:删除最旧 {dropped} 条")

    ideas = list(archive.get("ideas", []))
    for idea in issue["ideas"]:
        row = {"vol": vol}
        for k in ("level", "kind", "title", "body", "based_on", "since_vol"):
            if k in idea:
                row[k] = idea[k]
        ideas.append(row)

    return {"note": archive.get("note", ""), "items": kept, "ideas": ideas}, new_items


def render_issue_page(template, vol, pub, items, ideas, base, archive_link):
    """渲染单期页面。items/ideas 为该期内容(含 vol/pub 字段)。"""
    papers = [it for it in items if it["sec"] == "papers"]
    oss = [it for it in items if it["sec"] == "oss"]
    industry = [it for it in items if it["sec"] == "industry"]
    # 头条:优先 hot 标记;缺失时取首条兜底,保证焦点区不为空
    hot_paper = next((it for it in papers if it.get("hot") == "本报头条"), None)
    hot_paper = hot_paper or (papers[0] if papers else None)
    hot_ind = next((it for it in industry if it.get("hot") == "行业要闻"), None)
    hot_ind = hot_ind or (industry[0] if industry else None)

    focus = "\n".join(render_focus(it) for it in (hot_paper, hot_ind) if it)
    paper_html = "\n\n".join(render_paper(it) for it in papers if it is not hot_paper)
    oss_html = "\n".join(render_rail(it, with_date=False) for it in oss)
    ind_html = "\n".join(render_rail(it, with_date=True)
                         for it in industry if it is not hot_ind)
    idea_html = "\n\n".join(render_idea(i, vol, base) for i in ideas)

    # 内嵌当期 JSON 供详情浮层使用;转义 '<' 避免 </script> 提前闭合
    issue_json = json.dumps(
        {"vol": vol, "pub": pub, "items": items, "ideas": ideas},
        ensure_ascii=False).replace("<", "\\u003c")

    pub_cn, weekday_cn = date_cn(pub)
    mapping = {
        "{{BASE}}": base,
        "{{ARCHIVE_LINK}}": archive_link,
        "{{VOL_PADDED}}": f"{vol:03d}",
        "{{PUB_DATE_CN}}": pub_cn,
        "{{WEEKDAY_CN}}": weekday_cn,
        "{{ITEM_COUNT}}": str(len(items)),
        "{{IDEA_COUNT}}": str(len(ideas)),
        "{{FOCUS_ARTICLES}}": focus,
        "{{PAPER_ITEMS}}": "\n" + paper_html + "\n" if paper_html else "",
        "{{OSS_ITEMS}}": oss_html,
        "{{INDUSTRY_ITEMS}}": ind_html,
        "{{IDEA_ITEMS}}": "\n" + idea_html + "\n" if idea_html else "",
        "{{ISSUE_JSON}}": issue_json,
    }
    page = template
    for k, v in mapping.items():
        page = page.replace(k, v)
    if "{{" in page:
        raise RuntimeError(f"VOL.{vol:03d} 页面存在未替换的占位符!")
    return page


def check_page(path, vol, expect_items):
    """自检:无残留占位符;内嵌 radar-issue JSON 可解析且条目数与当期一致。"""
    text = path.read_text(encoding="utf-8")
    if "{{" in text:
        raise RuntimeError(f"{path} 存在未替换的占位符!")
    m = re.search(r'<script type="application/json" id="radar-issue">\s*(\{.*?\})\s*</script>',
                  text, re.S)
    if not m:
        raise RuntimeError(f"{path} 缺少 radar-issue 内嵌 JSON!")
    data = json.loads(m.group(1))
    if len(data.get("items", [])) != expect_items:
        raise RuntimeError(
            f"{path} 内嵌条目数 {len(data.get('items', []))} ≠ 当期 {expect_items}!")
    return len(text.encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description="渲染 index.html + issues/ + archive.html 并更新存档")
    ap.add_argument("--vol", type=int, help="期号(默认:存档最大 vol + 1)")
    ap.add_argument("--date", help="出版日期 YYYY-MM-DD(默认:北京时间今天)")
    args = ap.parse_args()

    archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    issue = json.loads(ISSUE.read_text(encoding="utf-8"))
    vol = args.vol or max((it.get("vol", 0) for it in archive.get("items", [])), default=0) + 1
    pub = args.date or datetime.now(TZ).strftime("%Y-%m-%d")

    new_archive, new_items = merge_archive(archive, issue, vol, pub)
    ARCHIVE.write_text(json.dumps(new_archive, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    # issue.json 补上 vol/pub,供 make_docx / send_email 使用
    issue["vol"], issue["pub"] = vol, pub
    ISSUE.write_text(json.dumps(issue, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 按期分组存档内容 ----
    vol_items, vol_ideas, vol_pub = {}, {}, {}
    for it in new_archive["items"]:
        v = it.get("vol", 0)
        vol_items.setdefault(v, []).append(it)
        p = it.get("pub") or it.get("date") or ""
        if p > vol_pub.get(v, ""):
            vol_pub[v] = p
    for idea in new_archive["ideas"]:
        vol_ideas.setdefault(idea.get("vol", 0), []).append(idea)
    vols = sorted(vol_items)
    if vol not in vol_items:
        raise RuntimeError(f"存档中没有第 {vol} 期的条目,无法渲染当期页面!")
    vol_pub[vol] = pub

    template = TEMPLATE.read_text(encoding="utf-8")

    # ---- index.html = 最新期 ----
    page = render_issue_page(template, vol, pub, vol_items[vol],
                             vol_ideas.get(vol, []), base=".", archive_link="archive.html")
    OUT.write_text(page, encoding="utf-8")

    # ---- issues/vol-NNN.html = 存档里每一期 ----
    OUT_ISSUES.mkdir(exist_ok=True)
    issue_files = []
    for v in vols:
        p = render_issue_page(template, v, vol_pub.get(v, ""), vol_items[v],
                              vol_ideas.get(v, []), base="..", archive_link="../archive.html")
        f = OUT_ISSUES / f"vol-{v:03d}.html"
        f.write_text(p, encoding="utf-8")
        issue_files.append((f, v))
    # 清理已不在存档中的旧期页(90 天清理后被整期删除的情况)
    keep = {f.name for f, _ in issue_files}
    for old in OUT_ISSUES.glob("vol-*.html"):
        if old.name not in keep:
            old.unlink()
            print(f"[build] 清理过期期页 {old}")

    # ---- archive.html = 往期索引 ----
    latest_cn, _ = date_cn(pub)
    arch_page = ARCH_TEMPLATE.read_text(encoding="utf-8")
    arch_page = arch_page.replace("{{VOL_COUNT}}", str(len(vols)))
    arch_page = arch_page.replace("{{LATEST_DATE}}", latest_cn)
    if "{{" in arch_page:
        raise RuntimeError("archive.html 存在未替换的占位符!")
    OUT_ARCHIVE.write_text(arch_page, encoding="utf-8")

    # ---- 自检与产出清单 ----
    produced = [(OUT, vol)] + issue_files
    print(f"[build] VOL.{vol:03d} · {pub}")
    total = 0
    for f, v in produced:
        size = check_page(f, v, len(vol_items[v]))
        total += size
        print(f"[build]   {f.relative_to(ROOT)}  {size} 字节")
    size = len(OUT_ARCHIVE.read_bytes())
    total += size
    print(f"[build]   {OUT_ARCHIVE.relative_to(ROOT)}  {size} 字节")
    assert len(issue_files) == len(vols), "期页数量与存档期数不一致!"
    print(f"[build] 期页 {len(issue_files)} 份 = 存档期数 {len(vols)} ✓ "
          f"(共 {total} 字节;当期新增 {len(new_items)} 条,"
          f"存档 items {len(new_archive['items'])} · ideas {len(new_archive['ideas'])})")


if __name__ == "__main__":
    main()
