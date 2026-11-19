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
SCORE_THRESHOLD = 8.5         # 统一录取分数线（>= 8.5分保留）
BATCH_SIZE = 8                # 每次打包 8 篇发给 AI
MAX_PER_FEED = 3              # 每个 RSS 源单次最多提取 3 篇候选
MAX_ARTICLES_PER_RUN = 24     # 每次定时任务总共最多送审 24 篇（跨门类发牌式轮询抽取，最多3次API调用）
MAX_SAVED_PER_TOPIC = 50      # 每个门类独立保留最新 50 篇（保护冷门门类永远不会被高频门类冲掉！）
MAX_BODY_CHARS = 3500         # 保存正文最大字符数（控体积保速度）

DATA_FILE = "high_quality_news.json"
SEEN_FILE = "seen_urls.json"
STATUS_FILE = "status.json"

VALID_SUB_TOPICS = {
    "AI与硬科技": ["算力硬件", "模型应用", "财报资本", "宏观政经"],
    "宏观与金融": ["央行宏观", "股债汇商", "巨头并购", "金融风险"],
    "国际与地缘": ["贸易关税", "法案管制", "能源矿产", "国际政局"],
    "新能源与制造": ["智驾车企", "电力储能", "航天低空", "出海制造"],
    "影视文化": ["深度影评", "新片动向", "行业商业", "影视科技"],
    "前沿科学": ["前沿科学"],
    "科幻小说": ["科幻小说"],
}

# 7 大新闻门类 RSS 源配置
TOPICS = {
    "AI与硬科技": [
        "https://news.google.com/rss/search?q=(AI+OR+人工智能+OR+芯片+OR+算力+OR+半导体+OR+大模型)+(财新+OR+第一财经+OR+21世纪+OR+界面+OR+路透+OR+彭博+OR+经济观察报)+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(AI+OR+芯片+OR+半导体+OR+算力+OR+大模型)+site:163.com+-快科技+-IT之家+-驱动之家+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(AI芯片+OR+算力+OR+半导体+OR+晶圆+OR+HBM+OR+存储芯片)+(财报+OR+营收+OR+量产+OR+市占率+OR+良率+OR+资本开支)+-快科技+-IT之家+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "宏观与金融": [
        "https://news.google.com/rss/search?q=(美联储+OR+央行+OR+利率+OR+通胀+OR+CPI+OR+PMI+OR+社融+OR+财政+OR+国债)+(财新+OR+第一财经+OR+21世纪+OR+路透+OR+彭博+OR+华尔街)+-午评+-收评+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(美债+OR+汇率+OR+黄金+OR+原油+OR+大宗商品+OR+主权基金+OR+并购+OR+财报)+(高盛+OR+摩根+OR+彭博+OR+路透+OR+财新+OR+第一财经)+-涨停+-概念股+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "国际与地缘": [
        "https://news.google.com/rss/search?q=(关税+OR+贸易+OR+出口管制+OR+实体清单+OR+制裁+OR+反垄断+OR+法案)+(路透+OR+彭博+OR+联合早报+OR+财新+OR+第一财经+OR+新华社)+-掀桌+-彻底慌了+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(地缘+OR+供应链+OR+关键矿产+OR+稀土+OR+航运+OR+能源+OR+外交+OR+欧盟+OR+东盟)+(路透+OR+彭博+OR+联合早报+OR+财新+OR+界面)+-爽文+-打脸+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "新能源与制造": [
        "https://news.google.com/rss/search?q=(智能驾驶+OR+自动驾驶+OR+新能源车+OR+固态电池+OR+储能+OR+电网+OR+核电)+(财报+OR+市占率+OR+量产+OR+出海+OR+产能+OR+晚点+OR+财新+OR+第一财经)+-快科技+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(商业航天+OR+卫星+OR+火箭+OR+SpaceX+OR+低空经济+OR+机器人+OR+出海建厂)+(量产+OR+发射+OR+订单+OR+营收+OR+供应链)+-概念股+-涨停+when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "影视文化": [
        "https://news.google.com/rss/search?q=(影评+OR+豆瓣+OR+导演+OR+编剧+OR+专访+OR+电影节+OR+戛纳+OR+奥斯卡+OR+剧集)+(深度+OR+叙事+OR+镜头+OR+主创+OR+美学+OR+创作)+-票房+-破亿+-排片+-绯闻+-恋情+when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(新片+OR+新剧+OR+定档+OR+首映+OR+美剧+OR+英剧+OR+Netflix+OR+HBO+OR+流媒体+OR+好莱坞)+(导演+OR+改编+OR+口碑+OR+虚拟制片+OR+AI+OR+制作成本+OR+战略)+-票房+-粉丝+-街拍+when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "前沿科学": [
        "https://news.google.com/rss/search?q=(Nature+OR+Science+OR+自然杂志+OR+科学杂志+OR+中科院+OR+韦伯望远镜+OR+深空探测+OR+天体物理)+(突破+OR+论文+OR+发现+OR+实验+OR+观测)+-养生+-震惊+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(基因编辑+OR+脑机接口+OR+神经科学+OR+临床试验+OR+创新药+OR+可控核聚变+OR+量子计算)+(突破+OR+论文+OR+临床+OR+数据+OR+科学家+OR+专访)+-概念股+-涨停+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ],
    "科幻小说": [
        "https://news.google.com/rss/search?q=(科幻小说+OR+科幻文学+OR+科幻作家+OR+雨果奖+OR+星云奖+OR+银河奖+OR+科幻世界)+(书评+OR+新作+OR+出版+OR+专访+OR+刘慈欣+OR+特德姜+OR+陈楸帆+OR+郝景芳)+-爽文+-书荒+-免费阅读+-最新章节+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=(硬科幻+OR+科幻小说+OR+科幻文学+OR+未来事务管理局)+(叙事+OR+设定+OR+世界观+OR+宇宙+OR+哲学+OR+思想+OR+文学+OR+三联+OR+界面+OR+新京报+OR+澎湃+OR+豆瓣)+-网文+-系统流+-重生+-起点+-番茄小说+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ]
}

VIP_SOURCES = re.compile(
    r"(财新|晚点|LatePost|第一财经|21世纪|界面|路透|彭博|Bloomberg|联合早报|经济观察报|澎湃|毒眸|娱理|三联|新京报|虎嗅|36氪|芯东西|科幻世界|未来事务管理局)"
)

SOURCE_BLACKLIST = re.compile(
    r"(百家号|营销号|股吧|彩票|算命|娱乐八卦|粉丝网|追星|笔趣阁|起点中文|番茄小说)"
)

TITLE_BLACKLIST = re.compile(
    r"(!|！|震惊|暴跌|崩盘|涨停|跌停|午评|收评|概念股|必看|彻底慌了|断崖式|ETF|掘金|龙头股|价值重估|满仓|飙升|"
    r"入选.*指数|斩获.*奖|荣获.*奖|掀桌|巧了|打脸|急了|亮剑|霸气|赢麻了|券商最新研判|早报（|"
    r"票房|排片|破\d+亿|恋情|绯闻|离婚|出轨|街拍|红毯|艳压|少女感|冻龄|颜值|撕番|应援|生图|演技炸裂|看哭|"
    r"书荒|爽文|系统流|无限流|末世囤货|重生|穿越|修仙|完本|免费阅读|最新章节|TXT下载|笔趣阁)"
)

HEAD_BLACKLIST = re.compile(
    r"(快科技\s*\d+月\d+日|驱动之家|站长之家|太平洋科技|CNMO|IT之家.*现场消息|在今天的发布会上)"
)

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

SYSTEM_PROMPT = """你是一位极其严苛、客观的跨领域总编（覆盖硬科技、宏观金融、国际政经、新能源制造、严肃影视、前沿科学与科幻文学）。请对输入的新闻列表进行独立质量打分（满分10分，支持小数如8.5、9.0），按每篇文章指定的合法选项归类 `sub_topic`，并摘录原文核心原句。

【8.5分高分核心标准】：
▶ 轨道 A（适用于【AI与硬科技】、【宏观与金融】、【国际与地缘】、【新能源与制造】、以及【影视文化】的商业/科技）：
1. 实质性新事实增量（30%）：围绕新发生的具体商业/技术/政经事件（财报、央行决议、宏观统计指标、具体法案/关税细则、产能突破、重大并购），而非旧闻拼凑或空洞社论。
2. 数据密度与横向基准（30%）：不仅有具体数字，还必须提供客观参照系（同比/环比/预期差、市占率对比、同业财务/良率/成本对比、具体税率或金额）。
3. 一手信源与叙事克制（40%）：源自官方统计局/央行/财报、权威机构（路透、彭博、财新、IDC等）或核心供应链披露；克制中立，绝不煽情。

▶ 轨道 B（适用于【前沿科学】）：
1. 源自顶级学术期刊（Nature/Science/Cell/NEJM等）、权威科研机构或临床试验一手数据，清晰阐述科学机理、实验量化结果与真实突破边界，严禁夸大疗效或伪科学。

▶ 轨道 C（适用于【影视文化】的深度影评/新片动向、以及【科幻小说】）：
1. 必须具备扎实的文本细读（剧作/小说叙事结构、世界观与科学设定内核、视听美学或社会哲学剖析）、或主创/科幻作家干货极密的一手专访、或国际权威电影节/科幻大奖（雨果/星云/银河奖）深度解读。

【一票否决与封顶红线（严格执行！）】：
- 【事件级去重铁律（打 0.0 分）】：若候选文章与《近期已发布新闻清单》或同批次其他文章属同一具体事件，**只保留信息最全面、最深刻的那 1 篇**，其余重复事件文章一律打 0.0 分，reason 写“同事件重复报道”。
- 【自媒体情绪爽文/军事地缘引战文（最高 4.0 分）】：国际、政治、科技新闻中凡带有“彻底慌了、掀桌、打脸、赢麻了、霸气反击”等自媒体情绪宣泄色彩的，一律淘汰！
- 【股市每日盘面播报/单股吹票研报/厂商发布会PPT通稿（最高 7.5 分）】：A股午评收评、板块异动快讯、针对单一中小个股的“买入/增持”推荐稿、照抄厂商发布会PPT的单方宣传稿，一律淘汰！
- 【票房播报/娱乐八卦/网文书荒推荐（最高 4.0 分）】：院线票房与排片播报、明星八卦粉圈控评、注水剧情复述、网络爽文推书帖，一律淘汰！

【子版块归类铁律（sub_topic 字段）】：
- 每篇候选文章头部均标注了它唯一允许使用的 `合法子版块选项`，请严格从中选择 1 个原样填入 `sub_topic`！

【原文核心原句摘录规则（key_quotes 字段）】：
- 对于评分 >= 8.5 的文章，请直接从正文中**一字不改地摘抄 1~2 句最核心的数据原句或核心论断原话**（控制在 60~140 字以内，绝不要改写或总结！）。若评分 < 8.5，key_quotes 填 ""。

请严格输出 JSON 格式（不要输出任何多余文字），格式如下：
{
  "results": [
    {
      "id": 0,
      "score": 9.0,
      "sub_topic": "央行宏观",
      "key_quotes": "正文原句摘录...",
      "reason": "简明扼要写出打分依据或淘汰原因"
    }
  ]
}"""


# ================= 2. 辅助工具函数 =================
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
    valid_list = VALID_SUB_TOPICS.get(topic, ["模型应用"])
    if len(valid_list) == 1:
        return valid_list[0]

    text = f"{title} {snippet} {reason}"
    if topic == "AI与硬科技":
        if re.search(r"(进出口|海关总署|数据局|美联储|利率|央行|自主可控|乌兰察布|冷焦虑|出口管制|关税|国家标准)", text):
            return "宏观政经"
        if re.search(r"(财报|三季报|季报|Q3|Q4|营收|净利|利润|毛利率|IPO|招股书|估值|并购|收购|持仓|张坤|次贷|现金流|回购|分红|市盈率|增持|主力资金|闯关创业板|资本开支)", text):
            return "财报资本"
        if re.search(r"(芯片|半导体|晶圆|台积电|CoWoS|封装|HBM|内存|DRAM|存储|闪存|光模块|光互联|液冷|买电|电力设备|EDA|氮化镓|星闪|手机出货|端侧SoC|征程7|服务器)", text):
            return "算力硬件"
        return "模型应用"
    elif topic == "宏观与金融":
        if re.search(r"(违约|暴雷|次贷|利差|CDS|危机|破产|做空|泡沫|抛售|风险)", text):
            return "金融风险"
        if re.search(r"(财报|并购|收购|IPO|持仓|巴菲特|摩根|高盛|营收|净利|私募|主权基金)", text):
            return "巨头并购"
        if re.search(r"(美债|黄金|原油|汇率|人民币|美元|日元|大宗商品|铜价|国债|股市|指数)", text):
            return "股债汇商"
        return "央行宏观"
    elif topic == "国际与地缘":
        if re.search(r"(关税|贸易|进出口|顺差|逆差|世贸|倾销|自贸)", text):
            return "贸易关税"
        if re.search(r"(制裁|实体清单|出口管制|法案|禁令|审查|合规|反垄断)", text):
            return "法案管制"
        if re.search(r"(石油|天然气|稀土|锂矿|航运|红海|运河|矿产|供应链|粮食)", text):
            return "能源矿产"
        return "国际政局"
    elif topic == "新能源与制造":
        if re.search(r"(航天|火箭|卫星|星链|SpaceX|低空|eVTOL|无人机|商业航天)", text):
            return "航天低空"
        if re.search(r"(固态电池|储能|电网|光伏|风电|核电|氢能|锂电|宁德时代|充电)", text):
            return "电力储能"
        if re.search(r"(出海|建厂|海外工厂|墨西哥|东南亚|欧洲建厂|供应链转移|外贸制造)", text):
            return "出海制造"
        return "智驾车企"
    elif topic == "影视文化":
        if re.search(r"(AI|虚拟制片|特效|视效|LED棚|IMAX|杜比|后期|渲染|数字人|生成式|技术)", text):
            return "影视科技"
        if re.search(r"(财报|营收|利润|订阅|会员|奈飞|Netflix|迪士尼|爱奇艺|腾讯视频|出品|成本|版权|并购|罢工|商业)", text):
            return "行业商业"
        if re.search(r"(定档|预告|首映|开机|杀青|立项|片单|戛纳|威尼斯|柏林|奥斯卡|艾美奖|新片|新剧|开播)", text):
            return "新片动向"
        return "深度影评"

    return valid_list[0]

def enforce_per_topic_quota(news_list, max_per_topic=MAX_SAVED_PER_TOPIC):
    """分门类独立蓄水池：每个门类独立保留最新 max_per_topic 篇，保护冷门频道不被高频新闻冲刷掉"""
    counts = {}
    kept = []
    for item in news_list:
        t = item.get("topic", "AI与硬科技")
        counts[t] = counts.get(t, 0) + 1
        if counts[t] <= max_per_topic:
            kept.append(item)
    return kept

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
        history_block = "\n".join([f"- {t}" for t in recent_accepted_titles[:20]])

    article_blocks = []
    for idx, art in enumerate(batch_articles):
        body = art["body"]
        if len(body) > 1200:
            sliced_body = body[:850] + "\n...[中间省略]...\n" + body[-350:]
        else:
            sliced_body = body
        allowed_subs = " | ".join(VALID_SUB_TOPICS.get(art["topic"], ["模型应用"]))
        article_blocks.append(
            f"【候选文章 ID: {idx}】\n"
            f"所属门类：{art['topic']} （合法子版块选项：[{allowed_subs}]）\n"
            f"标题：{art['title']}\n"
            f"来源：{art['source']}\n"
            f"正文切片：\n{sliced_body}\n"
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

    for item in saved_news:
        t_name = item.get("topic", "AI与硬科技")
        valid_set = set(VALID_SUB_TOPICS.get(t_name, VALID_SUB_TOPICS["AI与硬科技"]))
        if item.get("sub_topic") not in valid_set:
            item["sub_topic"] = fallback_sub_topic(
                t_name, item.get("title", ""), item.get("snippet", ""), item.get("reason", "")
            )

    recent_titles = [item.get("title", "") for item in saved_news[:35]]
    topic_buckets = {t: [] for t in TOPICS}
    all_collected_titles = list(recent_titles)
    scanned_count = 0
    local_filtered_count = 0

    print("🔍 Step 1: 开始扫描 7 大新闻门类 RSS 源并进行本地粗筛...")
    for topic, urls in TOPICS.items():
        for feed_idx, rss_url in enumerate(urls, 1):
            feed = feedparser.parse(rss_url)
            sorted_entries = sorted(
                feed.entries,
                key=lambda x: 0 if VIP_SOURCES.search(x.get("title", "")) else 1
            )
            feed_count = 0
            print(f"  📡 扫描 [{topic}] 源 #{feed_idx} (共 {len(sorted_entries)} 条)...")

            for entry in sorted_entries:
                if feed_count >= MAX_PER_FEED:
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

                if SOURCE_BLACKLIST.search(source):
                    seen_ids.add(title_hash)
                    local_filtered_count += 1
                    continue

                if TITLE_BLACKLIST.search(title):
                    seen_ids.add(title_hash)
                    local_filtered_count += 1
                    continue

                if is_similar_title(title, all_collected_titles):
                    seen_ids.add(title_hash)
                    local_filtered_count += 1
                    continue

                real_url, body = decode_and_extract(link)
                seen_ids.add(title_hash)

                if len(body) < 450:
                    local_filtered_count += 1
                    continue

                if HEAD_BLACKLIST.search(body[:120]):
                    local_filtered_count += 1
                    continue

                if TAIL_BLACKLIST.search(body[-350:]):
                    local_filtered_count += 1
                    continue

                all_collected_titles.append(title)
                topic_buckets[topic].append({
                    "id_hash": title_hash,
                    "topic": topic,
                    "title": title,
                    "source": source,
                    "url": real_url,
                    "pub_date": pub_date,
                    "body": body[:MAX_BODY_CHARS],
                    "snippet": body[:140].replace("\n", " ") + "..."
                })
                feed_count += 1

    # 发牌式跨门类轮询抽样（Round-Robin），保证 7 个门类绝对公平，不被排前面的门类吃光名额
    candidates = []
    while len(candidates) < MAX_ARTICLES_PER_RUN:
        added_any = False
        for t in TOPICS:
            if topic_buckets[t] and len(candidates) < MAX_ARTICLES_PER_RUN:
                candidates.append(topic_buckets[t].pop(0))
                added_any = True
        if not added_any:
            break

    print(f"📦 Step 2: 跨门类均衡抽样完成，共选出 {len(candidates)} 篇候选文章进入 AI 终审。")

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
            if sub_topic not in set(VALID_SUB_TOPICS.get(t_name, [])):
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
                    "body": art["body"],
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

    # 按分门类独立蓄水池保存（每个门类各自保留最新 50 篇）
    saved_news = enforce_per_topic_quota(saved_news, MAX_SAVED_PER_TOPIC)
    save_json(DATA_FILE, saved_news)
    save_json(SEEN_FILE, list(seen_ids)[-3500:])

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
