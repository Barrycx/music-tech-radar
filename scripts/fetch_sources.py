#!/usr/bin/env python3
"""抓取候选素材:arXiv × 2、Hacker News × 2、GitHub 热门仓库。

仅用标准库。某个源失败只记 warning、不阻塞整体。
输出:radar/build/raw.json
"""

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "raw.json"
TZ = ZoneInfo("Asia/Shanghai")


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

ATOM = "{http://www.w3.org/2005/Atom}"


def http_get(url, timeout=30):
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
            out.append({"source": "arxiv", "title": title, "summary": summary,
                        "published": published, "url": url, "authors": authors})
    return out


def parse_hn(data):
    """HN Algolia JSON → hits(title/url/points)。"""
    out = []
    for h in data.get("hits", []):
        title, url = h.get("title"), h.get("url")
        if title and url:
            out.append({"source": "hn", "title": title, "url": url,
                        "points": h.get("points", 0),
                        "published": (h.get("created_at") or "")[:10]})
    return out


def parse_github(data):
    """GitHub 仓库搜索 JSON → items(full_name/html_url/description/stargazers_count)。"""
    out = []
    for r in data.get("items", []):
        out.append({"source": "github", "full_name": r.get("full_name"),
                    "url": r.get("html_url"), "description": r.get("description") or "",
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language") or "",
                    "published": (r.get("created_at") or "")[:10]})
    return out


def main():
    today = datetime.now(TZ).date()
    since = (today - timedelta(days=30)).isoformat()
    github_url = ("https://api.github.com/search/repositories?q=music+OR+audio+created:%3E"
                  f"{since}&sort=stars&order=desc&per_page=20")

    jobs = [
        ("arxiv_sd", ARXIV_SD, lambda b: parse_arxiv(b)),
        ("arxiv_hc", ARXIV_HC, lambda b: parse_arxiv(b)),
        ("hn_music", HN_MUSIC, lambda b: parse_hn(json.loads(b))),
        ("hn_audio", HN_AUDIO, lambda b: parse_hn(json.loads(b))),
        ("github", github_url, lambda b: parse_github(json.loads(b))),
    ]

    sources, warnings = {}, []
    for name, url, parser in jobs:
        try:
            items = parser(http_get(url))
            sources[name] = items
            print(f"[fetch] {name}: {len(items)} 条候选")
        except Exception as exc:  # 单个源失败不阻塞
            warnings.append(f"{name}: {exc}")
            sources[name] = []
            print(f"[fetch][warning] {name} 抓取失败,已跳过: {exc}", file=sys.stderr)

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
