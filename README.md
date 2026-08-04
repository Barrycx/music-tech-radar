# 音乐科技雷达 · 自建每日情报系统

替换原 Claude 云端定时任务的本地 Python 实现。每天北京时间 07:00 前后运行一次,
产出:网页版 `index.html`、Word 版 `word/*.docx`、QQ 邮件送达,并维护机器可读存档 `archive.json`。

## 架构(文字版)

```
数据源(arXiv × 2 / HN × 2 / GitHub / OpenAlex / Google News 中英 × 2
       / Hugging Face 论文+模型 / 行业 RSS × 3 / Bluesky,共 14 源)
        │  fetch_sources.py   → build/raw.json(候选素材,URL 归一化+去重,失败源跳过)
        ▼
archive.json(历期存档)+ raw.json
        │  edit_issue.py      → 调 Kimi API 两段式:调用 A 选稿写作 → items,
        ▼                       调用 B 选题策划 → ideas,合并校验 → build/issue.json
                              (--mock 时用内置假数据)
build_page.py ── ① 新条目并入 archive.json(去重 / 90 天 / ≤400 条)
              └ ② 渲染多页静态站:index.html(最新期)+ issues/vol-NNN.html(每期
                 永久链接)+ archive.html(往期索引,前端 fetch archive.json 渲染)
        ▼
make_docx.py  → word/音乐科技雷达_第NNN期_YYYY-MM-DD.docx
        ▼
send_email.py → QQ SMTP 发信(正文摘要 + docx 附件)→ state.json mailed_vol=N
        ▲
daily.py(总控):今日已出版且已送达则收工;已出版未送达则只补发;否则完整出版。
```

## 本地运行

```bash
cd radar
# 全链路演练(不调 API、不发邮件,需要网络抓取;--mock 时连抓取也跳过)
python3 scripts/daily.py --mock --no-mail

# 正式出版(需要环境变量,见下)
python3 scripts/daily.py

# 单步调试
python3 scripts/fetch_sources.py
python3 scripts/edit_issue.py [--mock]
python3 scripts/build_page.py [--vol 2] [--date 2026-07-24]
python3 scripts/make_docx.py
python3 scripts/send_email.py --page-url https://你的页面地址/
```

依赖:仅 `python-docx`(抓取/渲染/邮件全部标准库)。系统 Python 没有时装到虚拟环境:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/daily.py --mock --no-mail
```

## 环境变量

| 变量 | 用途 | 缺省行为 |
|---|---|---|
| `KIMI_API_KEY` | Kimi Code API key(`sk-kimi-` 开头,端点 `api.kimi.com/coding/v1`,模型 `kimi-for-coding`) | 缺失时 edit_issue 报错(可用 `--mock` 绕过) |
| `QQ_MAIL_USER` | QQ 邮箱发件账号 | 缺失则不发送,报错退出 |
| `QQ_SMTP_AUTH` | QQ 邮箱 SMTP 授权码 | 同上 |
| `MAIL_TO` | 收件人(多个用逗号分隔) | 同上 |

代码中不出现任何密钥/邮箱字面量,全部走环境变量。

## 每天自动运行

由 GitHub Actions 定时触发,workflow:`.github/workflows/daily.yml`。
主班次 cron UTC `5 23 * * *`(北京 07:05),补刊班次 UTC `5 0 * * *`(北京 08:05,幂等)。
四个环境变量存到仓库 Secrets(`KIMI_API_KEY` / `QQ_MAIL_USER` / `QQ_SMTP_AUTH` / `MAIL_TO`),
Pages source 选 GitHub Actions;`archive.json` / `state.json` / `index.html` / `archive.html` / `issues/` / `word/` 由 workflow 提交回仓库。

## 数据文件

- `archive.json` — 唯一权威存档:历期 items(含 vol/pub/sec/tag/title/url/src/why/hot/detail)
  与 ideas。只增不减(除 90 天 / 400 条清理),跨期去重与选题积累都靠它;
  同时原样发布为静态资源,`archive.html` 前端 fetch 它渲染往期列表;
  每期页内嵌 `#radar-issue`(仅当期 items+ideas)供详情浮层渲染。
- `state.json` — `{"mailed_vol": N}`,邮件幂等。
- `template/page.html` / `template/archive.html` — 版式模板,内容区为 `{{占位符}}`,
  设计遵循 `docs/hallmark/`(Nutlope/hallmark 规范,MIT):移动端优先、吸顶 tab 分栏、深浅色主题。
- `docs/hallmark/` — vendored 的网页设计规范(SKILL.md + references/),改版时遵循。
- `build/` — 中间产物(raw.json / issue.json),可随时删除重建。
