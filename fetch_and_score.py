import os
import re
import json
import time
import hashlib
import urllib.parse
import requests
import feedparser
import trafilatura
from datetime import datetime, timezone
from googlenewsdecoder import gnewsdecoder

# ================= 1. 原有 7 大深度门类核心配置区 =================
SCORE_THRESHOLD = 8.5         # 7大深度门类录取线（>= 8.5分保留）
BATCH_SIZE = 8                # 每次打包 8 篇发给 AI
MAX_PER_FEED = 3              # 每个 RSS 源单次最多提取 3 篇候选
MAX_ARTICLES_PER_RUN = 24     # 7大深度门类单次最多送审 24 篇
MAX_SAVED_PER_TOPIC = 50      # 每个深度门类独立保留最新 50 篇
MAX_BODY_CHARS = 3500         # 保存正文最大字符数

DATA_FILE = "high_quality_news.json"
SEEN_FILE = "seen_urls.json"
STATUS_FILE = "status.json"

# 热点风向标独立存储文件
TRENDING_FILE = "trending_news.json"
TRENDING_SNAPSHOT_FILE = "trending_snapshot.json"
TRENDING_TTL_SECONDS = 48 * 3600
MAX_TRENDING_SAVED = 35
MAX_TRENDING_CANDIDATES = 8

# 全球抓马台独立存储文件（与原有门类、热点风向标完全物理隔离）
GOSSIP_FILE = "gossip_news.json"
GOSSIP_SEEN_FILE = "gossip_seen.json"
GOSSIP_TTL_SECONDS = 48 * 3600
MAX_GOSSIP_SAVED = 30
MAX_GOSSIP_CANDIDATES = 8

VALID_SUB_TOPICS = {
    "AI与硬科技": ["算力硬件", "模型应用", "财报资本", "宏观政经"],
    "宏观与金融": ["央行宏观", "股债汇商", "巨头并购", "金融风险"],
    "国际与地缘": ["贸易关税", "法案管制", "能源矿产", "国际政局"],
    "新能源与制造": ["智驾车企", "电力储能", "航天低空", "出海制造"],
    "影视文化": ["深度影评", "新片动向", "行业商业", "影视科技"],
    "前沿科学": ["前沿科学"],
    "科幻小说": ["科幻小说"],
}

# 7 大深度门类 RSS 源配置（保持原样）
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

# 热点风向标媒体焦点源
TRENDING_MEDIA_FEEDS = [
    ("国内热点", "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
    ("全球风向", "https://news.google.com/rss?hl=zh-CN&gl=SG&ceid=SG:zh-Hans"),
    ("突发共振", "https://news.google.com/rss/search?q=(突发+OR+通报+OR+紧急+OR+最新+OR+回应+OR+调查+OR+宣布)+(路透+OR+彭博+OR+联合早报+OR+澎湃+OR+财新+OR+第一财经+OR+新京报+OR+界面+OR+新华社+OR+央视)+when:3h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
]

# 全球抓马台专属 RSS 源（路径 B：国内奇闻/港台小报 + 全球顶级英文八卦小报直连）
GOSSIP_CN_FEEDS = [
    ("国内瓜田", "https://news.google.com/rss/search?q=(曝+OR+实锤+OR+塌房+OR+出轨+OR+离婚+OR+互撕+OR+翻车+OR+豪门+OR+奇葩+OR+狗血+OR+小作文)+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
    ("港台/日韩瓜", "https://news.google.com/rss/search?q=(好萊塢+OR+韓星+OR+日媒+OR+豪門+OR+出軌+OR+離婚+OR+翻車+OR+互撕+OR+醜聞+OR+奇葩)+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
]

GOSSIP_GLOBAL_FEEDS = [
    ("TMZ", "https://www.tmz.com/rss.xml"),
    ("Page Six", "https://pagesix.com/feed/"),
    ("Daily Mail Showbiz", "https://www.dailymail.co.uk/tvshowbiz/index.rss"),
    ("Daily Mail Weird", "https://www.dailymail.co.uk/news/weird/index.rss")
]

VIP_SOURCES = re.compile(
    r"(财新|晚点|LatePost|第一财经|21世纪|界面|路透|彭博|Bloomberg|联合早报|经济观察报|澎湃|新京报|央视|新华社|毒眸|娱理|三联|虎嗅|36氪|芯东西|科幻世界|未来事务管理局|BBC|日经|韩联社)"
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

TRENDING_GOSSIP_BLACKLIST = re.compile(
    r"(恋情|绯闻|出轨|离婚|塌房|互撕|翻车|街拍|红毯|艳压|少女感|冻龄|颜值|撕番|应援|生图|演技炸裂|综艺路透|壁纸|头像|星座运势|带货榜)"
)

# 全球抓马台仅拦截硬广、赌博与无聊纯穿搭词（彻底解封感叹号与情绪词）
GOSSIP_AD_BLACKLIST = re.compile(
    r"(彩票|博彩|代孕|微商|减肥药|星座运势|壁纸|头像|穿搭分享|显瘦指南|买一送一|优惠券|Shop the look|Best deals)"
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

# 7大深度门类 Prompt
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

# 热点风向标 Prompt
TRENDING_SYSTEM_PROMPT = """你是一位敏锐的全网突发热点与公共舆情总编。以下是通过“平台热榜1小时极速飙升算法”与“国内外权威媒体短时密集共振算法”捕捉到的候选热点事件及其配套报道。
请在不限定领域的前提下（社会民生、突发事故、法治案件、国内外政经突发、商业黑天鹅、科技文体破圈大事均予以收纳），对每个候选热点进行公共价值与真实性把关（满分10分，>= 8.0 分予以收录）。

【收录与淘汰标准】：
1. 【广泛接纳真实突发（>= 8.0 分）】：凡属于真实发生的国内外重大突发事件、官方重要通报、引发广泛公众讨论的社会民生/法治/政策/商业热点，且配套报道事实清晰、信源正规，均应给予 8.2 ~ 9.8 分（根据事件公共影响力与飙升强度打分）。
2. 【同事件去重铁律（打 0.0 分）】：若候选热点与《过去48小时已收录热点清单》或同批次其他候选属同一事件，且**并无重大新事实反转或新官方通报进展**，一律打 0.0 分淘汰！但若有重大新进展（如从“事故发生”到“官方发布问责通报”），则予以高分放行。
3. 【纯娱乐明星八卦/网红买榜/软广一票否决（最高 4.0 分）】：纯粹的娱乐明星私生活绯闻、粉圈控评、网红炒作、毫无公共价值的低俗猎奇或营销带货，一律打 4.0 分以下淘汰！

请严格输出 JSON 格式（不要输出任何多余文字），格式如下：
{
  "results": [
    {
      "id": 0,
      "score": 9.0,
      "region_tag": "国内热点",
      "key_quotes": "从正文中一字不改摘录1~2句最核心的事实或通报原话（60~130字）",
      "reason": "简明扼要解读该事件为何在短时间内引爆关注及当前核心看点（40~80字）"
    }
  ]
}"""

# 全球抓马台专用 Prompt（按 Drama 戏剧冲突程度打分，并将英文一手瓜翻译成接地气中文吃瓜剧透！）
GOSSIP_SYSTEM_PROMPT = """你是一位眼光极毒、深谙全球娱乐圈与奇葩社会新闻的“顶级八卦小报主编”。你的唯一任务是从国内及全球英文小报（TMZ、Page Six、Daily Mail 等）的候选文章中，按【Drama（戏剧冲突与狗血猎奇）程度】打分（满分 10 分，>= 8.0 分入选“全球抓马台”）。

【Drama 吸睛分（满分 10 分）四维打分标准】：
1. 戏剧冲突与狗血烈度（35%）：撕破脸互爆猛料、公开翻车打脸、出轨/婚变/巨额分产大战、豪门宫斗、法庭荒诞互告、人设瞬间塌房。冲突越激烈分越高！
2. 反转与猎奇离谱度（30%）：情节比电视剧还离谱、充满神反转的全球奇葩社会新闻或名人怪诞行为。
3. “瓜料”实锤细节度（20%）：正文里有具体细节（聊天记录、小作文原话、荒诞金额或经过），绝不是标题党空壳。
4. 破圈吸睛度（15%）：涉及知名明星、顶级网红、亿万富豪、王室名流，或极其离谱到让人忍不住转发的普通人奇闻。

【一票否决（打 0.0 ~ 5.0 分淘汰！）】：
- 【无聊吹捧/日常穿搭（最高 4.0 分）】：某明星穿裙子现身红毯很美、机场街拍、普通电影宣传、毫无冲突的日常晒娃或和平客套声明，毫无 Drama，一律淘汰！
- 【标题诈骗（打 0.0 分）】：标题写得惊天动地，点进去正文其实啥也没发生或强行辟谣，一律淘汰！
- 【同瓜去重（打 0.0 分）】：若与《过去48小时已吃大瓜清单》或同批次属同一个瓜且无新反转，打 0.0 分！

【输出字段要求（全部使用生动接地气的简体中文！）】：
- `cn_title`：若是英文报道（TMZ/Page Six/Daily Mail），请忠实于原意翻译并润色成一个极具吸睛感的中文八卦标题（切勿脱离事实瞎编）；若是中文报道，保留原标题（繁体转简体）。
- `drama_tag`：严格四选一："🌟 娱乐圈大瓜" | "🌍 欧美日韩瓜" | "🎭 社会奇闻录" | "💣 翻车名场面"
- `drama_summary`：【3秒省流吃瓜】用最直白、生动、带点吃瓜幽默的简体中文（50~90字），一口气剧透“谁和谁到底发生了什么狗血事”，跳过一切废话铺垫！
- `spicy_quote`：【最炸裂原话/细节】摘录（英文则意译成传神中文）文中最炸裂、最狗血的一句当事人原话或最离谱的细节（25~75字）。

请严格输出 JSON 格式（不要输出任何多余文字），格式如下：
{
  "results": [
    {
      "id": 0,
      "score": 9.3,
      "cn_title": "吸睛中文标题",
      "drama_tag": "🌍 欧美日韩瓜",
      "drama_summary": "3秒省流吃瓜大白话剧透...",
      "spicy_quote": "最炸裂的一句原话或离谱细节..."
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

def clean_html_text(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text

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
    counts = {}
    kept = []
    for item in news_list:
        t = item.get("topic", "AI与硬科技")
        counts[t] = counts.get(t, 0) + 1
        if counts[t] <= max_per_topic:
            kept.append(item)
    return kept

def is_similar_title(new_title, existing_titles, threshold=0.40):
    tokens_new = set(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", new_title.lower()))
    if len(tokens_new) < 3:
        return False
    for old_title in existing_titles:
        tokens_old = set(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", old_title.lower()))
        if not tokens_old:
            continue
        overlap = len(tokens_new & tokens_old) / min(len(tokens_new), len(tokens_old))
        if overlap >= threshold:
            return True
    return False

def decode_and_extract(url):
    real_url = url
    if "news.google.com" in url:
        try:
            res = gnewsdecoder(url, interval=0.5)
            if res.get("status") or res.get("success"):
                real_url = res.get("decoded_url", url)
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


# ================= 3. 多模型轮询通用调用函数 =================
def call_llm_raw(system_prompt_text, user_prompt_text):
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

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
                {"role": "system", "content": system_prompt_text},
                {"role": "user", "content": user_prompt_text}
            ],
            "temperature": 0.15,
            "response_format": {"type": "json_object"}
        }

        try:
            print(f"🤖 尝试调用 [{provider.upper()}] {model_name}...")
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


def call_llm_with_fallback(batch_articles, recent_accepted_titles):
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
    return call_llm_raw(SYSTEM_PROMPT, user_prompt)


# ================= 4. 独立模块：【🔥 热点风向标】混合双擎流水线 =================
def fetch_platform_hotlists():
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # 1. 百度实时热搜榜 API
    try:
        r = requests.get("https://top.baidu.com/api/board?platform=wise&tab=realtime", headers=headers, timeout=10)
        if r.status_code == 200:
            cards = r.json().get("data", {}).get("cards", [])
            if cards:
                content_list = cards[0].get("content", [])
                if content_list and isinstance(content_list[0], dict) and "content" in content_list[0]:
                    content_list = content_list[0]["content"]
                for rank_idx, entry in enumerate(content_list[:30], 1):
                    word = (entry.get("word") or entry.get("query") or "").strip()
                    if not word:
                        continue
                    hot_val = int(re.sub(r"\D", "", str(entry.get("hotScore", "0"))) or 0)
                    tag_code = str(entry.get("hotTag", ""))
                    tag_map = {"1": "新", "4": "沸", "5": "爆"}
                    tag = tag_map.get(tag_code, "")
                    items.append({
                        "title": word,
                        "rank": rank_idx,
                        "hot_val": hot_val,
                        "tag": tag,
                        "platform": "百度热搜"
                    })
    except Exception as e:
        print(f"  [百度热榜跳过] {e}")

    # 2. 今日头条实时热榜 API
    try:
        r = requests.get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", headers=headers, timeout=10)
        if r.status_code == 200:
            data_list = r.json().get("data", [])
            for rank_idx, entry in enumerate(data_list[:30], 1):
                word = (entry.get("Title") or "").strip()
                if not word:
                    continue
                hot_val = int(re.sub(r"\D", "", str(entry.get("HotValue", "0"))) or 0)
                label_raw = str(entry.get("Label", "")).strip()
                tag = label_raw if label_raw in ("新", "沸", "爆") else ""
                items.append({
                    "title": word,
                    "rank": rank_idx,
                    "hot_val": hot_val,
                    "tag": tag,
                    "platform": "头条热榜"
                })
    except Exception as e:
        print(f"  [头条热榜跳过] {e}")

    return items


def find_article_for_keyword(keyword, min_len=320, prefer_vip=True):
    q = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={q}+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        feed = feedparser.parse(rss_url)
        entries = feed.entries[:8]
        if prefer_vip:
            entries = sorted(entries, key=lambda x: 0 if VIP_SOURCES.search(x.get("title", "")) else 1)
        for entry in entries[:3]:
            raw_title = entry.get("title", "").strip()
            source = "主流媒体"
            title = raw_title
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title, source = parts[0].strip(), parts[1].strip()
            if prefer_vip and SOURCE_BLACKLIST.search(source):
                continue
            real_url, body = decode_and_extract(entry.get("link", ""))
            if len(body) >= min_len:
                return {
                    "title": title,
                    "source": source,
                    "url": real_url,
                    "pub_date": entry.get("published", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
                    "body": body[:MAX_BODY_CHARS],
                    "snippet": body[:140].replace("\n", " ") + "..."
                }
    except Exception as e:
        print(f"  [热词配文异常] {e}")
    return None


def run_trending_pipeline():
    """独立运行【🔥 热点风向标】并返回被拦截的八卦热词供【🍉 全球抓马台】废料回收"""
    print("\n🔥 Step 3: 启动【热点风向标】混合双擎（1h热榜斜率 + 国内外权威媒体共振）...")
    now_ts = int(time.time())

    saved_trending = load_json(TRENDING_FILE, [])
    active_trending = [
        item for item in saved_trending
        if (now_ts - int(item.get("first_erupted_ts", now_ts))) <= TRENDING_TTL_SECONDS
    ]
    existing_trending_titles = [item.get("title", "") for item in active_trending] + [
        item.get("hot_keyword", "") for item in active_trending if item.get("hot_keyword")
    ]

    snapshot = load_json(TRENDING_SNAPSHOT_FILE, {})
    snapshot = {
        k: v for k, v in snapshot.items()
        if (now_ts - int(v.get("first_seen_ts", now_ts))) <= 24 * 3600
    }

    surging_pool = []
    recycled_gossip = []  # 回收被正经热点踢掉的娱乐/抓马热词

    hotlist_items = fetch_platform_hotlists()
    for item in hotlist_items:
        kw = item["title"]
        if TRENDING_GOSSIP_BLACKLIST.search(kw):
            recycled_gossip.append(item)
            continue

        norm_key = make_hash(re.sub(r"\W+", "", kw)[:14])
        rank = item["rank"]
        hot_val = item["hot_val"]
        tag = item["tag"]
        platform = item["platform"]

        velocity_badge = ""
        priority = 0

        if norm_key not in snapshot:
            snapshot[norm_key] = {
                "title": kw,
                "first_seen_ts": now_ts,
                "last_rank": rank,
                "hot_val": hot_val,
                "platform": platform
            }
            if rank <= 15 or tag in ("沸", "爆", "新"):
                tag_str = f" [{tag}]" if tag else ""
                velocity_badge = f"🚀 1h新晋空降 {platform}第{rank}{tag_str}"
                priority = 95 - rank + (15 if tag in ("沸", "爆") else 5)
        else:
            prev = snapshot[norm_key]
            age_hours = (now_ts - int(prev.get("first_seen_ts", now_ts))) / 3600.0
            prev_rank = int(prev.get("last_rank", rank))
            prev_hot = int(prev.get("hot_val", hot_val))

            prev["last_rank"] = rank
            prev["hot_val"] = max(hot_val, prev_hot)

            if age_hours > 6.0:
                continue

            rank_jump = prev_rank - rank
            heat_growth = ((hot_val - prev_hot) / max(prev_hot, 1)) * 100 if prev_hot > 0 else 0

            if rank_jump >= 8:
                velocity_badge = f"🚀 1h飙升 {rank_jump} 位 (冲至{platform}第{rank})"
                priority = 75 + rank_jump
            elif heat_growth >= 40 and rank <= 20:
                velocity_badge = f"📈 1h热度暴涨 +{int(heat_growth)}% ({platform}第{rank})"
                priority = 70 + min(int(heat_growth / 4), 25)

        if not velocity_badge:
            continue

        if is_similar_title(kw, existing_trending_titles, threshold=0.45):
            continue

        merged = False
        for existing in surging_pool:
            if is_similar_title(kw, [existing["hot_keyword"]], threshold=0.38):
                if platform not in existing["platforms"]:
                    existing["platforms"].append(platform)
                    existing["resonance_badge"] = f"📡 {'·'.join(existing['platforms'])} 双榜共振"
                    existing["priority"] += 30
                merged = True
                break

        if not merged:
            surging_pool.append({
                "hot_keyword": kw,
                "velocity_badge": velocity_badge,
                "resonance_badge": f"📡 {platform} 实时热榜",
                "platforms": [platform],
                "region_tag": "国内热点",
                "priority": priority,
                "article": None
            })

    for region_label, feed_url in TRENDING_MEDIA_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:12]:
                raw_title = entry.get("title", "").strip()
                if not raw_title or TRENDING_GOSSIP_BLACKLIST.search(raw_title):
                    continue

                source = "主流媒体"
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title, source = parts[0].strip(), parts[1].strip()

                if is_similar_title(title, existing_trending_titles, threshold=0.42):
                    continue

                summary_html = entry.get("summary", "")
                cluster_outlets = []
                for m_name in re.findall(r"<font[^>]*>(.*?)</font>", summary_html):
                    clean_m = re.sub(r"<[^>]+>", "", m_name).strip()
                    if clean_m and clean_m not in cluster_outlets:
                        cluster_outlets.append(clean_m)

                media_count = max(len(cluster_outlets), 1)
                if media_count < 3 and not (region_label == "突发共振" and VIP_SOURCES.search(source)):
                    continue

                merged = False
                for existing in surging_pool:
                    if is_similar_title(title, [existing["hot_keyword"]], threshold=0.36):
                        existing["resonance_badge"] = f"📡 {'·'.join(existing['platforms'])} 与 {media_count}家主流媒体共振"
                        existing["priority"] += 35
                        merged = True
                        break

                if not merged:
                    sample_outlets = "·".join(cluster_outlets[:3]) if cluster_outlets else source
                    res_badge = (
                        f"📡 {sample_outlets}等 {media_count} 家媒体密集聚焦"
                        if media_count >= 3 else f"📡 权威媒体突发聚焦 ({source})"
                    )
                    vel_badge = "🔥 短时多源爆发" if media_count >= 4 else "⚡ 突发焦点速递"
                    surging_pool.append({
                        "hot_keyword": title,
                        "velocity_badge": vel_badge,
                        "resonance_badge": res_badge,
                        "platforms": [source],
                        "region_tag": "全球风向" if region_label == "全球风向" else "国内热点",
                        "priority": 72 + media_count * 5,
                        "entry_link": entry.get("link", ""),
                        "entry_pub": entry.get("published", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
                        "entry_source": source,
                        "article": None
                    })
        except Exception as e:
            print(f"  [媒体焦点簇跳过] {e}")

    surging_pool.sort(key=lambda x: x["priority"], reverse=True)

    ready_candidates = []
    for cand in surging_pool:
        if len(ready_candidates) >= MAX_TRENDING_CANDIDATES:
            break

        if cand.get("entry_link"):
            real_url, body = decode_and_extract(cand["entry_link"])
            if len(body) >= 320:
                cand["article"] = {
                    "title": cand["hot_keyword"],
                    "source": cand["entry_source"],
                    "url": real_url,
                    "pub_date": cand["entry_pub"],
                    "body": body[:MAX_BODY_CHARS],
                    "snippet": body[:140].replace("\n", " ") + "..."
                }
        else:
            art = find_article_for_keyword(cand["hot_keyword"], min_len=320, prefer_vip=True)
            if art:
                cand["article"] = art

        if cand["article"]:
            if not is_similar_title(cand["article"]["title"], existing_trending_titles, threshold=0.42):
                ready_candidates.append(cand)
                existing_trending_titles.append(cand["article"]["title"])

    print(f"⚡ 热点双擎共锁定 {len(ready_candidates)} 个高爆发候选事件进入 AI 热点把关...")

    if ready_candidates:
        history_str = "\n".join([f"- {t}" for t in existing_trending_titles[:25]]) or "无"
        blocks = []
        for idx, c in enumerate(ready_candidates):
            art = c["article"]
            body = art["body"]
            sliced = body[:850] + "\n...\n" + body[-300:] if len(body) > 1150 else body
            blocks.append(
                f"【候选热点 ID: {idx}】\n"
                f"飙升信号：{c['velocity_badge']} | {c['resonance_badge']}\n"
                f"默认区域属性：{c['region_tag']}\n"
                f"配套报道标题：{art['title']} (来源：{art['source']})\n"
                f"报道正文切片：\n{sliced}\n"
            )
        user_prompt = (
            f"《过去48小时已收录热点清单（若无重大新事实进展请打 0.0 分去重）》：\n{history_str}\n\n"
            f"====================\n\n" + "\n====================\n".join(blocks)
        )

        results, used_model = call_llm_raw(TRENDING_SYSTEM_PROMPT, user_prompt)
        res_map = {item.get("id"): item for item in results if isinstance(item, dict)}

        added_trending = 0
        for idx, c in enumerate(ready_candidates):
            r = res_map.get(idx)
            if not r:
                continue
            score = float(r.get("score", 0))
            if score >= 8.0:
                art = c["article"]
                region_tag = (r.get("region_tag") or c["region_tag"]).strip()
                key_quotes = (r.get("key_quotes") or "").strip()
                reason = (r.get("reason") or "").strip()
                print(f"  🔥 [热点收录! {score}分 | {c['velocity_badge']}] {art['title']} ({art['source']})")
                active_trending.insert(0, {
                    "hot_keyword": c["hot_keyword"],
                    "title": art["title"],
                    "source": art["source"],
                    "url": art["url"],
                    "pub_date": art["pub_date"],
                    "snippet": art["snippet"],
                    "key_quotes": key_quotes,
                    "body": art["body"],
                    "score": score,
                    "reason": reason,
                    "velocity_badge": c["velocity_badge"],
                    "resonance_badge": c["resonance_badge"],
                    "region_tag": region_tag,
                    "model": used_model,
                    "first_erupted_ts": now_ts,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                })
                added_trending += 1
            else:
                print(f"  🗑️ [热点剔除 {score}分] {c['hot_keyword'][:24]}...")

        print(f"✅ 热点风向标更新完毕：本轮新增 {added_trending} 条飙升热点。")

    save_json(TRENDING_FILE, active_trending[:MAX_TRENDING_SAVED])
    save_json(TRENDING_SNAPSHOT_FILE, snapshot)
    return recycled_gossip


# ================= 5. 独立模块：【🍉 全球抓马台】高能多巴胺八卦流水线（路径 B） =================
def run_gossip_pipeline(recycled_hot_gossip=None):
    """独立运行【🍉 全球抓马台】：国内废料回收+港台奇闻 + 欧美英文顶流小报（TMZ/Page Six/Daily Mail）"""
    now_ts = int(time.time())
    saved_gossip = load_json(GOSSIP_FILE, [])
    active_gossip = [
        item for item in saved_gossip
        if (now_ts - int(item.get("first_erupted_ts", now_ts))) <= GOSSIP_TTL_SECONDS
    ]

    # 节能调度：若已有 >= 6 条大瓜，且非手动触发(workflow_dispatch)，仅在偶数小时运行（每天省一半API）
    is_manual = (os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch")
    current_hour = datetime.now(timezone.utc).hour
    if len(active_gossip) >= 6 and not is_manual and (current_hour % 2 != 0):
        print("\n🍉 Step 4: 【全球抓马台】奇数小时节能休眠中（已保留 48h 内现有大瓜）。")
        save_json(GOSSIP_FILE, active_gossip[:MAX_GOSSIP_SAVED])
        return

    print("\n🍉 Step 4: 启动【全球抓马台】（国内/港台八卦 + TMZ/Page Six/Daily Mail 全球一手瓜）...")
    gossip_seen = set(load_json(GOSSIP_SEEN_FILE, []))
    existing_gossip_titles = [item.get("title", "") for item in active_gossip] + [
        item.get("orig_title", "") for item in active_gossip if item.get("orig_title")
    ]

    cn_bucket = []
    global_bucket = []

    # --- A. 国内池 1：废料回收（从热榜被正经热点踢掉的八卦热词） ---
    for hot_item in (recycled_hot_gossip or [])[:4]:
        kw = hot_item["title"]
        h = make_hash("g_hot_" + re.sub(r"\W+", "", kw)[:14])
        if h in gossip_seen or GOSSIP_AD_BLACKLIST.search(kw):
            continue
        if is_similar_title(kw, existing_gossip_titles, threshold=0.45):
            continue
        gossip_seen.add(h)
        art = find_article_for_keyword(kw, min_len=180, prefer_vip=False)
        if art:
            tag_str = f" [{hot_item['tag']}]" if hot_item.get("tag") else ""
            cn_bucket.append({
                "orig_title": art["title"],
                "source": f"{art['source']} ({hot_item['platform']}第{hot_item['rank']}{tag_str})",
                "url": art["url"],
                "pub_date": art["pub_date"],
                "body": art["body"],
                "lang": "zh",
                "origin_hint": f"🔥 {hot_item['platform']}第{hot_item['rank']}{tag_str}"
            })

    # --- B. 国内池 2：国内奇闻与港台娱乐小报 RSS ---
    for label, rss_url in GOSSIP_CN_FEEDS:
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries[:10]:
                if len(cn_bucket) >= 5:
                    break
                raw_title = entry.get("title", "").strip()
                if not raw_title or GOSSIP_AD_BLACKLIST.search(raw_title):
                    continue
                source = label
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title, source = parts[0].strip(), parts[1].strip()

                h = make_hash("g_cn_" + re.sub(r"\W+", "", title)[:14])
                if h in gossip_seen or is_similar_title(title, existing_gossip_titles, threshold=0.42):
                    continue

                real_url, body = decode_and_extract(entry.get("link", ""))
                gossip_seen.add(h)
                if len(body) < 180:
                    continue

                existing_gossip_titles.append(title)
                cn_bucket.append({
                    "orig_title": title,
                    "source": source,
                    "url": real_url,
                    "pub_date": entry.get("published", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
                    "body": body[:MAX_BODY_CHARS],
                    "lang": "zh",
                    "origin_hint": f"🍉 {label}"
                })
        except Exception as e:
            print(f"  [中文瓜源跳过 {label}] {e}")

    # --- C. 海外池（路径 B 核心）：直连全球顶级英文小报 RSS (TMZ / Page Six / Daily Mail) ---
    for outlet_name, rss_url in GOSSIP_GLOBAL_FEEDS:
        try:
            feed = feedparser.parse(rss_url)
            picked = 0
            for entry in feed.entries[:8]:
                if picked >= 2 or len(global_bucket) >= 5:
                    break
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link or GOSSIP_AD_BLACKLIST.search(title):
                    continue

                h = make_hash("g_en_" + re.sub(r"\W+", "", title.lower())[:20])
                if h in gossip_seen or is_similar_title(title, existing_gossip_titles, threshold=0.45):
                    continue

                _, body = decode_and_extract(link)
                gossip_seen.add(h)

                # 若英文小报站点偶发反爬，自动回退读取 RSS 内置正文摘要
                if len(body) < 180:
                    fallback_summary = clean_html_text(entry.get("summary", ""))
                    if len(fallback_summary) >= 120:
                        body = fallback_summary
                    else:
                        continue

                existing_gossip_titles.append(title)
                global_bucket.append({
                    "orig_title": title,
                    "source": outlet_name,
                    "url": link,
                    "pub_date": entry.get("published", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
                    "body": body[:MAX_BODY_CHARS],
                    "lang": "en",
                    "origin_hint": f"🌍 全球一手生瓜 · {outlet_name}"
                })
                picked += 1
        except Exception as e:
            print(f"  [英文瓜源跳过 {outlet_name}] {e}")

    # 50/50 交替发牌抽样（保证国内大瓜与欧美全球一手大瓜均衡混合，共 8 篇 = 1 次 API 请求）
    gossip_candidates = []
    while len(gossip_candidates) < MAX_GOSSIP_CANDIDATES:
        added = False
        if global_bucket and len(gossip_candidates) < MAX_GOSSIP_CANDIDATES:
            gossip_candidates.append(global_bucket.pop(0))
            added = True
        if cn_bucket and len(gossip_candidates) < MAX_GOSSIP_CANDIDATES:
            gossip_candidates.append(cn_bucket.pop(0))
            added = True
        if not added:
            break

    print(f"🍉 全球抓马台共备齐 {len(gossip_candidates)} 篇候选大瓜进入 AI 抓马定级...")

    if gossip_candidates:
        history_str = "\n".join([f"- {t}" for t in existing_gossip_titles[:25]]) or "无"
        blocks = []
        for idx, g in enumerate(gossip_candidates):
            body = g["body"]
            sliced = body[:900] + "\n...\n" + body[-250:] if len(body) > 1150 else body
            blocks.append(
                f"【候选大瓜 ID: {idx}】\n"
                f"语言：{'英文原稿(请翻译成吸睛简体中文标题及中文吃瓜剧透)' if g['lang'] == 'en' else '中文原稿'}\n"
                f"来源：{g['source']}\n"
                f"原标题：{g['orig_title']}\n"
                f"正文内容：\n{sliced}\n"
            )
        user_prompt = (
            f"《过去48小时已吃大瓜清单（重复且无新反转请打 0.0 分）》：\n{history_str}\n\n"
            f"====================\n\n" + "\n====================\n".join(blocks)
        )

        results, used_model = call_llm_raw(GOSSIP_SYSTEM_PROMPT, user_prompt)
        res_map = {item.get("id"): item for item in results if isinstance(item, dict)}

        added_gossip = 0
        for idx, g in enumerate(gossip_candidates):
            r = res_map.get(idx)
            if not r:
                continue
            score = float(r.get("score", 0))
            if score >= 8.0:
                cn_title = (r.get("cn_title") or g["orig_title"]).strip()
                drama_tag = (r.get("drama_tag") or ("🌍 欧美日韩瓜" if g["lang"] == "en" else "🌟 娱乐圈大瓜")).strip()
                drama_summary = (r.get("drama_summary") or "").strip()
                spicy_quote = (r.get("spicy_quote") or "").strip()

                print(f"  🍉 [顶级大瓜! {score}分 | {drama_tag}] {cn_title} ({g['source']})")
                active_gossip.insert(0, {
                    "title": cn_title,
                    "orig_title": g["orig_title"],
                    "source": g["source"],
                    "url": g["url"],
                    "pub_date": g["pub_date"],
                    "body": g["body"],
                    "score": score,
                    "drama_tag": drama_tag,
                    "origin_hint": g["origin_hint"],
                    "drama_summary": drama_summary,
                    "spicy_quote": spicy_quote,
                    "lang": g["lang"],
                    "model": used_model,
                    "first_erupted_ts": now_ts,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                })
                added_gossip += 1
            else:
                print(f"  🗑️ [无聊瓜剔除 {score}分] {g['orig_title'][:28]}...")

        print(f"✅ 全球抓马台更新完毕：本轮新增 {added_gossip} 条高能大瓜。")

    save_json(GOSSIP_FILE, active_gossip[:MAX_GOSSIP_SAVED])
    save_json(GOSSIP_SEEN_FILE, list(gossip_seen)[-1500:])


# ================= 6. 主流水线 =================
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

    print("🔍 Step 1: 开始扫描 7 大深度门类 RSS 源并进行本地粗筛...")
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

    candidates = []
    while len(candidates) < MAX_ARTICLES_PER_RUN:
        added_any = False
        for t in TOPICS:
            if topic_buckets[t] and len(candidates) < MAX_ARTICLES_PER_RUN:
                candidates.append(topic_buckets[t].pop(0))
                added_any = True
        if not added_any:
            break

    print(f"📦 Step 2: 7 大深度门类均衡抽样完成，共选出 {len(candidates)} 篇候选文章进入 AI 终审。")

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

    saved_news = enforce_per_topic_quota(saved_news, MAX_SAVED_PER_TOPIC)
    save_json(DATA_FILE, saved_news)
    save_json(SEEN_FILE, list(seen_ids)[-3500:])

    # 独立运行【🔥 热点风向标】，并回收被踢出的八卦词条
    recycled_gossip = []
    try:
        recycled_gossip = run_trending_pipeline()
    except Exception as e:
        print(f"⚠️ [热点风向标流水线异常，不影响主板块]: {e}")

    # 独立运行【🍉 全球抓马台】（完全异常隔离，绝不影响主板块与热点风向标）
    try:
        run_gossip_pipeline(recycled_gossip)
    except Exception as e:
        print(f"⚠️ [全球抓马台流水线异常，不影响主板块]: {e}")

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
    print(f"🎉 全部任务运行结束！深度板块新增 {newly_accepted} 篇。")

if __name__ == "__main__":
    main()
