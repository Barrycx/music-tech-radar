#!/usr/bin/env python3
"""发送当期邮件:QQ SMTP(SSL 465),正文为简短信件 + 板块条目链接,附件为当期 docx。

机密全部走环境变量:QQ_MAIL_USER(发件账号)、QQ_SMTP_AUTH(SMTP 授权码)、MAIL_TO(收件人)。
缺任何一个即报错退出,不发送。发送成功后更新 state.json 的 mailed_vol。
"""

import argparse
import html
import json
import os
import smtplib
import sys
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISSUE = ROOT / "build" / "issue.json"
STATE = ROOT / "state.json"

SEC_NAMES = (("papers", "学术前沿"), ("oss", "开源工具"), ("industry", "行业动态"))


def build_html(issue, issue_url, archive_url):
    vol, pub = issue["vol"], issue["pub"]
    parts = [
        '<div style="font-family:Georgia,\'Songti SC\',serif;max-width:42rem;'
        'color:#1a1a1a;line-height:1.8">',
        f'<h2 style="color:#c1301c;letter-spacing:.1em">音乐科技雷达 '
        f'<span style="font-size:.8em;color:#666">第 {vol:03d} 期 · {pub}</span></h2>',
        "<p>早上好,今日份音乐×科技情报已出版。各板块速览如下,完整排版见网页版,详细解读见附件 Word。</p>",
    ]
    for key, name in SEC_NAMES:
        rows = [it for it in issue["items"] if it["sec"] == key]
        if not rows:
            continue
        parts.append(f'<p style="margin-bottom:.2rem"><b>■ {name}</b></p><ul style="margin-top:.2rem">')
        for it in rows:
            star = f'【{it["hot"]}】' if it.get("hot") else ""
            parts.append(
                f'<li><a href="{html.escape(it["url"], quote=True)}">{star}'
                f'{html.escape(it["title"])}</a></li>')
        parts.append("</ul>")
    if issue.get("ideas"):
        parts.append('<p style="margin-bottom:.2rem"><b>■ 选题灵感</b></p><ul style="margin-top:.2rem">'
                     + "".join(f"<li>{i['level']} · {i['kind']}|{html.escape(i['title'])}</li>"
                               for i in issue["ideas"]) + "</ul>")
    parts.append(f'<p>完整页面:<a href="{html.escape(issue_url, quote=True)}">{html.escape(issue_url)}</a></p>')
    parts.append(f'<p style="color:#7b7b78;font-size:.85em">往期回顾:'
                 f'<a href="{html.escape(archive_url, quote=True)}" style="color:#7b7b78">'
                 f'{html.escape(archive_url)}</a></p>')
    parts.append('<p style="color:#7b7b78;font-size:.85em">音乐科技雷达 · 每日 07:00 出版 · '
                 "本邮件由自动出版系统发出</p></div>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="发送当期邮件")
    ap.add_argument("--page-url", default="", help="站点根地址(邮件正文链接拼为 issues/vol-NNN.html 与 archive.html)")
    ap.add_argument("--docx", help="附件路径(默认按 issue.json 的期号日期推算)")
    args = ap.parse_args()

    user = os.environ.get("QQ_MAIL_USER")
    auth = os.environ.get("QQ_SMTP_AUTH")
    mail_to = os.environ.get("MAIL_TO")
    missing = [k for k, v in (("QQ_MAIL_USER", user), ("QQ_SMTP_AUTH", auth), ("MAIL_TO", mail_to)) if not v]
    if missing:
        print(f"[mail] 错误:缺少环境变量 {'、'.join(missing)},未发送。", file=sys.stderr)
        sys.exit(1)

    issue = json.loads(ISSUE.read_text(encoding="utf-8"))
    vol, pub = issue.get("vol"), issue.get("pub")
    if not vol or not pub:
        print("[mail] 错误:issue.json 缺少 vol/pub(请先运行 build_page.py)", file=sys.stderr)
        sys.exit(1)
    docx = Path(args.docx) if args.docx else ROOT / "word" / f"音乐科技雷达_第{vol:03d}期_{pub}.docx"
    if not docx.exists():
        print(f"[mail] 错误:附件不存在 {docx}", file=sys.stderr)
        sys.exit(1)
    if args.page_url:
        base = args.page_url if args.page_url.endswith("/") else args.page_url + "/"
        issue_url = f"{base}issues/vol-{vol:03d}.html"   # 当期永久链接
        archive_url = f"{base}archive.html"
    else:
        issue_url = archive_url = "(页面地址未配置)"

    msg = MIMEMultipart()
    msg["Subject"] = Header(f"音乐科技雷达 第{vol:03d}期 {pub}", "utf-8")
    msg["From"] = formataddr((str(Header("音乐科技雷达", "utf-8")), user))
    msg["To"] = mail_to
    msg.attach(MIMEText(build_html(issue, issue_url, archive_url), "html", "utf-8"))
    with open(docx, "rb") as f:
        att = MIMEApplication(f.read())
    att.add_header("Content-Disposition", "attachment",
                   filename=Header(docx.name, "utf-8").encode())
    msg.attach(att)

    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=60) as smtp:
            smtp.login(user, auth)
            smtp.send_message(msg, from_addr=user,
                              to_addrs=[a.strip() for a in mail_to.split(",") if a.strip()])
    except Exception as exc:
        print(f"[mail] 发送失败: {exc}", file=sys.stderr)
        sys.exit(1)

    STATE.write_text(json.dumps({"mailed_vol": vol}, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print(f"[mail] 第 {vol:03d} 期已送达,state.json mailed_vol={vol}")


if __name__ == "__main__":
    main()
