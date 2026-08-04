#!/usr/bin/env python3
"""抓取候选素材:arXiv × 2、Hacker News × 2、GitHub、OpenAlex、Google News × 2、
Hugging Face × 2、行业 RSS × 3、Bluesky。

仅用标准库。某个源失败只记 warning、不阻塞整体。
所有候选统一规范:至少含 title/url,有日期给 date(YYYY-MM-DD),有摘要给 summary(≤400 字);
URL 入库前一律经 normalize_url() 归一化,并在单源内部与跨源各去重一次。
输出:radar/build/raw.json
"""

import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "raw.json"
TZ = ZoneInfo("Asia/Shanghai")

TIMEOUT = 20  # 每个源的单次请求超时(秒),保证总耗时可控


def _ssl_context():
    """优先用 certifi 的 CA(部分 macOS Python 缺系统证书链),仍是可选依赖。"""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()

ARXIV_SD = ("https://export.arxiv.org/api/query?search_query=cat:cs.SD+OR+cat:eess.AS"
            "&sortBy=submittedDate&sortOrder=descending&max_results=40")
ARXIV_HC = ("https://export.arxiv.org/api/query?search_query=%28all:music+OR+all:audio%29"
            "+AND+%28cat:cs.HC+OR+cat:cs.MM%29&sortBy=submittedDate&sortOrder=descending&max_results=20")
HN_MUSIC = ("https://hn.algolia.com/api/v1/search_by_date?query=music&tags=story"
            "&numericFilters=points%3E10")
HN_AUDIO = ("https://hn.algolia.com/api/v1/search_by_date?query=audio&tags=story"
            "&numericFilters=points%3E10")
GNEWS_ZH = ("https://news.google.com/rss/search?"
            "q=AI%E9%9F%B3%E4%B9%90+OR+%E9%9F%B3%E4%B9%90%E7%94%9F%E6%88%90+OR+AI+music"
            "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")  # q=AI音乐 OR 音乐生成 OR AI music(需 URL 编码)
GNEWS_EN = ("https://news.google.com/rss/search?q=%22AI+music%22+OR+%22music+generation%22"
            "+OR+%22music+AI%22&hl=en-US&gl=US&ceid=US:en")
HF_PAPERS = "https://huggingface.co/api/daily_papers"
HF_MODELS = ("https://huggingface.co/api/models?pipeline_tag=text-to-audio"
             "&sort=lastModified&limit=30&direction=-1")
RSS_CDM = "https://cdm.link/feed/"
RSS_MUSICTECH = "https://musictech.com/feed/"
RSS_SYNTHTOPIA = "https://www.synthtopia.com/feed/"
BLUESKY = ("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
           "?q=music%20AI&limit=25&sort=latest")

ATOM = "{http://www.w3.org/2005/Atom}"

# 常见追踪参数(归一化时剔除;utm_* 前缀整体剔除)
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "igshid", "spm", "mc_cid", "mc_eid", "ref"}


def normalize_url(url):
    """URL 归一化:小写 scheme/host、http→https、去尾斜杠、去追踪参数、
    arXiv 链接去版本号(/abs/2607.20166v1 → /abs/2607.20166)。

    入库与跨期去重都以归一化后的 URL 为准。解析失败时原样返回(不丢数据)。
    """
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    netloc = (parts.netloc or "").lower()
    path = parts.path
    # arXiv 去版本号:/abs/2607.20166v1、/pdf/2607.20166v2 → 去掉结尾 vN
    if "arxiv.org" in netloc:
        path = re.sub(r"v\d+$", "", path)
    path = path.rstrip("/")
    # 剔除 utm_* 等追踪参数,保留其余参数的原始顺序
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS])
    return urlunsplit((scheme, netloc, path, query, ""))


def http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "music-tech-radar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def parse_arxiv(xml_bytes):
    """arXiv Atom XML → 候选列表(title/summary/published/url/authors 前两位)。"""
    root = ET.fromstring(xml_bytes)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        title = " ".join((e.findtext(f"{ATOM}title") or "").split())
        summary = " ".join((e.findtext(f"{ATOM}summary") or "").split())
        published = (e.findtext(f"{ATOM}published") or "")[:10]
        url = (e.findtext(f"{ATOM}id") or "").strip()
        authors = [a.findtext(f"{ATOM}name") or "" for a in e.findall(f"{ATOM}author")][:2]
        if title and url:
            out.append({"source": "arxiv", "title": title, "summary": summary[:400],
                        "date": published, "published": published, "url": url,
                        "authors": authors})
    return out


def parse_hn(data):
    """HN Algolia JSON → hits(title/url/points)。"""
    out = []
    for h in data.get("hits", []):
        title, url = h.get("title"), h.get("url")
        if title and url:
            out.append({"source": "hn", "title": title, "url": url,
                        "points": h.get("points", 0),
                        "date": (h.get("created_at") or "")[:10],
                        "published": (h.get("created_at") or "")[:10]})
    return out


def parse_github(data):
    """GitHub 仓库搜索 JSON → items(full_name/html_url/description/stargazers_count)。"""
    out = []
    for r in data.get("items", []):
        out.append({"source": "github", "full_name": r.get("full_name"),
                    "title": r.get("full_name"),
                    "url": r.get("html_url"), "description": r.get("description") or "",
                    "summary": (r.get("description") or "")[:400],
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language") or "",
                    "date": (r.get("created_at") or "")[:10],
                    "published": (r.get("created_at") or "")[:10]})
    return out


def _abstract_from_inverted(index):
    """OpenAlex 的 abstract_inverted_index(词 → 位置列表)还原成Plain文本。"""
    if not isinstance(index, dict) or not index:
        return ""
    positions = {}
    for word, pos_list in index.items():
        for p in pos_list:
            positions[p] = word
    return " ".join(positions[p] for p in sorted(positions))


def parse_openalex(data):
    """OpenAlex works JSON → title/date/doi/landing_page_url + 还原摘要。"""
    out = []
    for w in data.get("results", []):
        title = " ".join((w.get("title") or "").split())
        loc = w.get("primary_location") or {}
        url = loc.get("landing_page_url") or w.get("doi") or ""
        if not title or not url:
            continue
        out.append({"source": "openalex", "title": title, "url": url,
                    "date": (w.get("publication_date") or "")[:10],
                    "summary": _abstract_from_inverted(w.get("abstract_inverted_index"))[:400],
                    "doi": w.get("doi") or ""})
    return out


def _strip_html(text):
    """剥 HTML 标签并折叠空白(用于 RSS description)。"""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(text).split())


def _parse_rss_date(value):
    """RSS pubDate(RFC 822)→ YYYY-MM-DD,解析失败返回空串。"""
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value.strip()).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_rss(xml_bytes, source_name):
    """通用 RSS 解析:title/link/pubDate/description(截 400 字剥 HTML)/source。"""
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        entry = {"source": source_name, "title": title, "url": link,
                 "date": _parse_rss_date(item.findtext("pubDate"))}
        src_el = item.find("source")
        if src_el is not None and (src_el.text or "").strip():
            entry["src_name"] = src_el.text.strip()
        desc = _strip_html(item.findtext("description"))
        if desc:
            entry["summary"] = desc[:400]
        out.append(entry)
    return out


def resolve_redirects(items, limit=15, timeout=3):
    """Google News 的 link 是跳转页:对前 limit 条尝试一次 GET 取最终 URL,
    超时/失败保留原链接。限制条数与超时,避免拖慢整体。"""
    for c in items[:limit]:
        try:
            req = urllib.request.Request(c["url"],
                                         headers={"User-Agent": "music-tech-radar/1.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                final_url = resp.geturl()
            if final_url:
                c["url"] = final_url
        except Exception:
            pass  # 跳转解析失败不阻塞,用原链接
    return items


def parse_hf_papers(data):
    """HF daily_papers JSON → 只保留标题/摘要含 music|audio|sound 的论文。"""
    out = []
    for entry in data if isinstance(data, list) else []:
        paper = entry.get("paper") or {}
        title = " ".join((paper.get("title") or "").split())
        summary = " ".join((paper.get("summary") or "").split())
        text = (title + " " + summary).lower()
        if not any(k in text for k in ("music", "audio", "sound")):
            continue
        arxiv_id = (paper.get("id") or "").strip()
        if not title or not arxiv_id:
            continue
        out.append({"source": "hf_papers", "title": title,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "date": (entry.get("publishedAt") or paper.get("publishedAt") or "")[:10],
                    "summary": summary[:400]})
    return out


def parse_hf_models(data):
    """HF text-to-audio 模型列表 JSON → id/lastModified/downloads/likes。"""
    out = []
    for m in data if isinstance(data, list) else []:
        model_id = (m.get("id") or "").strip()
        if not model_id:
            continue
        out.append({"source": "hf_models", "title": model_id,
                    "url": f"https://huggingface.co/{model_id}",
                    "date": (m.get("lastModified") or "")[:10],
                    "downloads": m.get("downloads", 0), "likes": m.get("likes", 0)})
    return out


def parse_bluesky(data):
    """Bluesky searchPosts JSON → 帖子文本(截 300)/作者 handle/indexedAt,
    url 由 handle + rkey(uri 最后一段)拼出。"""
    out = []
    for p in data.get("posts", []):
        record = p.get("record") or {}
        text = " ".join((record.get("text") or "").split())
        handle = ((p.get("author") or {}).get("handle") or "").strip()
        rkey = (p.get("uri") or "").rstrip("/").rsplit("/", 1)[-1]
        if not text or not handle or not rkey:
            continue
        out.append({"source": "bluesky", "title": text[:80], "summary": text[:300],
                    "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                    "date": (p.get("indexedAt") or "")[:10], "author": handle})
    return out


def dedup_within(items):
    """单源内部按 URL 去重(URL 此时已归一化)。"""
    seen, out = set(), []
    for c in items:
        u = c.get("url", "")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(c)
    return out


def main():
    today = datetime.now(TZ).date()
    since = (today - timedelta(days=30)).isoformat()
    github_url = ("https://api.github.com/search/repositories?q=music+OR+audio+created:%3E"
                  f"{since}&sort=stars&order=desc&per_page=20")
    openalex_url = ("https://api.openalex.org/works?filter=primary_topic.id:T11309,"
                    f"from_publication_date:{(today - timedelta(days=3)).isoformat()},"
                    f"to_publication_date:{today.isoformat()}"
                    "&per-page=50&sort=publication_date:desc&mailto=radar@example.com")

    jobs = [
        ("arxiv_sd", ARXIV_SD, parse_arxiv),
        ("arxiv_hc", ARXIV_HC, parse_arxiv),
        ("hn_music", HN_MUSIC, lambda b: parse_hn(json.loads(b))),
        ("hn_audio", HN_AUDIO, lambda b: parse_hn(json.loads(b))),
        ("github", github_url, lambda b: parse_github(json.loads(b))),
        ("openalex", openalex_url, lambda b: parse_openalex(json.loads(b))),
        ("gnews_zh", GNEWS_ZH, lambda b: parse_rss(b, "gnews_zh")),
        ("gnews_en", GNEWS_EN, lambda b: parse_rss(b, "gnews_en")),
        ("hf_papers", HF_PAPERS, lambda b: parse_hf_papers(json.loads(b))),
        ("hf_models", HF_MODELS, lambda b: parse_hf_models(json.loads(b))),
        ("rss_cdm", RSS_CDM, lambda b: parse_rss(b, "rss_cdm")),
        ("rss_musictech", RSS_MUSICTECH, lambda b: parse_rss(b, "rss_musictech")),
        ("rss_synthtopia", RSS_SYNTHTOPIA, lambda b: parse_rss(b, "rss_synthtopia")),
        ("bluesky", BLUESKY, lambda b: parse_bluesky(json.loads(b))),
    ]

    sources, warnings = {}, []
    for name, url, parser in jobs:
        try:
            items = parser(http_get(url))
            if name.startswith("gnews_"):
                items = resolve_redirects(items)  # Google 跳转链接尝试取最终 URL
            for c in items:  # URL 统一归一化
                c["url"] = normalize_url(c.get("url", ""))
            sources[name] = dedup_within(items)
            print(f"[fetch] {name}: {len(sources[name])} 条候选")
        except Exception as exc:  # 单个源失败不阻塞
            warnings.append(f"{name}: {exc}")
            sources[name] = []
            print(f"[fetch][warning] {name} 抓取失败,已跳过: {exc}", file=sys.stderr)

    # 跨源去重:以归一化 URL 为准,按源顺序保留先出现的
    seen_global = set()
    for name in sources:
        kept = []
        for c in sources[name]:
            u = c.get("url", "")
            if u and u not in seen_global:
                seen_global.add(u)
                kept.append(c)
        if len(kept) != len(sources[name]):
            print(f"[fetch] {name}: 跨源去重去掉 {len(sources[name]) - len(kept)} 条")
        sources[name] = kept

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": datetime.now(TZ).isoformat(timespec="seconds"),
               "sources": sources, "warnings": warnings}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in sources.values())
    print(f"[fetch] 共 {total} 条候选 → {OUT}")
    if warnings:
        print(f"[fetch] {len(warnings)} 个源失败(详见 warnings)")


if __name__ == "__main__":
    main()
