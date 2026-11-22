import json
import os
import re
import time
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="高信噪比硬核新闻监控",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

TZ_UTC8 = timezone(timedelta(hours=8))

# ================= 1. 7 大深度门类母子联动架构配置（保持原样） =================
TOPIC_SCHEMA = {
    "AI与硬科技": {
        "icon": "🤖",
        "subs": {
            "算力硬件": {"icon": "🔬"},
            "模型应用": {"icon": "🤖"},
            "财报资本": {"icon": "📊"},
            "宏观政经": {"icon": "🌐"},
        }
    },
    "宏观与金融": {
        "icon": "🏦",
        "subs": {
            "央行宏观": {"icon": "🏦"},
            "股债汇商": {"icon": "💹"},
            "巨头并购": {"icon": "📑"},
            "金融风险": {"icon": "⚠️"},
        }
    },
    "国际与地缘": {
        "icon": "🌍",
        "subs": {
            "贸易关税": {"icon": "🚢"},
            "法案管制": {"icon": "⚖️"},
            "能源矿产": {"icon": "⚡"},
            "国际政局": {"icon": "🏛️"},
        }
    },
    "新能源与制造": {
        "icon": "🔋",
        "subs": {
            "智驾车企": {"icon": "🚗"},
            "电力储能": {"icon": "⚡"},
            "航天低空": {"icon": "🚀"},
            "出海制造": {"icon": "🏭"},
        }
    },
    "影视文化": {
        "icon": "🎬",
        "subs": {
            "深度影评": {"icon": "🎞️"},
            "新片动向": {"icon": "🎬"},
            "行业商业": {"icon": "💼"},
            "影视科技": {"icon": "🪄"},
        }
    },
    "前沿科学": {
        "icon": "🧬",
        "subs": {}
    },
    "科幻小说": {
        "icon": "🪐",
        "subs": {}
    }
}

DATA_FILE = "high_quality_news.json"
TRENDING_FILE = "trending_news.json"
GOSSIP_FILE = "gossip_news.json"
STATUS_FILE = "status.json"
PAGE_SIZE = 25
ACTIVE_SURGE_HOURS = 3.5


# ================= 2. 辅助工具函数 =================
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


def format_hours_ago(erupted_ts, now_ts, suffix="爆发"):
    diff_sec = max(0, now_ts - int(erupted_ts))
    hours = diff_sec / 3600.0
    if hours < 1.0:
        mins = max(1, int(diff_sec / 60))
        return f"{mins}分钟前{suffix}"
    return f"{int(hours)}小时前{suffix}"


def make_unique_expander_label(base_label, unique_seed):
    h = int(hashlib.md5(unique_seed.encode("utf-8")).hexdigest()[:8], 16)
    zw_suffix = "".join("\u200b" if (h >> bit) & 1 else "\u200c" for bit in range(16))
    return base_label + zw_suffix


def infer_sub_topic(item):
    topic = item.get("topic", "AI与硬科技")
    if topic not in TOPIC_SCHEMA:
        topic = "AI与硬科技"
        item["topic"] = topic

    valid_subs = list(TOPIC_SCHEMA[topic]["subs"].keys())
    if not valid_subs:
        return item.get("sub_topic") or topic

    existing_sub = item.get("sub_topic", "")
    if existing_sub in valid_subs:
        return existing_sub

    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('reason', '')}"

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

    return valid_subs[0]


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


def load_48h_json(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            now_ts = int(time.time())
            data = json.load(f)
            return [
                item for item in data
                if (now_ts - int(item.get("first_erupted_ts", now_ts))) <= 48 * 3600
            ]
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


# ================= 3. 响应式 CSS =================
st.markdown("""
<style>
.block-container,
div[data-testid="stAppViewBlockContainer"] {
    padding-top: 4.2rem !important;
    padding-bottom: 2rem !important;
}
section[data-testid="stSidebar"] .block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 1.5rem !important;
}
div.stButton > button {
    height: 40px !important;
    padding: 0px 10px !important;
    border-radius: 8px !important;
    transition: all 0.15s ease-in-out !important;
    white-space: nowrap !important;
}
section[data-testid="stSidebar"] div.stButton > button {
    margin-bottom: 2px !important;
}
div.stButton > button[kind="secondary"] {
    border: 1px solid rgba(250, 250, 250, 0.15) !important;
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

@media (max-width: 640px) {
    .block-container,
    div[data-testid="stAppViewBlockContainer"] {
        padding-top: 3.8rem !important;
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

news_list = load_news()
trending_list = load_48h_json(TRENDING_FILE)
gossip_list = load_48h_json(GOSSIP_FILE)
status_info = load_status()

if "active_topic" not in st.session_state:
    st.session_state.active_topic = "AI与硬科技"
if "selected_subs" not in st.session_state:
    st.session_state.selected_subs = set()
if "display_limit" not in st.session_state:
    st.session_state.display_limit = PAGE_SIZE
if "need_scroll_top" not in st.session_state:
    st.session_state.need_scroll_top = False
if "scroll_seq" not in st.session_state:
    st.session_state.scroll_seq = 0


def switch_channel(target_topic):
    """切换频道时重置子选态、分页并触发自动滚回顶部"""
    st.session_state.active_topic = target_topic
    st.session_state.selected_subs = set()
    st.session_state.display_limit = PAGE_SIZE
    st.session_state.need_scroll_top = True
    st.rerun()


# ================= 4. 左侧固定导航栏 =================
with st.sidebar:
    st.markdown("### 📡 硬核新闻监控")

    # 1. 置顶独立雷达：🔥 热点风向标
    is_trending_active = (st.session_state.active_topic == "热点风向标")
    if st.button(
        f"🔥 热点风向标 ({len(trending_list)})",
        key="sidebar_ch_trending",
        type="primary" if is_trending_active else "secondary",
        use_container_width=True
    ):
        switch_channel("热点风向标")

    # 2. 紧跟热点风向标下方：🍉 全球抓马台（独立 JSON，不混入全站总览）
    is_gossip_active = (st.session_state.active_topic == "全球抓马台")
    if st.button(
        f"🍉 全球抓马台 ({len(gossip_list)})",
        key="sidebar_ch_gossip",
        type="primary" if is_gossip_active else "secondary",
        use_container_width=True
    ):
        switch_channel("全球抓马台")

    st.divider()

    # 3. 原有 7 大深度门类 + 全站总览
    channel_options = list(TOPIC_SCHEMA.keys()) + ["全站总览"]
    for ch_name in channel_options:
        if ch_name == "全站总览":
            ch_count = len(news_list)
            ch_label = f"🌐 全站总览 ({ch_count})"
        else:
            ch_count = sum(1 for n in news_list if n.get("topic") == ch_name)
            ch_icon = TOPIC_SCHEMA[ch_name]["icon"]
            ch_label = f"{ch_icon} {ch_name} ({ch_count})"

        is_active_ch = (st.session_state.active_topic == ch_name)
        if st.button(
            ch_label,
            key=f"sidebar_ch_{ch_name}",
            type="primary" if is_active_ch else "secondary",
            use_container_width=True
        ):
            switch_channel(ch_name)

    st.divider()

    min_score = st.slider("🎯 最低评分门槛 (深度门类)", min_value=8.5, max_value=10.0, value=8.5, step=0.1)
    search_kw = st.text_input("🔍 关键词检索", value="", placeholder="搜公司、技术、作品、事件...")

    if status_info:
        st.divider()
        dot = "🟢 巡检正常" if status_info.get("healthy", True) else "🔴 巡检异常"
        run_time_utc8 = to_utc8_str(status_info.get("last_run_utc", ""))
        st.caption(
            f"**{dot}**\n\n"
            f"🕒 {run_time_utc8}\n\n"
            f"📊 扫描 {status_info.get('scanned', 0)} ➔ 拦截 {status_info.get('local_filtered', 0)} "
            f"➔ 终审 {status_info.get('ai_evaluated', 0)} ➔ **新增 {status_info.get('accepted', 0)} 篇**\n\n"
            f"🤖 `{status_info.get('model', '')}`"
        )

current_topic = st.session_state.active_topic


# ================= 5. 分支视图 A：【🔥 热点风向标】 =================
def render_trending_card(item, layer_tag, now_ts, view_key):
    pub_time_utc8 = to_utc8_str(item.get("pub_date", ""))
    score_val = item.get("score", 8.5)
    vel_badge = item.get("velocity_badge", "🚀 热度飙升")
    res_badge = item.get("resonance_badge", "📡 多方聚焦")
    region_tag = item.get("region_tag", "国内热点")
    erupted_ts = item.get("first_erupted_ts", now_ts)
    ago_str = format_hours_ago(erupted_ts, now_ts, suffix="爆发")

    with st.container(border=True):
        c_title, c_score = st.columns([5, 1])
        with c_title:
            st.markdown(f"### [{item['title']}]({item['url']})")
            st.caption(
                f"`{vel_badge}`  `{res_badge}`  `{region_tag} · {ago_str}` 　|　 "
                f"📰 {item.get('source', '主流媒体')} 　|　 "
                f"🕒 {pub_time_utc8}"
            )
        with c_score:
            st.metric(label="飙升热度分", value=f"{score_val} / 10")

        key_quotes = item.get("key_quotes", "").strip()
        if key_quotes:
            st.write(f"**📊 核心原句摘录：** “{key_quotes}”")
        else:
            st.write(f"**原文前导：** {item.get('snippet', '')}")

        st.info(f"⚡ **热点风向解读：** {item.get('reason', '')}  *(把关引擎: `{item.get('model', '')}`)*")

        full_body = item.get("body", "").strip()
        if full_body:
            unique_seed = f"trending_{item.get('url', '')}_{item.get('title', '')}_{layer_tag}_{view_key}"
            exp_label = make_unique_expander_label("📖 展开阅读无广告纯净全文", unique_seed)
            with st.expander(exp_label):
                st.markdown(full_body.replace("\n", "\n\n"))


if current_topic == "热点风向标":
    now_ts = int(time.time())
    filtered_trending = [
        t for t in trending_list
        if not search_kw or search_kw.lower() in (
            t.get("title", "") + t.get("hot_keyword", "") + t.get("key_quotes", "") + t.get("reason", "")
        ).lower()
    ]

    upper_surging = [
        t for t in filtered_trending
        if (now_ts - int(t.get("first_erupted_ts", now_ts))) <= ACTIVE_SURGE_HOURS * 3600
    ]
    lower_recent = [
        t for t in filtered_trending
        if (now_ts - int(t.get("first_erupted_ts", now_ts))) > ACTIVE_SURGE_HOURS * 3600
    ]

    trending_sort_key = lambda x: (float(x.get("score", 0)), int(x.get("first_erupted_ts", 0)))
    upper_surging.sort(key=trending_sort_key, reverse=True)
    lower_recent.sort(key=trending_sort_key, reverse=True)

    st.caption(
        f"当前视图：🔥 **热点风向标（混合双擎：平台热榜 1h 飙升斜率 + 国内外权威华文媒体短时共振）** 　|　 "
        f"48小时有效池共 **{len(filtered_trending)}** 条"
    )

    if not filtered_trending:
        st.info("当前暂无热点数据。请前往 GitHub Actions 手动运行一次 `Run workflow` 即可拉取最新热点。")
    else:
        st.markdown(f"#### 🔥 正在极速飙升（近 3 小时内新晋爆发 · {len(upper_surging)} 条）")
        if not upper_surging:
            st.caption("✨ 近 3 小时暂无新晋突发入库，以下为过去 48 小时已爆发的重点风向：")
        else:
            for item in upper_surging:
                render_trending_card(item, "upper", now_ts, search_kw)

        if lower_recent:
            st.divider()
            st.markdown(f"#### 📌 过去 48 小时热点回溯（已进入平稳期，满 48h 自动代谢 · {len(lower_recent)} 条）")
            for item in lower_recent:
                render_trending_card(item, "lower", now_ts, search_kw)


# ================= 6. 分支视图 B：【🍉 全球抓马台】（按 Drama 吸睛分从高到低排列，48h 自动清瓜） =================
elif current_topic == "全球抓马台":
    now_ts = int(time.time())
    filtered_gossip = [
        g for g in gossip_list
        if not search_kw or search_kw.lower() in (
            g.get("title", "") + g.get("orig_title", "") + g.get("drama_summary", "") + g.get("spicy_quote", "")
        ).lower()
    ]

    # 按 Drama 吸睛分从高到低排，同分按最新爆出时间排
    filtered_gossip.sort(
        key=lambda x: (float(x.get("score", 0)), int(x.get("first_erupted_ts", 0))),
        reverse=True
    )

    st.caption(
        f"当前视图：🍉 **全球抓马台（国内/港台八卦 + TMZ · Page Six · Daily Mail 全球一手瓜，按 Drama 程度排序 · 48h代谢）** 　|　 "
        f"当前瓜池共 **{len(filtered_gossip)}** 条"
    )

    if not filtered_gossip:
        st.info("🍉 全球抓马台刚建好，瓜池暂空！请前往 GitHub Actions 手动点一次 `Run workflow`，立刻收割第一批全球高能大瓜！")
    else:
        for item in filtered_gossip:
            pub_time_utc8 = to_utc8_str(item.get("pub_date", ""))
            score_val = item.get("score", 8.5)
            drama_tag = item.get("drama_tag", "🌟 娱乐圈大瓜")
            origin_hint = item.get("origin_hint", "🍉 全球瓜田")
            erupted_ts = item.get("first_erupted_ts", now_ts)
            ago_str = format_hours_ago(erupted_ts, now_ts, suffix="爆出")

            with st.container(border=True):
                c_title, c_score = st.columns([5, 1])
                with c_title:
                    st.markdown(f"### [{item['title']}]({item['url']})")
                    st.caption(
                        f"`🍉 {score_val}分`  `{drama_tag}`  `{origin_hint} · {ago_str}` 　|　 "
                        f"📰 {item.get('source', '八卦源')} 　|　 "
                        f"🕒 {pub_time_utc8}"
                    )
                with c_score:
                    st.metric(label="Drama 吸睛分", value=f"{score_val} / 10")

                drama_summary = item.get("drama_summary", "").strip()
                if drama_summary:
                    st.write(f"**🍉 3秒省流吃瓜：** {drama_summary}")

                spicy_quote = item.get("spicy_quote", "").strip()
                if spicy_quote:
                    st.warning(f"🌶️ **炸裂原话/细节：** “{spicy_quote}”  *(吃瓜引擎: `{item.get('model', '')}`)*")

                full_body = item.get("body", "").strip()
                if full_body:
                    lang_hint = "（英文一手原稿）" if item.get("lang") == "en" else ""
                    unique_seed = f"gossip_{item.get('url', '')}_{item.get('title', '')}_{search_kw}"
                    exp_label = make_unique_expander_label(f"📖 展开看吃瓜原文{lang_hint}", unique_seed)
                    with st.expander(exp_label):
                        if item.get("lang") == "en" and item.get("orig_title"):
                            st.caption(f"**Original Headline:** {item['orig_title']}")
                        st.markdown(full_body.replace("\n", "\n\n"))


# ================= 7. 分支视图 C：原有 7 大深度门类与全站总览（保持原样） =================
else:
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
            "is_active": (len(st.session_state.selected_subs) == 0)
        }]

        for sk in sub_keys:
            info = current_subs_dict[sk]
            cnt = sum(1 for n in topic_news if n.get("sub_topic") == sk)
            box_items.append({
                "key": sk,
                "title": f"{info['icon']} {sk} · {cnt}",
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
                        st.session_state.display_limit = PAGE_SIZE
                        st.session_state.need_scroll_top = True
                        st.rerun()

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

    st.caption(f"当前视图：{filter_tag_str} 　|　 共匹配 **{len(filtered)}** 篇硬核报道")

    if not filtered:
        st.info(f"当前筛选条件（{filter_tag_str}）下暂无符合条件的文章。")
    else:
        visible_items = filtered[:st.session_state.display_limit]
        view_state_key = f"{current_topic}_{','.join(sorted(list(active_subs)))}_{min_score}_{search_kw}"

        for item in visible_items:
            t_name = item.get("topic", "AI与硬科技")
            t_schema = TOPIC_SCHEMA.get(t_name, TOPIC_SCHEMA["AI与硬科技"])
            sub_name = item.get("sub_topic", "")
            pub_time_utc8 = to_utc8_str(item.get("pub_date", ""))
            score_val = item.get("score", 8.5)

            if t_schema.get("subs") and sub_name in t_schema["subs"]:
                sub_icon = t_schema["subs"][sub_name]["icon"]
                path_badge = f"`{t_name} › {sub_icon} {sub_name}`"
            else:
                path_badge = f"`{t_schema.get('icon', '📡')} {t_name}`"

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
                    unique_seed = f"{item.get('url', '')}_{item.get('title', '')}_{view_state_key}"
                    exp_label = make_unique_expander_label("📖 展开阅读无广告纯净全文", unique_seed)
                    with st.expander(exp_label):
                        st.markdown(full_body.replace("\n", "\n\n"))

        if len(filtered) > st.session_state.display_limit:
            remaining = len(filtered) - st.session_state.display_limit
            if st.button(f"⏬ 加载更多历史文章（还有 {remaining} 篇）", use_container_width=True):
                st.session_state.display_limit += PAGE_SIZE
                st.rerun()

# ================= 8. 切换板块/子版块自动滚回顶部脚本（零高度隐形注入） =================
if st.session_state.need_scroll_top:
    st.session_state.need_scroll_top = False
    st.session_state.scroll_seq += 1
    components.html(
        f"""
        <script>
        // scroll_seq: {st.session_state.scroll_seq}
        (function() {{
            const doc = window.parent.document;
            const selectors = [
                'section[data-testid="stMain"]',
                'div[data-testid="stAppViewContainer"]',
                'section.main',
                '.main'
            ];
            selectors.forEach(function(sel) {{
                const el = doc.querySelector(sel);
                if (el) el.scrollTo({{ top: 0, behavior: 'instant' }});
            }});
            window.parent.scrollTo(0, 0);
        }})();
        </script>
        """,
        height=0,
    )
