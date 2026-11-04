import json
import os
import re
import streamlit as st

st.set_page_config(
    page_title="高信噪比硬核新闻监控",
    page_icon="📡",
    layout="wide"
)

# ================= 1. 母子联动分类架构配置 (双版块正式启用) =================
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

# ================= 2. 存量与兜底智能归类引擎 =================
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


# ================= 3. 定制方框卡片 CSS 样式 =================
st.markdown("""
<style>
div.stButton > button {
    height: auto !important;
    padding: 13px 10px !important;
    border-radius: 10px !important;
    transition: all 0.18s ease-in-out !important;
    white-space: pre-wrap !important;
    line-height: 1.45 !important;
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
    border: 2px solid #ff4b4b !important;
    background-color: rgba(255, 75, 75, 0.16) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 0 12px rgba(255, 75, 75, 0.25) !important;
}
</style>
""", unsafe_allow_html=True)

# ================= 4. 页面头部与后台巡检健康状态栏 =================
st.title("📡 高质量新闻筛选器 (Score ≥ 8.5)")
st.caption("过滤流量党、情绪化渲染与商业软文 · 仅保留高事实密度、有横向基准或深度思考价值的一手报道")

status_info = load_status()
if status_info:
    dot = "🟢 巡检正常" if status_info.get("healthy", True) else "🔴 巡检异常"
    st.caption(
        f"`{dot}` 　|　 **最近巡检：** {status_info.get('last_run_utc', '')} 　|　 "
        f"**本轮漏斗：** 扫描新条目 {status_info.get('scanned', 0)} 篇 ➔ "
        f"本地拦截 {status_info.get('local_filtered', 0)} 篇 ➔ "
        f"AI 终审 {status_info.get('ai_evaluated', 0)} 篇 ➔ "
        f"新增入选 **{status_info.get('accepted', 0)}** 篇 　|　 "
        f"**引擎：** `{status_info.get('model', '')}`"
    )

news_list = load_news()

if "active_topic" not in st.session_state:
    st.session_state.active_topic = "AI与硬科技"
if "selected_subs" not in st.session_state:
    st.session_state.selected_subs = set()

# ================= 5. 一级大频道切换栏 =================
st.markdown("##### 🧭 一级频道切换")
channel_options = list(TOPIC_SCHEMA.keys()) + ["全站总览"]
c_cols = st.columns(len(channel_options))

for idx, ch_name in enumerate(channel_options):
    if ch_name == "全站总览":
        ch_count = len(news_list)
        ch_icon = "🌐"
    else:
        ch_count = sum(1 for n in news_list if n.get("topic") == ch_name)
        ch_icon = TOPIC_SCHEMA[ch_name]["icon"]

    is_active_ch = (st.session_state.active_topic == ch_name)
    if c_cols[idx].button(
        f"{ch_icon} {ch_name}  ({ch_count} 篇)",
        key=f"channel_{ch_name}",
        type="primary" if is_active_ch else "secondary",
        use_container_width=True
    ):
        st.session_state.active_topic = ch_name
        st.session_state.selected_subs = set()
        st.rerun()

current_topic = st.session_state.active_topic

# ================= 6. 二级五宫格“可多选开关方框” (交互形态 B) =================
if current_topic != "全站总览":
    current_subs_dict = TOPIC_SCHEMA[current_topic]["subs"]
    topic_news = [n for n in news_list if n.get("topic") == current_topic]

    st.markdown("##### 🧩 子版块点选（支持同时点亮多个方框组合筛选，再次点击可取消选中）")
    sub_keys = list(current_subs_dict.keys())
    MAX_COLS_PER_ROW = 5

    box_items = [{
        "key": "__ALL__",
        "title": f"📦 全部精选  ·  {len(topic_news)} 篇",
        "desc": f"展示【{current_topic}】全部硬核报道",
        "is_active": (len(st.session_state.selected_subs) == 0)
    }]

    for sk in sub_keys:
        info = current_subs_dict[sk]
        cnt = sum(1 for n in topic_news if n.get("sub_topic") == sk)
        box_items.append({
            "key": sk,
            "title": f"{info['icon']} {sk}  ·  {cnt} 篇",
            "desc": info["desc"],
            "is_active": (sk in st.session_state.selected_subs)
        })

    for row_start in range(0, len(box_items), MAX_COLS_PER_ROW):
        row_slice = box_items[row_start : row_start + MAX_COLS_PER_ROW]
        cols = st.columns(MAX_COLS_PER_ROW)
        for idx, box in enumerate(row_slice):
            with cols[idx]:
                btn_label = f"{box['title']}\n{box['desc']}"
                if st.button(
                    btn_label,
                    key=f"box_{current_topic}_{box['key']}",
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

# ================= 7. 辅助过滤栏（评分滑块 + 关键词检索） =================
col_score, col_kw = st.columns([2, 5])
with col_score:
    min_score = st.slider("🎯 最低评分门槛", min_value=8.5, max_value=10.0, value=8.5, step=0.1)
with col_kw:
    search_kw = st.text_input("🔍 关键词检索（支持搜片名、公司名、技术词、数据或打分依据）", "")

st.divider()

# ================= 8. 新闻列表过滤与卡片渲染 (样式 1：面包屑路径式) =================
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
    st.info(f"当前筛选条件（{filter_tag_str}）下暂无符合条件的文章。如刚新增【影视文化】版块，请前往 GitHub Actions 手动触发一次运行即可拉取最新内容。")
else:
    st.markdown(f"当前视图：{filter_tag_str} 　|　 共匹配出 **{len(filtered)}** 篇硬核报道：")
    for item in filtered:
        t_name = item.get("topic", "AI与硬科技")
        sub_name = item.get("sub_topic", "模型应用")
        sub_icon = TOPIC_SCHEMA.get(t_name, {}).get("subs", {}).get(sub_name, {}).get("icon", "🏷️")

        with st.container(border=True):
            c_title, c_score = st.columns([5, 1])
            with c_title:
                st.markdown(f"### [{item['title']}]({item['url']})")
                # 样式 1：【面包屑路径式】一级 › 二级（保持原始发布时间展示）
                st.caption(
                    f"`{t_name} › {sub_icon} {sub_name}` 　|　 "
                    f"📰 {item.get('source', '未知')} 　|　 "
                    f"🕒 {item.get('pub_date', '')}"
                )
            with c_score:
                st.metric(label="质量评分", value=f"{item['score']} / 10")

            # 优先展示 AI 一字不改摘录的“核心数据/核心论断原句”，存量旧数据自动平滑回退显示“原文前导”
            key_quotes = item.get("key_quotes", "").strip()
            if key_quotes:
                st.write(f"**📊 核心原句摘录：** “{key_quotes}”")
            else:
                st.write(f"**原文前导：** {item.get('snippet', '')}")

            st.success(f"⚖️ **入选依据：** {item.get('reason', '')}  *(评审模型: `{item.get('model', '')}`)*")

            # 页面内无广告纯净全文折叠阅读器（新抓取的文章均带有 body 字段）
            full_body = item.get("body", "").strip()
            if full_body:
                with st.expander("📖 展开阅读无广告纯净全文"):
                    st.markdown(full_body.replace("\n", "\n\n"))
