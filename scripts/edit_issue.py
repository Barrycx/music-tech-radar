#!/usr/bin/env python3
"""每日编辑:读存档 + 候选素材,调 Kimi(Moonshot)API 产出当期内容(JSON)。

- 接口:OpenAI 兼容 https://api.moonshot.cn/v1/chat/completions,模型 kimi-k2-0711-preview
- key 从环境变量 MOONSHOT_API_KEY 读,代码中不出现任何密钥字面量
- --mock 模式:不调 API,产出内置假 issue,用于无 key 时跑通链路
输出:radar/build/issue.json
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "archive.json"
RAW = ROOT / "build" / "raw.json"
OUT = ROOT / "build" / "issue.json"

API_URL = "https://api.moonshot.cn/v1/chat/completions"
MODEL = "kimi-k2-0711-preview"


def _ssl_context():
    """优先用 certifi 的 CA(部分 macOS Python 缺系统证书链),仍是可选依赖。"""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()

SECS = ("papers", "oss", "industry")
LEVELS = ("入门", "进阶", "硬核")

PROMPT_TMPL = """你是「音乐科技雷达」的每日编辑。这是一份面向浙江音乐学院『数字音乐智能处理』专业学生的每日情报报纸,覆盖音乐×计算机(AI 音乐生成、MIR、音频处理)与音乐×视觉/交互艺术的学术与行业动态。你的任务:从下面的候选素材中筛选最近 24–48 小时的最新内容,产出当期报纸内容(JSON)。

【筛选标准】
- 只保留与专业强相关的:音乐/歌声生成、符号音乐、MIR(转谱/检索/推荐/评测)、音频信号处理与音效、音乐×视觉/VR/交互艺术、新型音乐交互界面(NIME 类)、音乐科技行业新闻(版权诉讼、产品发布、公司动态)。
- 排除:纯语音技术(ASR/TTS/说话人识别,除非与音乐直接相关)、生物声学、与音乐无关的音频工程、GitHub 上的盗版软件和 SEO 垃圾仓库。
- 去重:下列「已收录 URL」任何一条都不得再次出现在你的输出中。
- 数量:学术(papers)5–8 篇、开源(oss)2–4 个、行业(industry)2–4 条。宁缺毋滥,某板块没有好内容就少放。
- 恰好 2 条头条:学术板块选 1 条标 hot="本报头条",行业板块选 1 条标 hot="行业要闻",其余条目不带 hot 字段。

【写作要求】
- 全部用中文,文字凝练。
- 每条 items 字段:sec(papers|oss|industry)、tag(短分类,如 音乐生成/符号音乐/评测/版权)、date(条目自身日期 YYYY-MM-DD)、title(中文标题)、url、src(来源短标注,如 "arXiv · cs.SD"、"HN 396pt"、"C++ · 842★")、orig(论文英文原题,非论文省略)、why(凝练一两句:做了什么+为什么值得看;头条条目写两句——第一句『做了什么』,第二句『为什么值得看』,两句都以句号结尾)、detail(详情正文)。
- detail 写给『懂音乐但技术一般』的读者,通俗直白、少术语、多类比,固定三段、段间用 \\n 分隔:【这是什么】(2–4 句)、【为什么值得关注】(2–3 句)、【怎么入手】(2–3 句),文本内不出现英文双引号。

【选题灵感 ideas】3–4 个可动手的作品/研究选题:
- 基于存档中近 60 天的全部积累(不只是当天候选!),鼓励跨期组合,按难度从低到高排列。
- 每条字段:level(入门|进阶|硬核)、kind(工具|交互作品|产品原型|研究)、title、body(一两句做什么和怎么做,结尾用『需要:』列出所需技能)、based_on(引用的相关条目数组,每项含 url、title;引用往期条目时额外带 vol 字段标注期号)。
- 选题要具体可执行,难度跨度从课程作业到可发论文,适合音乐学院学生(会乐理、编程能力中等)。
- 好选题可以连续保留多期(沿用下方「历期选题」中的选题,基于的条目标注首提期号),但至少有 1 个新选题或明显升级的旧选题。

【输出契约】只输出一个 JSON 对象,不要输出任何其他文字。schema:
{"items":[{"sec":"papers|oss|industry","tag":"..","date":"YYYY-MM-DD","title":"..","url":"..","src":"..","orig":"可选","why":"..","hot":"可选:本报头条|行业要闻","detail":"三段,段间\\n分隔"}],"ideas":[{"level":"入门|进阶|硬核","kind":"..","title":"..","body":"..","based_on":[{"vol":可选,"url":"..","title":".."}]}]}

【已收录 URL(禁止重复)】
{known_urls}

【历期选题(可沿用并标注首提期号)】
{known_ideas}

【候选素材】
{candidates}
"""

MOCK_ISSUE = {
    "items": [
        {"sec": "papers", "tag": "音乐生成", "date": "2026-07-24",
         "title": "示例头条:歌词到整曲的一站式生成模型公开权重",
         "url": "https://arxiv.org/abs/2607.90001", "src": "arXiv · cs.SD",
         "orig": "Open Weights for End-to-End Lyric-to-Song Generation",
         "why": "新模型把歌词、风格描述一步映射为带人声的完整歌曲,并公开全部权重。开源全曲生成第一次达到接近商业产品的完成度。",
         "hot": "本报头条",
         "detail": "【这是什么】一个开源的 AI 作曲系统:输入歌词和一句风格描述(比如『欢快的独立摇滚』),直接输出带人声和伴奏的完整歌曲,而且模型权重全部公开,任何人都能下载使用。\n【为什么值得关注】此前能做到这个完成度的只有 Suno 这类闭源商业产品,开源意味着你可以拆开看它的内部构造、在自己的机器上跑、甚至改造成自己的创作工具。对学习和研究都是重大利好。\n【怎么入手】先跑官方 Demo 感受效果;有显卡的话按 README 本地推理一次,试试用中文歌词会发生什么。不需要读完全文,先建立直观感受。"},
        {"sec": "papers", "tag": "符号音乐", "date": "2026-07-24",
         "title": "示例:用对比学习对齐 MIDI 与音频表示",
         "url": "https://arxiv.org/abs/2607.90002", "src": "arXiv",
         "orig": "Contrastive Alignment of Symbolic and Audio Music Representations",
         "why": "让模型同时理解乐谱和音频两种形态的音乐。统一表示是检索、转谱等下游任务的基础设施。",
         "detail": "【这是什么】研究人员训练了一个模型,让同一段音乐的乐谱(MIDI)和音频在模型的『理解空间』里靠得很近——就像双语词典把两种语言的同一个词映射到同一个意思。\n【为什么值得关注】有了这种对齐,用音频搜乐谱、用乐谱搜音频都变得可行,自动转谱、跨模态检索都会受益。这是 MIR 领域很基础也很重要的一步。\n【怎么入手】看它用哪些下游任务验证对齐效果,这套评测方式可以直接借鉴到自己的项目里。"},
        {"sec": "papers", "tag": "评测", "date": "2026-07-23",
         "title": "示例:AI 伴奏与人耳偏好的大规模听测研究",
         "url": "https://arxiv.org/abs/2607.90003", "src": "arXiv",
         "orig": "A Large-Scale Listening Study of AI-Generated Accompaniment",
         "why": "上千人参与的盲听对比,量化 AI 伴奏与人类作品的差距。听测方法论值得学习。",
         "detail": "【这是什么】一项大规模盲听实验:让上千名听众在不知道来源的情况下对比 AI 生成的伴奏和人类编曲师的伴奏,量化两者的差距到底还有多大。\n【为什么值得关注】绝大多数生成研究只用自动指标,这篇用真人听测给出了更可信的答案,而且实验设计本身(怎么招募听众、怎么设计问题)就是做音乐评测研究的教科书。\n【怎么入手】重点读实验设计章节:样本怎么选、问题怎么问、统计怎么做。下次你做用户调研可以直接套用。"},
        {"sec": "papers", "tag": "音乐×视觉", "date": "2026-07-24",
         "title": "示例:节奏驱动的实时舞台灯光生成",
         "url": "https://arxiv.org/abs/2607.90004", "src": "arXiv",
         "orig": "Rhythm-Driven Real-Time Stage Lighting Generation",
         "why": "从音乐节拍和能量实时生成舞台灯光控制信号。Live House 和演出技术的直接结合。",
         "detail": "【这是什么】一个给演出自动打灯光的系统:实时分析音乐的节拍、段落和能量,输出灯光的颜色、运动、频闪控制信号,灯光师可以接手微调。\n【为什么值得关注】它把 MIR 技术(节拍跟踪、结构分析)接进了舞台灯光的工业协议,是音乐技术落地演出行业的典型案例,也展示了一条『分析→映射→控制』的作品开发路线。\n【怎么入手】看它如何把音乐特征映射成灯光参数——这张映射表就是你自己做音画作品时最需要设计的部分。"},
        {"sec": "oss", "tag": "音频处理", "date": "2026-07-24",
         "title": "示例:pedalboard-lite 浏览器端音频效果器链",
         "url": "https://github.com/example/pedalboard-lite", "src": "TS · 320★",
         "why": "把常见效果器搬到浏览器,免安装在线试用。适合做声音实验和教学演示。",
         "detail": "【这是什么】一个在网页里串效果器的开源工具:压缩、混响、延迟、失真等常见效果器像单块一样自由串联,上传音频或实时输入即可听到效果。\n【为什么值得关注】它把音频效果器从插件格式解放到浏览器,做声音实验、教学演示都不需要装任何软件。代码结构清晰,是学习 Web Audio 的好样本。\n【怎么入手】打开项目页面试玩几分钟,再读它的效果器实现源码——每个效果器都不长,很适合入门音频编程。"},
        {"sec": "oss", "tag": "MIR 工具", "date": "2026-07-24",
         "title": "示例:chordscan 自动和弦标注命令行工具",
         "url": "https://github.com/example/chordscan", "src": "Python · 156★",
         "why": "一键给歌曲标注和弦进行,输出带时间戳的 JSON。扒歌、和声分析都能提速。",
         "detail": "【这是什么】一个命令行小工具:给它一首歌的音频文件,它自动标注出整首歌的和弦进行,输出带精确时间戳的结果文件。\n【为什么值得关注】和弦识别是 MIR 的经典任务,这个工具把它做成了开箱即用的形态。扒歌、和声分析、构建数据集都能直接提速。\n【怎么入手】pip 安装后拿一首你熟悉的歌测试,对照你自己的和声听觉判断它的准确率——这个对比过程本身就是很好的练耳。"},
        {"sec": "industry", "tag": "版权", "date": "2026-07-24",
         "title": "示例要闻:主要唱片公司与 AI 音乐平台达成首批授权协议",
         "url": "https://example.com/news/label-ai-licensing-deal", "src": "示例科技媒体",
         "why": "多家唱片公司宣布与 AI 音乐平台达成训练数据授权协议,按使用量分成。行业从诉讼对抗转向授权合作,商业模式开始定型。",
         "hot": "行业要闻",
         "detail": "【这是什么】多家大型唱片公司与 AI 音乐生成平台宣布达成授权协议:AI 公司付费使用曲库训练模型,按生成量向版权方分成。这是行业首批大规模授权案例。\n【为什么值得关注】过去两年 AI 音乐的主旋律是诉讼,现在出现了『花钱买断合规』的新路径。授权模式一旦跑通,会直接影响 AI 音乐的成本结构和创业门槛。\n【怎么入手】持续关注协议的分成比例和覆盖范围;可以对比此前诉讼中双方的主张,看哪些妥协了、哪些守住了。"},
        {"sec": "industry", "tag": "产品", "date": "2026-07-23",
         "title": "示例:某 DAW 厂商发布 AI 编曲助手插件",
         "url": "https://example.com/news/daw-ai-assistant", "src": "示例媒体",
         "why": "传统宿主软件首次内置生成式编曲功能。AI 进入专业工作流的标志性一步。",
         "detail": "【这是什么】一家主流数字音频工作站(DAW)厂商发布了内置的 AI 编曲助手:在工程里选中几小节,它能建议配器、生成过渡段、补全和声。\n【为什么值得关注】此前 AI 音乐工具都是独立网站,这是第一次深度嵌入专业制作软件。AI 以『助手』而非『替代者』的姿态进入工作流,这个定位值得琢磨。\n【怎么入手】找评测视频看它实际生成的质量;想一想哪些环节你愿意交给它、哪些绝不——这个边界就是你的职业判断力。"},
    ],
    "ideas": [
        {"level": "入门", "kind": "工具", "title": "「和弦速查」练耳小工具",
         "body": "用 chordscan 给曲库批量标注和弦,做一个按和弦进行检索歌曲的练习工具。需要:Python 基础 · 命令行使用。",
         "based_on": [{"url": "https://github.com/example/chordscan", "title": "chordscan"}]},
        {"level": "进阶", "kind": "交互作品", "title": "网页效果器声音装置",
         "body": "基于 pedalboard-lite 的效果器链,做一个『观众动作改变效果参数』的网页声音装置。需要:JavaScript · Web Audio 基础。",
         "based_on": [{"url": "https://github.com/example/pedalboard-lite", "title": "pedalboard-lite"},
                      {"vol": 1, "url": "https://arxiv.org/abs/2607.13471", "title": "音乐驱动 360° 视频"}]},
        {"level": "硬核", "kind": "研究", "title": "中文歌 AI 伴奏听测研究",
         "body": "沿用大规模听测方法,构建中文流行歌 AI 伴奏盲听实验,对比开源与商业系统的差距。需要:实验设计 · 统计分析。",
         "based_on": [{"url": "https://arxiv.org/abs/2607.90003", "title": "AI 伴奏听测研究"},
                      {"vol": 1, "url": "https://arxiv.org/abs/2607.19688", "title": "AI 翻唱诊断评测"}]},
    ],
}


def build_prompt(archive, raw):
    items = archive.get("items", [])
    ideas = archive.get("ideas", [])
    known_urls = "\n".join(sorted({it.get("url", "") for it in items if it.get("url")})) or "(空)"
    known_ideas = json.dumps(
        [{"vol": i.get("vol"), "level": i.get("level"), "kind": i.get("kind"),
          "title": i.get("title"), "body": i.get("body")} for i in ideas[-30:]],
        ensure_ascii=False, indent=1)
    # 候选素材压缩:摘要截断,控制 token
    cand = []
    for name, arr in (raw.get("sources") or {}).items():
        for c in arr:
            c = dict(c)
            if isinstance(c.get("summary"), str):
                c["summary"] = c["summary"][:600]
            c["_from"] = name
            cand.append(c)
    candidates = json.dumps(cand, ensure_ascii=False, indent=1)
    return PROMPT_TMPL.format(known_urls=known_urls, known_ideas=known_ideas,
                              candidates=candidates)


def call_kimi(prompt, api_key):
    """调 Moonshot chat completions,120s 超时,失败重试 2 次。"""
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是「音乐科技雷达」的每日编辑,只输出符合契约的 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    last_err = None
    for attempt in range(3):  # 首次 + 重试 2 次
        try:
            req = urllib.request.Request(API_URL, data=body, method="POST", headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            })
            with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            last_err = exc
            print(f"[edit] API 调用失败(第 {attempt + 1} 次): {exc}", file=sys.stderr)
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError(f"Kimi API 调用连续失败: {last_err}")


def validate(issue, archive):
    """校验输出契约:可解析、字段齐全、hot 恰好一学术一行业、URL 与存档无重复。"""
    errs = []
    if not isinstance(issue, dict):
        raise ValueError("输出不是 JSON 对象")
    items, ideas = issue.get("items"), issue.get("ideas")
    if not isinstance(items, list) or not items:
        errs.append("items 缺失或为空")
        items = []
    if not isinstance(ideas, list) or not ideas:
        errs.append("ideas 缺失或为空")
        ideas = []

    known_urls = {it.get("url") for it in archive.get("items", [])}
    seen = set()
    hot_papers = hot_industry = 0
    for i, it in enumerate(items):
        for f in ("sec", "tag", "date", "title", "url", "src", "why", "detail"):
            if not it.get(f):
                errs.append(f"items[{i}] 缺字段 {f}")
        if it.get("sec") not in SECS:
            errs.append(f"items[{i}] sec 非法: {it.get('sec')}")
        url = it.get("url")
        if url in known_urls:
            errs.append(f"items[{i}] URL 与存档重复: {url}")
        if url in seen:
            errs.append(f"items[{i}] URL 在当期内部重复: {url}")
        seen.add(url)
        if it.get("hot") == "本报头条":
            hot_papers += 1
            if it.get("sec") != "papers":
                errs.append(f"items[{i}] 本报头条必须来自学术板块")
        elif it.get("hot") == "行业要闻":
            hot_industry += 1
            if it.get("sec") != "industry":
                errs.append(f"items[{i}] 行业要闻必须来自行业板块")
        elif "hot" in it:
            errs.append(f"items[{i}] hot 值非法: {it.get('hot')}")
        # detail 三段检查
        detail = it.get("detail") or ""
        for marker in ("【这是什么】", "【为什么值得关注】", "【怎么入手】"):
            if marker not in detail:
                errs.append(f"items[{i}] detail 缺少 {marker}")
    if hot_papers != 1:
        errs.append(f"本报头条应恰好 1 条,实际 {hot_papers}")
    if hot_industry != 1:
        errs.append(f"行业要闻应恰好 1 条,实际 {hot_industry}")

    for i, idea in enumerate(ideas):
        for f in ("level", "kind", "title", "body"):
            if not idea.get(f):
                errs.append(f"ideas[{i}] 缺字段 {f}")
        if idea.get("level") not in LEVELS:
            errs.append(f"ideas[{i}] level 非法: {idea.get('level')}")

    if errs:
        raise ValueError("输出校验未通过:\n" + "\n".join(f"  - {e}" for e in errs))
    return {"items": items, "ideas": ideas}


def main():
    ap = argparse.ArgumentParser(description="每日编辑:产出当期 issue.json")
    ap.add_argument("--mock", action="store_true", help="不调 API,产出内置假 issue")
    args = ap.parse_args()

    archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))

    if args.mock:
        issue = dict(MOCK_ISSUE)
        print("[edit] --mock 模式:使用内置假 issue(未调用 API)")
    else:
        api_key = os.environ.get("MOONSHOT_API_KEY")
        if not api_key:
            print("[edit] 错误:未设置环境变量 MOONSHOT_API_KEY", file=sys.stderr)
            sys.exit(1)
        if not RAW.exists():
            print(f"[edit] 错误:候选素材不存在 {RAW},请先运行 fetch_sources.py", file=sys.stderr)
            sys.exit(1)
        raw = json.loads(RAW.read_text(encoding="utf-8"))
        prompt = build_prompt(archive, raw)
        print(f"[edit] prompt {len(prompt)} 字符,调用 {MODEL} ...")
        content = call_kimi(prompt, api_key)
        try:
            issue = json.loads(content)
        except json.JSONDecodeError:
            print("[edit] 错误:API 输出不是合法 JSON,原始输出如下:", file=sys.stderr)
            print(content, file=sys.stderr)
            sys.exit(1)

    try:
        issue = validate(issue, archive)
    except ValueError as exc:
        print(f"[edit] {exc}", file=sys.stderr)
        print("[edit] 原始输出:", file=sys.stderr)
        print(json.dumps(issue, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(issue, ensure_ascii=False, indent=2), encoding="utf-8")
    n = {s: sum(1 for it in issue["items"] if it["sec"] == s) for s in SECS}
    print(f"[edit] 校验通过:学术 {n['papers']} · 开源 {n['oss']} · 行业 {n['industry']} · "
          f"选题 {len(issue['ideas'])} → {OUT}")


if __name__ == "__main__":
    main()
