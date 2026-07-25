#!/usr/bin/env python3
"""渲染当期页面:模板 + issue.json + archive.json → radar/index.html。

流程:先把当期内容并入存档(不变量:旧条目全部保留、按 URL 去重、
保留最近 90 天且 items ≤ 400 删最旧),写回 archive.json;
再渲染各区块 HTML 片段填充模板占位符。

期号:--vol 参数,或自动 = 存档最大 vol + 1。
出版日期:--date 参数,或北京时间今天(Asia/Shanghai)。
"""

import argparse
import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template" / "page.html"
ARCHIVE = ROOT / "archive.json"
ISSUE = ROOT / "build" / "issue.json"
OUT = ROOT / "index.html"
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
            f'<span class="mono-part">{mono}</span>')


def link(it):
    return (f'<a href="{esc_attr(it.get("url", ""))}" target="_blank" '
            f'rel="noopener">{esc(it.get("title", ""))}</a>')


def render_focus(it):
    body, whyline = split_hot(it.get("why", ""))
    lines = [
        "    <article>",
        f'      <div class="meta"><span class="hot">{esc(it["hot"])}</span>{meta_line(it)}</div>',
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


def render_idea(idea, vol):
    diff = DIFF.get(idea.get("level"), "▮▯▯")
    refs = []
    for b in idea.get("based_on") or []:
        label = esc(b.get("title", ""))
        if b.get("vol") and b["vol"] != vol:
            label += f" (VOL.{b['vol']:03d})"
        refs.append(f'<a href="{esc_attr(b.get("url", ""))}" target="_blank" '
                    f'rel="noopener">{label}</a>')
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


def main():
    ap = argparse.ArgumentParser(description="渲染当期 index.html 并更新存档")
    ap.add_argument("--vol", type=int, help="期号(默认:存档最大 vol + 1)")
    ap.add_argument("--date", help="出版日期 YYYY-MM-DD(默认:北京时间今天)")
    args = ap.parse_args()

    archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    issue = json.loads(ISSUE.read_text(encoding="utf-8"))
    vol = args.vol or max((it.get("vol", 0) for it in archive.get("items", [])), default=0) + 1
    pub = args.date or datetime.now(TZ).strftime("%Y-%m-%d")
    d = datetime.strptime(pub, "%Y-%m-%d")

    new_archive, new_items = merge_archive(archive, issue, vol, pub)
    ARCHIVE.write_text(json.dumps(new_archive, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    # issue.json 补上 vol/pub,供 make_docx / send_email 使用
    issue["vol"], issue["pub"] = vol, pub
    ISSUE.write_text(json.dumps(issue, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 渲染各区块 ----
    papers = [it for it in issue["items"] if it["sec"] == "papers"]
    oss = [it for it in issue["items"] if it["sec"] == "oss"]
    industry = [it for it in issue["items"] if it["sec"] == "industry"]
    hot_paper = next(it for it in papers if it.get("hot") == "本报头条")
    hot_ind = next(it for it in industry if it.get("hot") == "行业要闻")
    focus = render_focus(hot_paper) + "\n" + render_focus(hot_ind)
    paper_html = "\n\n".join(render_paper(it) for it in papers if it is not hot_paper)
    oss_html = "\n".join(render_rail(it, with_date=False) for it in oss)
    ind_html = "\n".join(render_rail(it, with_date=True)
                         for it in industry if it is not hot_ind)
    idea_html = "\n\n".join(render_idea(i, vol) for i in issue["ideas"])

    # 存档块转义 '<',避免 JSON 字符串内的 </script> 提前闭合标签
    archive_json = json.dumps(new_archive, ensure_ascii=False, indent=2).replace("<", "\\u003c")

    page = TEMPLATE.read_text(encoding="utf-8")
    mapping = {
        "{{VOL_PADDED}}": f"{vol:03d}",
        "{{PUB_DATE_CN}}": f"{d.year}年{d.month}月{d.day}日",
        "{{WEEKDAY_CN}}": f"星期{WEEKDAYS[d.weekday()]}",
        "{{ITEM_COUNT}}": str(len(new_items)),
        "{{IDEA_COUNT}}": str(len(issue["ideas"])),
        "{{FOCUS_ARTICLES}}": focus,
        "{{PAPER_ITEMS}}": "\n" + paper_html + "\n" if paper_html else "",
        "{{OSS_ITEMS}}": oss_html,
        "{{INDUSTRY_ITEMS}}": ind_html,
        "{{IDEA_ITEMS}}": "\n" + idea_html + "\n" if idea_html else "",
        "{{GEN_DATE}}": pub,
        "{{ARCHIVE_JSON}}": archive_json,
    }
    for k, v in mapping.items():
        page = page.replace(k, v)
    if "{{" in page:
        raise RuntimeError("存在未替换的占位符!")

    OUT.write_text(page, encoding="utf-8")
    print(f"[build] VOL.{vol:03d} · {pub} → {OUT}")
    print(f"[build] 存档:items {len(new_archive['items'])} 条(当期新增 {len(new_items)})"
          f" · ideas {len(new_archive['ideas'])} 条")
    print(f"[build] 页面 {len(page.encode('utf-8'))} 字节")


if __name__ == "__main__":
    main()
