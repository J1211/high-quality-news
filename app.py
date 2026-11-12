import json
import os
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import streamlit as st

st.set_page_config(
    page_title="高信噪比硬核新闻监控",
    page_icon="📡",
    layout="wide"
)

TZ_UTC8 = timezone(timedelta(hours=8))

# ================= 1. 母子联动分类架构配置 =================
# 注：当某频道的 "subs" 为空字典 {} 时，前端会自动隐藏第二排子版块方框（无子频道极简模式）
# 未来若想拓展其他类别小说，只需在 "subs" 中填入 {"科幻小说": ..., "推理悬疑": ...} 即可瞬间开启子方框！
TOPIC_SCHEMA = {
    "AI与硬科技": {
        "icon": "🤖",
        "subs": {
            "算力硬件": {"icon": "🔬", "desc": "芯片 / HBM存储 / 先进封装 / 算力基建"},
            "模型应用": {"icon": "🤖", "desc": "大模型 / 具身机器人 / 智驾 / AI应用"},
            "财报资本": {"icon": "📊", "desc": "季报业绩 / IPO招股书 / 并购 / 估值透视"},
            "宏观政经": {"icon": "🌐", "desc": "贸易数据 / 算力政策 / 管制与产业格局"},
        }
    },
    "影视文化": {
        "icon": "🎬",
        "subs": {
            "深度影评": {"icon": "🎞️", "desc": "剧作文本拆解 / 视听美学 / 导演主创专访"},
            "新片动向": {"icon": "🎬", "desc": "国内外新片新剧前瞻 / 国际影展 / 权威口碑"},
            "行业商业": {"icon": "💼", "desc": "流媒体与影企战略 / 制片成本 / 版权与商业模式"},
            "影视科技": {"icon": "🪄", "desc": "AI影视视效落地 / 虚拟制片 / 拍摄放映工业革新"},
        }
    },
    "科幻小说": {
        "icon": "🪐",
        "subs": {}  # 目前采用无子频道方式建立，点击后直接平铺展示
    }
}

DATA_FILE = "high_quality_news.json"
STATUS_FILE = "status.json"


# ================= 2. 时间转 UTC+8 与存量智能归类工具 =================
def to_utc8_str(raw_str):
    if not raw_str:
        return ""
    s = raw_str.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_UTC8).strftime("%Y-%m-%d %H:%M (UTC+8)")
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.astimezone(TZ_UTC8).strftime("%Y-%m-%d %H:%M (UTC+8)")
        except Exception:
            pass
    return s


def infer_sub_topic(item):
    topic = item.get("topic", "AI与硬科技")
    if topic not in TOPIC_SCHEMA:
        topic = "AI与硬科技"
        item["topic"] = topic

    valid_subs = TOPIC_SCHEMA[topic]["subs"].keys()
    if not valid_subs:
        # 无子频道的独立版块（如科幻小说），预埋同名 sub_topic 以便未来平滑扩容
        return item.get("sub_topic") or topic

    existing_sub = item.get("sub_topic", "")
    if existing_sub in valid_subs:
        return existing_sub

    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('reason', '')}"

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
        if re.search(r"(芯片|半导体|晶圆|台积电|CoWoS|封装|HBM|内存|DRAM|存储|闪存|光模块|光互联|液冷|买电|电力设备|EDA|氮化镓|星闪|手机出货|端侧SoC|征程7|服务器|算力高地)", text):
            return "算力硬件"
        return "模型应用"


def load_news():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                item["sub_topic"] = infer_sub_topic(item)
            return data
    except Exception:
        return []


def load_status():
    if not os.path.exists(STATUS_FILE):
        return None
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ================= 3. 响应式 CSS（兼顾 PC 宽屏与手机端流式紧凑网格） =================
st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
}
div.stButton > button {
    height: 40px !important;
    padding: 0px 10px !important;
    border-radius: 8px !important;
    transition: all 0.15s ease-in-out !important;
    white-space: nowrap !important;
}
div.stButton > button[kind="secondary"] {
    border: 1px solid rgba(250, 250, 250, 0.16) !important;
    background-color: rgba(255, 255, 255, 0.02) !important;
}
div.stButton > button[kind="secondary"]:hover {
    border-color: rgba(255, 75, 75, 0.6) !important;
    background-color: rgba(255, 75, 75, 0.06) !important;
}
div.stButton > button[kind="primary"] {
    border: 1.5px solid #ff4b4b !important;
    background-color: rgba(255, 75, 75, 0.16) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 0 10px rgba(255, 75, 75, 0.22) !important;
}

/* 📱 手机端（屏幕宽度 <= 640px）专属响应式流式网格 */
@media (max-width: 640px) {
    .block-container {
        padding-top: 1rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 0.35rem !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        width: calc(33.33% - 0.35rem) !important;
        flex: 1 1 calc(33.33% - 0.35rem) !important;
        min-width: 102px !important;
    }
    div.stButton > button {
        height: 36px !important;
        padding: 0px 6px !important;
        font-size: 0.82rem !important;
    }
    div[data-testid="stMetric"] {
        display: none !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ================= 4. 头部标题与 UTC+8 巡检状态栏 =================
st.markdown("### 📡 高质量新闻筛选器 (Score ≥ 8.5)")

status_info = load_status()
if status_info:
    dot = "🟢 巡检正常" if status_info.get("healthy", True) else "🔴 巡检异常"
    run_time_utc8 = to_utc8_str(status_info.get("last_run_utc", ""))
    st.caption(
        f"`{dot}` · 🕒 {run_time_utc8} · 本轮新增 **{status_info.get('accepted', 0)}** 篇 "
        f"*(扫描{status_info.get('scanned', 0)} ➔ 拦截{status_info.get('local_filtered', 0)} ➔ 终审{status_info.get('ai_evaluated', 0)} · `{status_info.get('model', '')}`)*"
    )

news_list = load_news()

if "active_topic" not in st.session_state:
    st.session_state.active_topic = "AI与硬科技"
if "selected_subs" not in st.session_state:
    st.session_state.selected_subs = set()

# ================= 5. 第一层：【一级大频道流式网格】 =================
channel_options = list(TOPIC_SCHEMA.keys()) + ["全站总览"]
MAX_CH_PER_ROW = 5

for row_start in range(0, len(channel_options), MAX_CH_PER_ROW):
    row_slice = channel_options[row_start : row_start + MAX_CH_PER_ROW]
    c_cols = st.columns(len(row_slice) if len(channel_options) <= 5 else MAX_CH_PER_ROW)
    for idx, ch_name in enumerate(row_slice):
        if ch_name == "全站总览":
            ch_count = len(news_list)
            ch_label = f"🌐 全站总览 · {ch_count}"
        else:
            ch_count = sum(1 for n in news_list if n.get("topic") == ch_name)
            ch_icon = TOPIC_SCHEMA[ch_name]["icon"]
            ch_label = f"{ch_icon} {ch_name} · {ch_count}"

        is_active_ch = (st.session_state.active_topic == ch_name)
        if c_cols[idx].button(
            ch_label,
            key=f"channel_{ch_name}",
            type="primary" if is_active_ch else "secondary",
            use_container_width=True
        ):
            st.session_state.active_topic = ch_name
            st.session_state.selected_subs = set()
            st.rerun()

current_topic = st.session_state.active_topic

# ================= 6. 第二层：【二级子版块方框】（若该频道无子频道如“科幻小说”，则自动隐藏此层） =================
if current_topic == "全站总览":
    topic_news = news_list
    has_sub_boxes = False
else:
    topic_news = [n for n in news_list if n.get("topic") == current_topic]
    current_subs_dict = TOPIC_SCHEMA[current_topic].get("subs", {})
    has_sub_boxes = bool(current_subs_dict)

if has_sub_boxes:
    sub_keys = list(current_subs_dict.keys())
    MAX_COLS_PER_ROW = 5

    box_items = [{
        "key": "__ALL__",
        "title": f"📦 全部 · {len(topic_news)}",
        "desc": f"展示【{current_topic}】全部硬核报道（点击右侧子版块可多选组合过滤）",
        "is_active": (len(st.session_state.selected_subs) == 0)
    }]

    for sk in sub_keys:
        info = current_subs_dict[sk]
        cnt = sum(1 for n in topic_news if n.get("sub_topic") == sk)
        box_items.append({
            "key": sk,
            "title": f"{info['icon']} {sk} · {cnt}",
            "desc": f"{info['desc']}（支持多选组合点亮，再次点击取消）",
            "is_active": (sk in st.session_state.selected_subs)
        })

    for row_start in range(0, len(box_items), MAX_COLS_PER_ROW):
        row_slice = box_items[row_start : row_start + MAX_COLS_PER_ROW]
        cols = st.columns(MAX_COLS_PER_ROW)
        for idx, box in enumerate(row_slice):
            with cols[idx]:
                if st.button(
                    box["title"],
                    key=f"box_{current_topic}_{box['key']}",
                    help=box["desc"],
                    type="primary" if box["is_active"] else "secondary",
                    use_container_width=True
                ):
                    if box["key"] == "__ALL__":
                        st.session_state.selected_subs = set()
                    else:
                        if box["key"] in st.session_state.selected_subs:
                            st.session_state.selected_subs.remove(box["key"])
                        else:
                            st.session_state.selected_subs.add(box["key"])
                        if len(st.session_state.selected_subs) == len(sub_keys):
                            st.session_state.selected_subs = set()
                    st.rerun()

# ================= 7. 第三层：【评分滑块 + 关键词检索】 =================
col_score, col_kw = st.columns([2, 4])
with col_score:
    min_score = st.slider("🎯 最低评分门槛", min_value=8.5, max_value=10.0, value=8.5, step=0.1)
with col_kw:
    search_kw = st.text_input("🔍 关键词检索", value="", placeholder="搜书名、片名、作家、公司、技术词或打分依据...")

st.divider()

# ================= 8. 新闻列表过滤与卡片渲染 =================
active_subs = st.session_state.selected_subs
filtered = [
    n for n in topic_news
    if (not has_sub_boxes or len(active_subs) == 0 or n.get("sub_topic") in active_subs)
    and float(n.get("score", 0)) >= min_score
    and (not search_kw or search_kw.lower() in (
        n.get("title", "") + n.get("snippet", "") + n.get("key_quotes", "") + n.get("reason", "")
    ).lower())
]

if current_topic == "全站总览":
    filter_tag_str = "🌐 **全站总览**"
elif not has_sub_boxes:
    filter_tag_str = f"{TOPIC_SCHEMA[current_topic]['icon']} **{current_topic}**"
elif len(active_subs) == 0:
    filter_tag_str = f"{TOPIC_SCHEMA[current_topic]['icon']} **{current_topic} › 📦 全部精选**"
else:
    sub_str = " + ".join([f"**{TOPIC_SCHEMA[current_topic]['subs'][s]['icon']} {s}**" for s in TOPIC_SCHEMA[current_topic]['subs'] if s in active_subs])
    filter_tag_str = f"{TOPIC_SCHEMA[current_topic]['icon']} **{current_topic}** › {sub_str}"

if not filtered:
    st.info(f"当前筛选条件（{filter_tag_str}）下暂无符合条件的文章。如刚新增【科幻小说】频道，请前往 GitHub Actions 手动运行一次即可拉取过去7天的科幻精品。")
else:
    st.caption(f"当前视图：{filter_tag_str} 　|　 共匹配 **{len(filtered)}** 篇硬核报道")
    for item in filtered:
        t_name = item.get("topic", "AI与硬科技")
        t_schema = TOPIC_SCHEMA.get(t_name, TOPIC_SCHEMA["AI与硬科技"])
        sub_name = item.get("sub_topic", "")
        pub_time_utc8 = to_utc8_str(item.get("pub_date", ""))
        score_val = item.get("score", 8.5)

        # 若该频道有子版块则显示面包屑 `一级 › 二级`，若无子版块（如科幻小说）则直接显示 `🪐 科幻小说`
        if t_schema.get("subs") and sub_name in t_schema["subs"]:
            sub_icon = t_schema["subs"][sub_name]["icon"]
            path_badge = f"`{t_name} › {sub_icon} {sub_name}`"
        else:
            path_badge = f"`{t_schema.get('icon', '🪐')} {t_name}`"

        with st.container(border=True):
            c_title, c_score = st.columns([5, 1])
            with c_title:
                st.markdown(f"### [{item['title']}]({item['url']})")
                st.caption(
                    f"`🌟 {score_val}分`  {path_badge} 　|　 "
                    f"📰 {item.get('source', '未知')} 　|　 "
                    f"🕒 {pub_time_utc8}"
                )
            with c_score:
                st.metric(label="质量评分", value=f"{score_val} / 10")

            key_quotes = item.get("key_quotes", "").strip()
            if key_quotes:
                st.write(f"**📊 核心原句摘录：** “{key_quotes}”")
            else:
                st.write(f"**原文前导：** {item.get('snippet', '')}")

            st.success(f"⚖️ **入选依据：** {item.get('reason', '')}  *(评审模型: `{item.get('model', '')}`)*")

            full_body = item.get("body", "").strip()
            if full_body:
                with st.expander("📖 展开阅读无广告纯净全文"):
                    st.markdown(full_body.replace("\n", "\n\n"))
