import os
import re
import json
import time
import hashlib
import requests
import feedparser
import trafilatura
from datetime import datetime, timezone
from googlenewsdecoder import gnewsdecoder

# ================= 1. 核心配置区 =================
SCORE_THRESHOLD = 8.5       # 录取分数线（>= 8.5分才保留）
BATCH_SIZE = 8              # 每次打包 8 篇发给 AI（既省 API 请求次数，又方便 AI 在同批次内做事件去重）
MAX_PER_FEED = 6            # 每个 RSS 源最多提取 6 篇候选，防止单一信源垄断名额
MAX_ARTICLES_PER_RUN = 16   # 每次定时任务总共最多送审 16 篇

DATA_FILE = "high_quality_news.json"
SEEN_FILE = "seen_urls.json"

# 主题与 RSS 源配置（已加入 -快科技 -IT之家 源头降噪，并实现多源均衡配额）
TOPICS = {
    "AI与硬科技": [
        # 源1：严肃财经与深度科技媒体定向源
        "https://news.google.com/rss/search?q=(AI+OR+人工智能+OR+芯片+OR+算力+OR+半导体+OR+大模型)+(财新+OR+第一财经+OR+21世纪+OR+界面+OR+路透+OR+彭博+OR+经济观察报)+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 源2：网易新闻（163.com）硬科技报道（排除数码快讯转载）
        "https://news.google.com/rss/search?q=(AI+OR+芯片+OR+半导体+OR+算力+OR+大模型)+site:163.com+-快科技+-IT之家+-驱动之家+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 源3：全网硬科技核心事件源（聚焦财报、流片、产能、并购与行业数据）
        "https://news.google.com/rss/search?q=(AI芯片+OR+算力+OR+半导体+OR+晶圆+OR+HBM+OR+存储芯片)+(财报+OR+营收+OR+量产+OR+市占率+OR+良率+OR+资本开支)+-快科技+-IT之家+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ]
}

# 1. 标题黑名单：含感叹号、情绪词、炒股词、或典型单一公司公关喜报词，直接秒杀
TITLE_BLACKLIST = re.compile(
    r"(!|！|震惊|暴跌|崩盘|涨停|跌停|午评|收评|概念股|必看|彻底慌了|断崖式|ETF|掘金|龙头股|价值重估|满仓|飙升|入选.*指数|斩获.*奖|荣获.*奖)"
)

# 2. 正文开头黑名单：拦截数码网站拆条快讯与发布会口水通稿（检查正文前 120 字）
HEAD_BLACKLIST = re.compile(
    r"(快科技\s*\d+月\d+日|驱动之家|站长之家|太平洋科技|CNMO|IT之家.*现场消息|在今天的发布会上)"
)

# 3. 正文末尾黑名单：拦截文末夹带私货的 ETF/股票营销软文（检查正文后 350 字）
TAIL_BLACKLIST = re.compile(
    r"(基金有风险|投资需谨慎|风险提示：本文|不构成投资建议|ETF联接|代码：\d{6}|关注【|扫码领)"
)

# 多模型自动故障转移池（未配置 GROQ_API_KEY 时会自动跳过 groq 节点，后续添加 Key 自动生效）
MODEL_POOL = [
    {"provider": "gemini", "model": "gemini-3.6-flash"},      # 主力首选：高智商、大上下文、已验证可用
    {"provider": "groq",   "model": "openai/gpt-oss-120b"},   # Groq 120B 旗舰（配置 GROQ_API_KEY 后激活）
    {"provider": "groq",   "model": "qwen/qwen3.8-27b"},      # Groq 中文强模型（配置 GROQ_API_KEY 后激活）
    {"provider": "gemini", "model": "gemini-2.5-flash"},      # Gemini 次选
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"}, # Gemini 极速轻量保底
    {"provider": "groq",   "model": "openai/gpt-oss-20b"},    # Groq 极速保底
]

# 8.5分冷酷主编评分矩阵 Prompt（新增跨批次事件去重 & 严打发布会 PPT 通稿）
SYSTEM_PROMPT = """你是一位极其严苛、客观的硬科技与财经新闻总编。请对输入的新闻列表进行独立质量打分（满分10分，支持小数如8.5、9.0）。

【高分核心标准（决定能否上 8.5 分）】：
1. 实质性新事实增量（30%）：围绕新发生的具体客观商业/技术事件（如财报发布、核心供应链突破、明确金额的并购/资本开支、重大政策落地），而非旧闻综述。
2. 数据密度与横向基准（30%）：不仅有具体数字，还必须提供客观参照系（如第三方机构市占率对比、同业公司财务/良率对比、同比/环比核心指标、分析师预期对比），具备深度可思考性。
3. 一手信源与多方印证（20%）：源自官方财报、监管文件、权威调研机构（如IDC、Counterpoint、彭博、路透）或核心供应链独家披露。
4. 叙事克制与价值中立（20%）：摆事实列数据，不替读者下结论，不强行煽情或点评企业家性格。

【一票否决与封顶红线（严格执行！）】：
- 【事件级去重铁律（打 0.0 分）】：如果某篇候选文章与我提供的《近期已发布新闻清单》属于同一个具体事件（例如同一家公司的同一份财报、同一场发布会），或者当前批次内有多篇文章报道同一事件，**只允许保留信息最全面、数据最客观的那 1 篇**，其余重复事件文章必须全部打 0.0 分，并在 reason 中注明“同事件重复报道”。
- 【厂商发布会 PPT 通稿封顶 7.5 分】：单一厂商新品发布会的单方参数罗列（照抄厂商发布会宣传口径如“性能提升100%”、“算力XX TOPS”，缺乏第三方独立测试或行业客观审视），最高不得超过 7.5 分！
- 【单一企业公关喜报封顶 7.0 分】：以某一家公司入选某指数、某榜单、荣获某奖项为主角的企业公关通稿（IR/PR稿），即使附带了公司财报数据，最高不得超过 7.0 分！
- 【主观注水综述封顶 7.0 分】：事实骨架单薄，却展开大量主观评论、讲故事的文章，最高 7.0 分。
- 【软文与标题党封顶 5.0 分】：夹带基金/股票推荐或情绪化博眼球，最高 5.0 分。

请严格输出 JSON 格式（不要输出任何多余文字），格式如下：
{
  "results": [
    {
      "id": 0,
      "score": 9.0,
      "reason": "简明扼要写出打分依据或淘汰原因"
    }
  ]
}"""


# ================= 2. 辅助与去重工具函数 =================
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def make_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]

def is_similar_title(new_title, existing_titles, threshold=0.42):
    """计算标题字词重合度（拦截同一事件换标题重发）"""
    tokens_new = set(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", new_title.lower()))
    if len(tokens_new) < 4:
        return False
    for old_title in existing_titles:
        tokens_old = set(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", old_title.lower()))
        if not tokens_old:
            continue
        overlap = len(tokens_new & tokens_old) / min(len(tokens_new), len(tokens_old))
        if overlap >= threshold:
            return True
    return False

def decode_and_extract(gnews_url):
    """解码 Google News 加密链接并提取干净的正文"""
    real_url = gnews_url
    if "news.google.com" in gnews_url:
        try:
            res = gnewsdecoder(gnews_url, interval=0.5)
            if res.get("status") or res.get("success"):
                real_url = res.get("decoded_url", gnews_url)
        except Exception as e:
            print(f"  [解码跳过] {e}")
            return real_url, ""

    try:
        downloaded = trafilatura.fetch_url(real_url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            return real_url, (text or "").strip()
    except Exception as e:
        print(f"  [抓取异常] {e}")
    return real_url, ""


# ================= 3. 多模型轮询调用函数 =================
def call_llm_with_fallback(batch_articles, recent_accepted_titles):
    """将一批文章打包发给模型池，附带近期已发布标题清单供 AI 跨批次去重"""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

    # 构建近期已入选新闻清单（供 AI 识别同一事件）
    history_block = "无"
    if recent_accepted_titles:
        history_block = "\n".join([f"- {t}" for t in recent_accepted_titles[:15]])

    # 构建打包输入文本（首尾切片法）
    article_blocks = []
    for idx, art in enumerate(batch_articles):
        body = art["body"]
        if len(body) > 1200:
            sliced_body = body[:850] + "\n...[中间省略]...\n" + body[-350:]
        else:
            sliced_body = body
        article_blocks.append(
            f"【候选文章 ID: {idx}】\n标题：{art['title']}\n来源：{art['source']}\n正文切片：\n{sliced_body}\n"
        )

    user_prompt = (
        f"《近期已发布新闻清单（若候选文章与以下清单属同一具体事件，请直接打 0.0 分淘汰）》：\n{history_block}\n\n"
        f"====================\n\n"
        + "\n====================\n".join(article_blocks)
    )

    for candidate in MODEL_POOL:
        provider = candidate["provider"]
        model_name = candidate["model"]

        if provider == "gemini" and not gemini_key:
            continue
        if provider == "groq" and not groq_key:
            continue

        if provider == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            api_key = gemini_key
        else:
            url = "https://api.groq.com/openai/v1/chat/completions"
            api_key = groq_key

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        try:
            print(f"🤖 尝试调用 [{provider.upper()}] {model_name} 评审 {len(batch_articles)} 篇文章...")
            resp = requests.post(url, headers=headers, json=payload, timeout=50)

            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                content = re.sub(r"^```json\s*|\s*```$", "", content.strip())
                parsed = json.loads(content)
                print(f"✅ [{model_name}] 评审成功！")
                return parsed.get("results", []), f"{provider}:{model_name}"
            else:
                print(f"⚠️ [{model_name}] 状态码 {resp.status_code}: {resp.text[:100]} -> 切换下一个模型...")
                time.sleep(1)
        except Exception as e:
            print(f"⚠️ [{model_name}] 调用异常: {e} -> 切换下一个模型...")
            time.sleep(1)

    print("❌ 所有可用模型均调用失败，请检查 API Key。")
    return [], "none"


# ================= 4. 主流水线 =================
def main():
    seen_ids = set(load_json(SEEN_FILE, []))
    saved_news = load_json(DATA_FILE, [])
    recent_titles = [item.get("title", "") for item in saved_news[:30]]
    candidates = []

    print("🔍 Step 1: 开始按多信源均衡配额拉取 RSS 并进行本地粗筛...")
    for topic, urls in TOPICS.items():
        for feed_idx, rss_url in enumerate(urls, 1):
            feed = feedparser.parse(rss_url)
            feed_count = 0
            print(f"  📡 正在扫描 [{topic}] 源 #{feed_idx} (共 {len(feed.entries)} 条条目)...")

            for entry in feed.entries:
                if feed_count >= MAX_PER_FEED or len(candidates) >= MAX_ARTICLES_PER_RUN:
                    break

                raw_title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                pub_date = entry.get("published", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

                source = "未知来源"
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title, source = parts[0].strip(), parts[1].strip()

                title_hash = make_hash(re.sub(r"\W+", "", title)[:16])
                if title_hash in seen_ids:
                    continue

                # 拦截1：标题黑名单（含感叹号、情绪词、入选指数等公关词）
                if TITLE_BLACKLIST.search(title):
                    print(f"    [本地拦截-标题黑名单] {title[:28]}...")
                    seen_ids.add(title_hash)
                    continue

                # 拦截2：本地标题相似度去重（防止同一发布会/同一事件拆条洗版）
                all_known_titles = recent_titles + [c["title"] for c in candidates]
                if is_similar_title(title, all_known_titles):
                    print(f"    [本地拦截-同事件近似标题] {title[:28]}...")
                    seen_ids.add(title_hash)
                    continue

                # 解码并提取正文
                real_url, body = decode_and_extract(link)
                seen_ids.add(title_hash)

                # 拦截3：正文字数过短（提高门槛至 450 字）
                if len(body) < 450:
                    print(f"    [本地拦截-正文过短({len(body)}字)] {title[:25]}...")
                    continue

                # 拦截4：数码快讯与发布会口水通稿（检查前 120 字）
                if HEAD_BLACKLIST.search(body[:120]):
                    print(f"    [本地拦截-快讯/发布会通稿] {title[:25]}...")
                    continue

                # 拦截5：文末软文/ETF推广（检查后 350 字）
                if TAIL_BLACKLIST.search(body[-350:]):
                    print(f"    [本地拦截-文末软文推广] {title[:25]}...")
                    continue

                candidates.append({
                    "id_hash": title_hash,
                    "topic": topic,
                    "title": title,
                    "source": source,
                    "url": real_url,
                    "pub_date": pub_date,
                    "body": body,
                    "snippet": body[:140].replace("\n", " ") + "..."
                })
                feed_count += 1

    print(f"📦 Step 2: 本地严筛完成，共选出 {len(candidates)} 篇高潜力候选文章进入 AI 终审。")

    newly_accepted = 0
    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]
        scores_list, used_model = call_llm_with_fallback(batch, recent_titles)

        score_map = {item.get("id"): item for item in scores_list if isinstance(item, dict)}

        for idx, art in enumerate(batch):
            res = score_map.get(idx)
            if not res:
                continue
            score = float(res.get("score", 0))
            reason = res.get("reason", "")

            if score >= SCORE_THRESHOLD:
                # 终审通过后，再次把该标题加入 recent_titles，供下一批次去重参考
                recent_titles.insert(0, art["title"])
                print(f"  🌟 [入选! {score}分] {art['title']} ({art['source']})")
                saved_news.insert(0, {
                    "topic": art["topic"],
                    "title": art["title"],
                    "source": art["source"],
                    "url": art["url"],
                    "pub_date": art["pub_date"],
                    "snippet": art["snippet"],
                    "score": score,
                    "reason": reason,
                    "model": used_model,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                })
                newly_accepted += 1
            else:
                print(f"  🗑️ [淘汰 {score}分] {art['title'][:22]}... | 原因: {reason[:38]}...")

        if i + BATCH_SIZE < len(candidates):
            time.sleep(6)

    save_json(DATA_FILE, saved_news[:200])
    save_json(SEEN_FILE, list(seen_ids)[-2000:])
    print(f"🎉 运行结束！本次新增 {newly_accepted} 篇高质量（>={SCORE_THRESHOLD}分）新闻。")

if __name__ == "__main__":
    main()
