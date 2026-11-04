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
SCORE_THRESHOLD = 8.5       # 统一录取分数线（>= 8.5分保留）
BATCH_SIZE = 8              # 每次打包 8 篇发给 AI
MAX_PER_FEED = 4            # 每个 RSS 源最多提取 4 篇高优候选
MAX_ARTICLES_PER_RUN = 20   # 每次定时任务总共最多送审 20 篇

DATA_FILE = "high_quality_news.json"
SEEN_FILE = "seen_urls.json"
STATUS_FILE = "status.json"

VALID_SUB_TOPICS = {
    "AI与硬科技": {"算力硬件", "模型应用", "财报资本", "宏观政经"},
    "影视文化": {"深度影评", "新片动向", "行业商业", "影视科技"},
}

# 主题与 RSS 源配置（AI与硬科技 + 影视文化 双版块并行）
TOPICS = {
    "AI与硬科技": [
        # 科技源1：严肃财经与深度科技媒体定向源
        "https://news.google.com/rss/search?q=(AI+OR+人工智能+OR+芯片+OR+算力+OR+半导体+OR+大模型)+(财新+OR+第一财经+OR+21世纪+OR+界面+OR+路透+OR+彭博+OR+经济观察报)+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 科技源2：网易新闻（163.com）硬科技报道（排除数码快讯转载）
        "https://news.google.com/rss/search?q=(AI+OR+芯片+OR+半导体+OR+算力+OR+大模型)+site:163.com+-快科技+-IT之家+-驱动之家+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 科技源3：全网硬科技核心事件源
        "https://news.google.com/rss/search?q=(AI芯片+OR+算力+OR+半导体+OR+晶圆+OR+HBM+OR+存储芯片)+(财报+OR+营收+OR+量产+OR+市占率+OR+良率+OR+资本开支)+-快科技+-IT之家+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "影视文化": [
        # 影视源1：深度影评、剧作分析与导演主创专访（源头屏蔽票房与娱乐八卦）
        "https://news.google.com/rss/search?q=(影评+OR+豆瓣+OR+导演+OR+编剧+OR+专访+OR+电影节+OR+戛纳+OR+奥斯卡+OR+剧集)+(深度+OR+叙事+OR+镜头+OR+主创+OR+美学+OR+创作)+-票房+-破亿+-排片+-绯闻+-恋情+-穿搭+when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 影视源2：国内外重磅新片/新剧动向与权威口碑前瞻
        "https://news.google.com/rss/search?q=(新片+OR+新剧+OR+定档+OR+首映+OR+美剧+OR+英剧+OR+韩剧+OR+Netflix+OR+HBO+OR+AppleTV+OR+院线)+(导演+OR+改编+OR+口碑+OR+烂番茄+OR+豆瓣+OR+电影节)+-票房+-破亿+-粉丝+-应援+-街拍+when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 影视源3：影视行业商业博弈与影视前沿科技（流媒体、制片成本、AI影视工业与虚拟制片）
        "https://news.google.com/rss/search?q=(影视+OR+好莱坞+OR+流媒体+OR+奈飞+OR+迪士尼+OR+爱奇艺+OR+腾讯视频+OR+电影工业)+(AI+OR+虚拟制片+OR+视效+OR+特效+OR+制作成本+OR+版权+OR+财报+OR+战略)+-票房+-涨停+-概念股+when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ]
}

# 信源白名单（抓取时自动排在队列最前面，优先享用配额）
VIP_SOURCES = re.compile(
    r"(财新|晚点|LatePost|第一财经|21世纪|界面|路透|彭博|Bloomberg|经济观察报|澎湃|毒眸|娱理|三联|新京报|虎嗅|36氪|芯东西)"
)

# 信源黑名单（命中直接丢弃）
SOURCE_BLACKLIST = re.compile(
    r"(百家号|营销号|股吧|彩票|算命|娱乐八卦|粉丝网|追星)"
)

# 1. 标题黑名单：拦截科技标题党、引战爽文、影视八卦粉圈词、以及票房/排片播报
TITLE_BLACKLIST = re.compile(
    r"(!|！|震惊|暴跌|崩盘|涨停|跌停|午评|收评|概念股|必看|彻底慌了|断崖式|ETF|掘金|龙头股|价值重估|满仓|飙升|"
    r"入选.*指数|斩获.*奖|荣获.*奖|掀桌|巧了|打脸|急了|亮剑|霸气|券商最新研判|早报（|"
    r"票房|排片|破\d+亿|恋情|绯闻|离婚|出轨|街拍|红毯|艳压|少女感|冻龄|颜值|撕番|应援|生图|演技炸裂|看哭)"
)

# 2. 正文开头黑名单：拦截数码快讯与发布会口水通稿
HEAD_BLACKLIST = re.compile(
    r"(快科技\s*\d+月\d+日|驱动之家|站长之家|太平洋科技|CNMO|IT之家.*现场消息|在今天的发布会上)"
)

# 3. 正文末尾黑名单：拦截文末夹带私货的 ETF/股票营销软文与单股增持评级
TAIL_BLACKLIST = re.compile(
    r"(基金有风险|投资需谨慎|风险提示：本文|不构成投资建议|ETF联接|代码：\d{6}|关注【|扫码领|投资评级：增持|投资评级：买入|维持“增持”|维持“买入”)"
)

MODEL_POOL = [
    {"provider": "gemini", "model": "gemini-3.6-flash"},
    {"provider": "groq",   "model": "openai/gpt-oss-120b"},
    {"provider": "groq",   "model": "qwen/qwen3.8-27b"},
    {"provider": "gemini", "model": "gemini-2.5-flash"},
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"},
    {"provider": "groq",   "model": "openai/gpt-oss-20b"},
]

# 双轨制 8.5分冷酷主编评分矩阵 + 原文核心原句摘录 Prompt
SYSTEM_PROMPT = """你是一位极其严苛、客观的硬科技、商业与严肃影视文化总编。请对输入的新闻列表进行独立质量打分（满分10分，支持小数如8.5、9.0），归类子版块，并摘录原文核心原句。

【双轨制 8.5分高分核心标准】：
▶ 轨道 A（适用于【AI与硬科技】全领域、以及【影视文化】中的行业商业/影视科技）：
1. 实质性新事实增量（30%）：围绕新发生的具体商业/技术事件（财报发布、供应链突破、AI影视技术落地、流媒体战略调整、并购融资、政策落地），而非旧闻拼凑。
2. 数据密度与横向基准（30%）：不仅有具体数字，还必须提供客观参照系（如市占率对比、同业财务/良率/成本对比、同比/环比核心指标）。
3. 一手信源与叙事克制（40%）：源自官方财报、权威机构、核心供应链或独家披露；摆事实列数据，不煽情不吹捧。

▶ 轨道 B（适用于【影视文化】中的深度影评、新片动向）：
1. 深度影评与主创专访（≥8.5分标准）：必须具备扎实的剧作文本细读（叙事结构、人物弧光、镜头调度/视听语言分析、导演作者性演变或时代社会议题剖析），逻辑严密、观点独立有深度；或为导演/编剧/制片人干货极密的一手幕后创作专访。
2. 新片/新剧动向（≥8.5分标准）：围绕真正具有艺术或行业标杆意义的国内外院线新片/流媒体新剧（如三大电影节/奥斯卡动向、名导新作、高口碑剧集），提供详实的创作背景、主创脉络或权威媒体/场刊/豆瓣/烂番茄专业口碑参照。

【一票否决与封顶红线（严格执行！）】：
- 【事件级去重铁律（打 0.0 分）】：若候选文章与《近期已发布新闻清单》或同批次其他文章属同一具体事件，**只保留信息最全面、最深刻的那 1 篇**，其余重复事件文章一律打 0.0 分，reason 写“同事件重复报道”。
- 【票房播报一票否决（最高 5.0 分）】：读者明确不关心票房数据！凡是以院线票房数字播报、排片占比、周末票房榜、“票房破X亿”喜报为核心的文章，一律最高 5.0 分淘汰！
- 【娱乐八卦/粉圈吹捧/注水剧情复述（打 0.0~5.0 分）】：明星恋情绯闻、红毯穿搭、粉圈控评（“演技炸裂、全员封神”）、片方无脑宣发通稿、或单纯按时间线复述剧情而无深度剧作分析的解说文，一律淘汰！
- 【自媒体引战体/单一中小个股增持吹票研报/厂商发布会PPT通稿/地方政绩稿（最高 7.5 分）】：一律不予通过！

【子版块严格四选一规则（sub_topic 字段）】：
- 若文章所属领域为 `AI与硬科技`，请严格从以下 4 个词中选 1 个：
  "算力硬件" | "模型应用" | "财报资本" | "宏观政经"
- 若文章所属领域为 `影视文化`，请严格从以下 4 个词中选 1 个：
  "深度影评" | "新片动向" | "行业商业" | "影视科技"

【原文核心原句摘录规则（key_quotes 字段）】：
- 对于评分 >= 8.5 的文章，请直接从正文中**一字不改地摘抄 1~2 句最核心的数据原句或核心论断原话**（控制在 60~140 字以内，绝不要自己改写或总结！）。若评分 < 8.5，key_quotes 填空字符串 "" 即可。

请严格输出 JSON 格式（不要输出任何多余文字），格式如下：
{
  "results": [
    {
      "id": 0,
      "score": 9.0,
      "sub_topic": "算力硬件",
      "key_quotes": "正文原句摘录...",
      "reason": "简明扼要写出打分依据或淘汰原因"
    }
  ]
}"""


# ================= 2. 辅助与分类回填工具函数 =================
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

def fallback_sub_topic(topic, title, snippet, reason):
    text = f"{title} {snippet} {reason}"
    if topic == "影视文化":
        if re.search(r"(AI|虚拟制片|特效|视效|LED棚|IMAX|杜比|后期|渲染|数字人|生成式|技术)", text):
            return "影视科技"
        if re.search(r"(财报|营收|利润|订阅|会员|奈飞|Netflix|迪士尼|爱奇艺|腾讯视频|出品|成本|版权|并购|罢工|商业)", text):
            return "行业商业"
        if re.search(r"(定档|预告|首映|开机|杀青|立项|片单|戛纳|威尼斯|柏林|奥斯卡|艾美奖|新片|新剧|开播)", text):
            return "新片动向"
        return "深度影评"
    else:
        if re.search(r"(进出口|海关总署|数据局|美联储|利率|央行|自主可控|乌兰察布|冷焦虑|出口管制|掀桌|关税|国家标准)", text):
            return "宏观政经"
        if re.search(r"(财报|三季报|季报|Q3|Q4|营收|净利|利润|毛利率|IPO|招股书|估值|并购|收购|持仓|张坤|次贷|现金流|回购|分红|市盈率|增持|主力资金|闯关创业板|资本开支)", text):
            return "财报资本"
        if re.search(r"(芯片|半导体|晶圆|台积电|CoWoS|封装|HBM|内存|DRAM|存储|闪存|光模块|光互联|液冷|买电|电力设备|EDA|氮化镓|星闪|手机出货|端侧SoC|征程7|服务器)", text):
            return "算力硬件"
        return "模型应用"

def is_similar_title(new_title, existing_titles, threshold=0.42):
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
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

    history_block = "无"
    if recent_accepted_titles:
        history_block = "\n".join([f"- {t}" for t in recent_accepted_titles[:15]])

    article_blocks = []
    for idx, art in enumerate(batch_articles):
        body = art["body"]
        if len(body) > 1200:
            sliced_body = body[:850] + "\n...[中间省略]...\n" + body[-350:]
        else:
            sliced_body = body
        article_blocks.append(
            f"【候选文章 ID: {idx}】\n所属领域：{art['topic']}\n标题：{art['title']}\n来源：{art['source']}\n正文切片：\n{sliced_body}\n"
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

    # 为存量历史文章自动补齐 sub_topic 字段
    for item in saved_news:
        t_name = item.get("topic", "AI与硬科技")
        valid_set = VALID_SUB_TOPICS.get(t_name, VALID_SUB_TOPICS["AI与硬科技"])
        if item.get("sub_topic") not in valid_set:
            item["sub_topic"] = fallback_sub_topic(
                t_name, item.get("title", ""), item.get("snippet", ""), item.get("reason", "")
            )

    recent_titles = [item.get("title", "") for item in saved_news[:30]]
    candidates = []
    scanned_count = 0
    local_filtered_count = 0

    print("🔍 Step 1: 开始按【AI与硬科技 + 影视文化】均衡配额拉取 RSS 并进行本地粗筛...")
    for topic, urls in TOPICS.items():
        for feed_idx, rss_url in enumerate(urls, 1):
            feed = feedparser.parse(rss_url)
            # VIP_SOURCES 白名单信源优先排在前面，优先获得配额
            sorted_entries = sorted(
                feed.entries,
                key=lambda x: 0 if VIP_SOURCES.search(x.get("title", "")) else 1
            )
            feed_count = 0
            print(f"  📡 正在扫描 [{topic}] 源 #{feed_idx} (共 {len(sorted_entries)} 条条目，VIP信源已提权)...")

            for entry in sorted_entries:
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

                scanned_count += 1

                # 信源黑名单拦截
                if SOURCE_BLACKLIST.search(source):
                    print(f"    [本地拦截-信源黑名单({source})] {title[:25]}...")
                    seen_ids.add(title_hash)
                    local_filtered_count += 1
                    continue

                # 标题黑名单拦截
                if TITLE_BLACKLIST.search(title):
                    print(f"    [本地拦截-标题黑名单] {title[:28]}...")
                    seen_ids.add(title_hash)
                    local_filtered_count += 1
                    continue

                # 同事件标题近似度拦截
                all_known_titles = recent_titles + [c["title"] for c in candidates]
                if is_similar_title(title, all_known_titles):
                    print(f"    [本地拦截-同事件近似标题] {title[:28]}...")
                    seen_ids.add(title_hash)
                    local_filtered_count += 1
                    continue

                real_url, body = decode_and_extract(link)
                seen_ids.add(title_hash)

                if len(body) < 450:
                    print(f"    [本地拦截-正文过短({len(body)}字)] {title[:25]}...")
                    local_filtered_count += 1
                    continue

                if HEAD_BLACKLIST.search(body[:120]):
                    print(f"    [本地拦截-快讯/发布会通稿] {title[:25]}...")
                    local_filtered_count += 1
                    continue

                if TAIL_BLACKLIST.search(body[-350:]):
                    print(f"    [本地拦截-文末软文/荐股评级] {title[:25]}...")
                    local_filtered_count += 1
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
    last_used_model = "无需调用 (本轮无新候选)"

    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]
        scores_list, used_model = call_llm_with_fallback(batch, recent_titles)
        last_used_model = used_model

        score_map = {item.get("id"): item for item in scores_list if isinstance(item, dict)}

        for idx, art in enumerate(batch):
            res = score_map.get(idx)
            if not res:
                continue
            score = float(res.get("score", 0))
            reason = res.get("reason", "")
            key_quotes = (res.get("key_quotes") or "").strip()
            t_name = art["topic"]
            sub_topic = (res.get("sub_topic") or "").strip()
            if sub_topic not in VALID_SUB_TOPICS.get(t_name, set()):
                sub_topic = fallback_sub_topic(t_name, art["title"], art["snippet"], reason)

            if score >= SCORE_THRESHOLD:
                recent_titles.insert(0, art["title"])
                print(f"  🌟 [入选! {score}分 | {t_name} › {sub_topic}] {art['title']} ({art['source']})")
                saved_news.insert(0, {
                    "topic": t_name,
                    "sub_topic": sub_topic,
                    "title": art["title"],
                    "source": art["source"],
                    "url": art["url"],
                    "pub_date": art["pub_date"],
                    "snippet": art["snippet"],
                    "key_quotes": key_quotes,
                    "body": art["body"],  # 保存无广告纯净正文供前端直接展开阅读
                    "score": score,
                    "reason": reason,
                    "model": used_model,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                })
                newly_accepted += 1
            else:
                print(f"  🗑️ [淘汰 {score}分 | {t_name}] {art['title'][:22]}... | 原因: {reason[:38]}...")

        if i + BATCH_SIZE < len(candidates):
            time.sleep(6)

    # 保存文章数据与已读账本
    save_json(DATA_FILE, saved_news[:250])
    save_json(SEEN_FILE, list(seen_ids)[-2500:])

    # 保存后台运行健康状态供前端顶部状态栏展示
    status_data = {
        "last_run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scanned": scanned_count,
        "local_filtered": local_filtered_count,
        "ai_evaluated": len(candidates),
        "accepted": newly_accepted,
        "model": last_used_model,
        "healthy": (last_used_model != "none")
    }
    save_json(STATUS_FILE, status_data)
    print(f"🎉 运行结束！本次新增 {newly_accepted} 篇高质量（>={SCORE_THRESHOLD}分）新闻。")

if __name__ == "__main__":
    main()
