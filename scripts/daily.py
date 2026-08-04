#!/usr/bin/env python3
"""每日总控:决定今天出版、补发,还是收工。

- 存档最新 pub 已是今天(北京时间):
    mailed_vol == 当前 vol → 今日已出版已送达,结束;
    否则 → 只补发邮件(用当天已有产物)。
- 否则完整出版:fetch → edit(--mock 可透传)→ build_page → make_docx → send_email(--no-mail 跳过)。
- 缺刊不补刊:昨天没出不补,期号始终 = 存档最大 vol + 1。
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ARCHIVE = ROOT / "archive.json"
STATE = ROOT / "state.json"
TZ = ZoneInfo("Asia/Shanghai")


def run_step(name, script, extra=()):
    print(f"\n===== {name} =====", flush=True)
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *extra])
    if r.returncode != 0:
        print(f"[daily] 步骤「{name}」失败(exit {r.returncode}),中止。", file=sys.stderr)
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description="音乐科技雷达 · 每日总控")
    ap.add_argument("--mock", action="store_true", help="编辑步骤用内置假数据,不调 API")
    ap.add_argument("--no-mail", action="store_true", help="跳过邮件发送")
    ap.add_argument("--page-url", default="", help="站点根地址(传给邮件正文,自动拼期页/往期页链接)")
    args = ap.parse_args()

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    items = archive.get("items", [])
    latest_pub = max((it.get("pub", "") for it in items), default="")
    vol = max((it.get("vol", 0) for it in items), default=0)
    mailed_vol = json.loads(STATE.read_text(encoding="utf-8")).get("mailed_vol", 0)

    if latest_pub == today:
        print(f"[daily] 存档最新 pub={latest_pub},今日(北京 {today})已出版(VOL.{vol:03d})")
        if mailed_vol == vol:
            print("[daily] 今日已出版已送达,结束。")
            return
        if args.no_mail:
            print(f"[daily] mailed_vol={mailed_vol} ≠ {vol},但指定了 --no-mail,不补发。")
            return
        print(f"[daily] mailed_vol={mailed_vol} ≠ {vol},执行补发邮件。")
        run_step("补发邮件", "send_email.py", ["--page-url", args.page_url])
        return

    print(f"[daily] 今日(北京 {today})未出版,开始完整出版流程(存档最新 pub={latest_pub})")
    if args.mock:
        print("[daily] --mock:跳过抓取,编辑步骤使用内置假数据。")
    else:
        run_step("抓取素材 fetch_sources", "fetch_sources.py")
    run_step("每日编辑 edit_issue", "edit_issue.py", ["--mock"] if args.mock else [])
    run_step("渲染页面 build_page", "build_page.py")
    run_step("生成 Word make_docx", "make_docx.py")
    if args.no_mail:
        print("\n[daily] --no-mail:跳过邮件发送。")
    else:
        run_step("发送邮件 send_email", "send_email.py", ["--page-url", args.page_url])

    issue = json.loads((ROOT / "build" / "issue.json").read_text(encoding="utf-8"))
    n = len(issue["items"])
    print(f"\n[daily] 完成:VOL.{issue['vol']:03d} · {issue['pub']} · 收录 {n} 条 · "
          f"选题 {len(issue['ideas'])} 个 · 邮件 {'跳过' if args.no_mail else '已发'}")


if __name__ == "__main__":
    main()
