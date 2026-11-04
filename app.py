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
    }
}

DATA_FILE = "high_quality_news.json"
STATUS_FILE = "status.json"


# ================= 2. 时间转 UTC+8 与存量智能归类工具 =================
def to_utc8_str(raw_str):
    """将 GMT / UTC 时间字符串统一转换为 YYYY-MM-DD HH:MM (UTC+8)"""
    if not raw_str:
        return ""
    s = raw_str.strip()
    # 1. 解析 RSS 标准时间 (如: Thu, 29 Oct 2026 06:47:05 GMT)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_UTC8).strftime("%Y-%m-%d %H:%M (UTC+8)")
    except Exception:
        pass
    # 2. 解析 status.json 时间 (如: 2026-11-04 06:48 UTC)
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


# ================= 3. 定制紧凑主控台与方框 CSS 样式 =================
st.markdown("""
<style>
/* 压缩页面顶部留白 */
.block-container {
    padding-top: 2rem !important;
}
/* 按钮通用紧凑圆角样式 */
div.stButton > button {
    height: 42px !important;
    padding: 0px 12px !important;
    border-radius: 8px !important;
    transition: all 0.16s ease-in-out !important;
}
/* 未选中态：微光深色边框 */
div.stButton > button[kind="secondary"] {
    border: 1px solid rgba(250, 250, 250, 0.16) !important;
    background-color: rgba(255, 255, 255, 0.02) !important;
}
div.stButton > button[kind="secondary"]:hover {
    border-color: rgba(255, 75, 75, 0.6) !important;
    background-color: rgba(255, 75, 75, 0.06) !important;
}
/* 选中点亮态：高亮红框与微发光 */
div.stButton > button[kind="primary"] {
    border: 1.5px solid #ff4b4b !important;
    background-color: rgba(255, 75, 75, 0.15) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 0 10px rgba(255, 75, 75, 0.22) !important;
}
</style>
""", unsafe_allow_html=True)

# ================= 4. 头部标题与 UTC+8 巡检状态栏 =================
st.title("📡 高质量新闻筛选器 (Score ≥ 8.5)")

status_info = load_status()
if status_info:
    dot = "🟢 巡检正常" if status_info.get("healthy", True) else "🔴 巡检异常"
    run_time_utc8 = to_utc8_str(status_info.get("last_run_utc", ""))
    st.caption(
        f"`{dot}` 　|　 **最近巡检：** {run_time_utc8} 　|　 "
        f"**本轮漏斗：** 扫描 {status_info.get('scanned', 0)} ➔ "
        f"拦截 {status_info.get('local_filtered', 0)} ➔ "
        f"终审 {status_info.get('ai_evaluated', 0)} ➔ "
        f"新增入选 **{status_info.get('accepted', 0)}** 篇 　|　 "
        f"**引擎：** `{status_info.get('model', '')}`"
    )

news_list = load_news()

if "active_topic" not in st.session_state:
    st.session_state.active_topic = "AI与硬科技"
if "selected_subs" not in st.session_state:
    st.session_state.selected_subs = set()

# ================= 5. 第一行：【主控台合一】（频道切换 + 评分门槛 + 搜索框同行对齐） =================
c1, c2, c3, c_score, c_search = st.columns([1.25, 1.15, 1.15, 1.25, 2.7])

channel_options = list(TOPIC_SCHEMA.keys()) + ["全站总览"]
channel_cols = [c1, c2, c3]

for idx, ch_name in enumerate(channel_options):
    if ch_name == "全站总览":
        ch_count = len(news_list)
        ch_icon = "🌐"
        ch_label = f"{ch_icon} 全站 · {ch_count}"
    else:
        ch_count = sum(1 for n in news_list if n.get("topic") == ch_name)
        ch_icon = TOPIC_SCHEMA[ch_name]["icon"]
        ch_label = f"{ch_icon} {ch_name} · {ch_count}"

    is_active_ch = (st.session_state.active_topic == ch_name)
    if channel_cols[idx].button(
        ch_label,
        key=f"channel_{ch_name}",
        type="primary" if is_active_ch else "secondary",
        use_container_width=True
    ):
        st.session_state.active_topic = ch_name
        st.session_state.selected_subs = set()
        st.rerun()

with c_score:
    score_options = [8.5, 8.6, 8.7, 8.8, 8.9, 9.0, 9.2, 9.5]
    min_score = st.selectbox(
        "最低评分门槛",
        options=score_options,
        index=0,
        format_func=lambda x: f"🎯 门槛 ≥ {x:.1f} 分",
        label_visibility="collapsed"
    )

with c_search:
    search_kw = st.text_input(
        "关键词检索",
        value="",
        placeholder="🔍 搜索片名、公司、技术词、数据或打分依据...",
        label_visibility="collapsed"
    )

current_topic = st.session_state.active_topic

# ================= 6. 第二行：【纯粹五宫格多选方框】（零废话标题、悬停看说明） =================
if current_topic != "全站总览":
    current_subs_dict = TOPIC_SCHEMA[current_topic]["subs"]
    topic_news = [n for n in news_list if n.get("topic") == current_topic]
    sub_keys = list(current_subs_dict.keys())
    MAX_COLS_PER_ROW = 5

    box_items = [{
        "key": "__ALL__",
        "title": f"📦 全部精选 · {len(topic_news)}",
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
else:
    topic_news = news_list

st.divider()

# ================= 7. 新闻列表过滤与卡片渲染 (样式 1 面包屑 + UTC+8 时间) =================
active_subs = st.session_state.selected_subs
filtered = [
    n for n in topic_news
    if (current_topic == "全站总览" or len(active_subs) == 0 or n.get("sub_topic") in active_subs)
    and float(n.get("score", 0)) >= min_score
    and (not search_kw or search_kw.lower() in (
        n.get("title", "") + n.get("snippet", "") + n.get("key_quotes", "") + n.get("reason", "")
    ).lower())
]

if current_topic == "全站总览":
    filter_tag_str = "🌐 **全站总览**"
elif len(active_subs) == 0:
    filter_tag_str = f"{TOPIC_SCHEMA[current_topic]['icon']} **{current_topic} › 📦 全部精选**"
else:
    sub_str = " + ".join([f"**{TOPIC_SCHEMA[current_topic]['subs'][s]['icon']} {s}**" for s in TOPIC_SCHEMA[current_topic]['subs'] if s in active_subs])
    filter_tag_str = f"{TOPIC_SCHEMA[current_topic]['icon']} **{current_topic}** › {sub_str}"

if not filtered:
    st.info(f"当前筛选条件（{filter_tag_str}）下暂无符合条件的文章。")
else:
    st.caption(f"当前视图：{filter_tag_str} 　|　 共匹配 **{len(filtered)}** 篇硬核报道")
    for item in filtered:
        t_name = item.get("topic", "AI与硬科技")
        sub_name = item.get("sub_topic", "模型应用")
        sub_icon = TOPIC_SCHEMA.get(t_name, {}).get("subs", {}).get(sub_name, {}).get("icon", "🏷️")
        pub_time_utc8 = to_utc8_str(item.get("pub_date", ""))

        with st.container(border=True):
            c_title, c_score = st.columns([5, 1])
            with c_title:
                st.markdown(f"### [{item['title']}]({item['url']})")
                st.caption(
                    f"`{t_name} › {sub_icon} {sub_name}` 　|　 "
                    f"📰 {item.get('source', '未知')} 　|　 "
                    f"🕒 {pub_time_utc8}"
                )
            with c_score:
                st.metric(label="质量评分", value=f"{item['score']} / 10")

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
