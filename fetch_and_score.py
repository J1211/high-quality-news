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
SCORE_THRESHOLD = 8.5       # 录取分数线
BATCH_SIZE = 4              # 每次打包发给 AI 评审的文章数（省 75% 请求次数）
MAX_ARTICLES_PER_RUN = 16   # 每次定时任务最多送审的新文章数（防超额）

DATA_FILE = "high_quality_news.json"
SEEN_FILE = "seen_urls.json"

# 主题与 RSS 源配置（后续扩展经济、金融、政治只需在这里加字典）
TOPICS = {
    "AI与硬科技": [
        # 源1：定向抓取网易新闻（163.com）中的 AI 与硬科技报道
        "https://news.google.com/rss/search?q=(AI+OR+人工智能+OR+芯片+OR+算力+OR+半导体+OR+大模型)+site:163.com+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        # 源2：全网主流财经科技媒体的 AI 与硬科技报道
        "https://news.google.com/rss/search?q=(AI芯片+OR+算力+OR+半导体+OR+大模型+OR+HBM+OR+晶圆)+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ]
}

# 本地粗筛黑名单：标题含这些词直接秒杀（0 Token 消耗）
TITLE_BLACKLIST = re.compile(
    r"(震惊|暴跌|崩盘|涨停|跌停|午评|收评|概念股|必看|彻底慌了|断崖式|ETF|掘金|龙头股|价值重估|满仓|飙升)"
)
# 文末软文黑名单：正文最后 350 字含这些词直接秒杀（专杀 5 分基金营销/吹票软文）
TAIL_BLACKLIST = re.compile(
    r"(基金有风险|投资需谨慎|风险提示：本文|不构成投资建议|ETF联接|代码：\d{6}|关注【|扫码领)"
)

# 多模型自动故障转移池（按优先级排序，全是目前官方支持的最新模型）
MODEL_POOL = [
    {"provider": "gemini", "model": "gemini-3.8-flash"},
    {"provider": "gemini", "model": "gemini-3.6-flash"},
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"},
    {"provider": "groq",   "model": "openai/gpt-oss-120b"},
    {"provider": "groq",   "model": "qwen/qwen3.8-27b"},
    {"provider": "groq",   "model": "openai/gpt-oss-20b"},
    {"provider": "gemini", "model": "gemini-2.5-flash"}, # 兼容老 Key 保底
]

# 8.5分冷酷主编评分矩阵 Prompt
SYSTEM_PROMPT = """你是一位极其严苛、客观的硬科技与财经新闻总编。请对输入的新闻列表进行独立质量打分（满分10分，支持小数如8.5、9.0）。

【高分核心标准（决定能否上 8.5 分）】：
1. 实质性新事实增量（30%）：围绕新发生的具体客观事件（量产/流片、财报发布、技术突破、明确金额的并购融资、政策落地），而非旧闻拼凑综述。
2. 数据密度与横向基准（30%）：不仅有具体数字，还提供参照系（如市占率对比、竞品参数/价格对比、同比/环比财务指标），具备可思考性。
3. 一手信源与多方印证（20%）：源自官方财报、公告、权威调研机构（如IDC、Counterpoint）或核心供应链独家披露。
4. 叙事克制与价值中立（20%）：摆事实列数据，不替读者下结论，不强行煽情或点评企业家性格。

【扣分与一票否决红线】：
- 事实单薄但展开大量主观描述、讲故事、强行升华评论（最高得 7.0 分）。
- 软文、企业公关通稿、文末夹带 ETF 基金或股票推荐（最高得 5.0 分）。
- 标题党、情绪渲染、拉踩引战（最高得 3.0 分）。

请严格输出 JSON 格式（不要输出任何 Markdown 代码块标记以外的多余文字），格式如下：
{
  "results": [
    {
      "id": 0,
      "score": 9.0,
      "reason": "简明扼要写出打分依据（如：含Counterpoint全球HBM市占率横向对比及公司三季报一手营收数据，叙事客观克制）"
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
def call_llm_with_fallback(batch_articles):
    """将一批文章打包发给模型池，自动跳过报错/限流/下线的模型"""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

    # 构建打包输入文本（采用首尾切片法节省 Token）
    user_Noteworthy = []
    for idx, art in enumerate(batch_articles):
        body = art["body"]
        if len(body) > 1200:
            sliced_body = body[:850] + "\n...[中间省略]...\n" + body[-350:]
        else:
            sliced_body = body
        user_Noteworthy.append(
            f"【文章 ID: {idx}】\n标题：{art['title']}\n来源：{art['source']}\n正文切片：\n{sliced_body}\n"
        )
    user_prompt = "\n====================\n".join(user_Noteworthy)

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
            resp = requests.post(url, headers=headers, json=payload, timeout=45)
            
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                # 清理可能附带的 markdown 标记
                content = re.sub(r"^```json\s*|\s*```$", "", content.strip())
                parsed = json.loads(content)
                print(f"✅ [{model_name}] 评审成功！")
                return parsed.get("results", []), f"{provider}:{model_name}"
            else:
                print(f"⚠️ [{model_name}] 返回状态码 {resp.status_code}: {resp.text[:120]} -> 自动切换下一个模型...")
                time.sleep(1)
        except Exception as e:
            print(f"⚠️ [{model_name}] 调用异常: {e} -> 自动切换下一个模型...")
            time.sleep(1)

    print("❌ 所有配置的模型均调用失败，请检查 API Key 或网络状态。")
    return [], "none"


# ================= 4. 主流水线 =================
def main():
    seen_ids = set(load_json(SEEN_FILE, []))
    saved_news = load_json(DATA_FILE, [])
    candidates = []

    print("🔍 Step 1: 开始拉取 RSS 源并进行本地零成本粗筛...")
    for topic, urls in TOPICS.items():
        for rss_url in urls:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                raw_title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                pub_date = entry.get("published", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

                # 分离 Google News 标题末尾的 " - 媒体名"
                source = "未知来源"
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title, source = parts[0].strip(), parts[1].strip()

                # 用标题前缀做唯一哈希（防止多家媒体转载同一篇通稿重复送审）
                title_hash = make_hash(re.sub(r"\W+", "", title)[:16])
                if title_hash in seen_ids:
                    continue

                # 第一层防爆：标题黑名单过滤
                if TITLE_BLACKLIST.search(title):
                    print(f"  [本地拦截-标题党] {title}")
                    seen_ids.add(title_hash)
                    continue

                # 提取正文
                real_url, body = decode_and_extract(link)
                seen_ids.add(title_hash) # 标记已处理，避免下次重复抓

                # 第一层防爆：正文字数体检（低于 400 字的快讯或残缺网页直接丢弃）
                if len(body) < 400:
                    print(f"  [本地拦截-正文过短({len(body)}字)] {title[:25]}...")
                    continue

                # 第一层防爆：文末软文/ETF推广拦截
                if TAIL_BLACKLIST.search(body[-350:]):
                    print(f"  [本地拦截-疑似软文/基金推广] {title[:25]}...")
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

                if len(candidates) >= MAX_ARTICLES_PER_RUN:
                    break
            if len(candidates) >= MAX_ARTICLES_PER_RUN:
                break

    print(f"📦 Step 2: 本地粗筛完成，共有 {len(candidates)} 篇合格候选文章进入 AI 严审。")

    # 分批打包送审
    newly_accepted = 0
    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]
        scores_list, used_model = call_llm_with_fallback(batch)

        score_map = {item.get("id"): item for item in scores_list if isinstance(item, dict)}

        for idx, art in enumerate(batch):
            res = score_map.get(idx)
            if not res:
                continue
            score = float(res.get("score", 0))
            reason = res.get("reason", "")

            if score >= SCORE_THRESHOLD:
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
                print(f"  🗑️ [淘汰 {score}分] {art['title'][:22]}... | 原因: {reason[:35]}...")

        # 第四层防爆：批次之间强制休眠 5 秒，彻底杜绝 RPM 超限
        if i + BATCH_SIZE < len(candidates):
            time.sleep(5)

    # 只保留最近 200 条高质量新闻 & 最近 2000 条已读哈希，保持仓库轻量
    save_json(DATA_FILE, saved_news[:200])
    save_json(SEEN_FILE, list(seen_ids)[-2000:])
    print(f"🎉 运行结束！本次新增 {newly_accepted} 篇高质量（>={SCORE_THRESHOLD}分）新闻。")

if __name__ == "__main__":
    main()
