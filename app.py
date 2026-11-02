import json
import os
import re
import streamlit as st

st.set_page_config(
    page_title="高信噪比硬核新闻监控",
    page_icon="📡",
    layout="wide"
)

# ================= 1. 母子联动分类架构配置 (方案 B 扩容底座) =================
# 未来拓展新领域时，只需在此字典新增一个大类及其对应的 4 个四字子版块即可，UI 自动适配！
TOPIC_SCHEMA = {
    "AI与硬科技": {
        "算力硬件": {"icon": "🔬", "desc": "芯片 / HBM存储 / 先进封装 / 算力基建"},
        "模型应用": {"icon": "🤖", "desc": "大模型 / 具身机器人 / 智驾 / AI应用"},
        "财报资本": {"icon": "📊", "desc": "季报业绩 / IPO招股书 / 并购 / 估值透视"},
        "宏观政经": {"icon": "🌐", "desc": "贸易数据 / 算力政策 / 管制与产业格局"},
    }
    # 未来拓展预留示例（取消注释即可自动激活顶部一级频道切换栏）：
    # "全球金融与商业": {
    #     "巨头财报": {"icon": "📑", "desc": "美股港股A股核心财报与指引"},
    #     "股债汇商": {"icon": "💹", "desc": "利率 / 汇率 / 黄金原油与资金流"},
    #     "并购资本": {"icon": "🏦", "desc": "大型并购 / 一二级投融与机构持仓"},
    #     "金融风险": {"icon": "⚠️", "desc": "信贷利差 / 债务违约与市场异动"},
    # }
}

DATA_FILE = "high_quality_news.json"

# ================= 2. 存量文章智能归类引擎 (100%兼容现有79篇数据) =================
def infer_sub_topic(item):
    """若文章已有合法的 sub_topic 则直接用；若无（如存量79篇），则按内容精准归入4大子版块"""
    topic = item.get("topic", "AI与硬科技")
    valid_subs = TOPIC_SCHEMA.get(topic, TOPIC_SCHEMA["AI与硬科技"]).keys()
    existing_sub = item.get("sub_topic", "")
    if existing_sub in valid_subs:
        return existing_sub

    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('reason', '')}"

    # 1. 宏观政经判定
    if re.search(r"(进出口|海关总署|数据局|美联储|利率|央行|自主可控|乌兰察布|冷焦虑|出口管制|掀桌|关税|国家标准|顶层设计)", text):
        return "宏观政经"
    # 2. 财报资本判定
    if re.search(r"(财报|三季报|季报|Q3|Q4|营收|净利|利润|毛利率|IPO|招股书|估值|并购|收购|持仓|张坤|次贷|现金流|回购|分红|市盈率|增持|主力资金|闯关创业板|资本开支)", text):
        return "财报资本"
    # 3. 算力硬件判定
    if re.search(r"(芯片|半导体|晶圆|台积电|CoWoS|封装|HBM|内存|DRAM|存储|闪存|光模块|光互联|液冷|买电|电力设备|EDA|氮化镓|星闪|手机出货|端侧SoC|征程7|服务器|算力高地)", text):
        return "算力硬件"
    # 4. 其余归入模型应用
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


# ================= 3. 定制方框卡片 CSS 样式 =================
st.markdown("""
<style>
/* 将按钮改造为高颜值仪表盘方框卡片 */
div.stButton > button {
    height: auto !important;
    padding: 14px 10px !important;
    border-radius: 10px !important;
    transition: all 0.18s ease-in-out !important;
    white-space: pre-wrap !important;
    line-height: 1.45 !important;
}
/* 未选中态方框：深色微光边框 */
div.stButton > button[kind="secondary"] {
    border: 1px solid rgba(250, 250, 250, 0.16) !important;
    background-color: rgba(255, 255, 255, 0.02) !important;
}
div.stButton > button[kind="secondary"]:hover {
    border-color: rgba(255, 75, 75, 0.6) !important;
    background-color: rgba(255, 75, 75, 0.06) !important;
}
/* 选中点亮态方框：高亮边框与底色 */
div.stButton > button[kind="primary"] {
    border: 2px solid #ff4b4b !important;
    background-color: rgba(255, 75, 75, 0.16) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 0 12px rgba(255, 75, 75, 0.25) !important;
}
</style>
""", unsafe_allow_html=True)

# ================= 4. 页面头部与母子联动方框状态管理 =================
st.title("📡 高质量新闻筛选器 (Score ≥ 8.5)")
st.caption("过滤流量党、情绪化渲染与商业软文 · 仅保留高事实密度、有横向基准数据的一手报道")

news_list = load_news()

# 初始化 Session State
if "active_topic" not in st.session_state:
    st.session_state.active_topic = "AI与硬科技"
if "selected_subs" not in st.session_state:
    st.session_state.selected_subs = set()  # 空集合代表选中“📦 全部精选”

# 如果未来配置了多个一级大领域，自动渲染顶部一级大频道切换条（方案 B 母子联动）
all_topics = list(TOPIC_SCHEMA.keys())
if len(all_topics) > 1:
    t_cols = st.columns(len(all_topics))
    for idx, t_name in enumerate(all_topics):
        t_count = sum(1 for n in news_list if n.get("topic", "AI与硬科技") == t_name)
        is_active_t = (st.session_state.active_topic == t_name)
        if t_cols[idx].button(
            f"📡 {t_name} ({t_count})",
            key=f"topic_{t_name}",
            type="primary" if is_active_t else "secondary",
            use_container_width=True
        ):
            st.session_state.active_topic = t_name
            st.session_state.selected_subs = set()
            st.rerun()

current_topic = st.session_state.active_topic
current_schema = TOPIC_SCHEMA.get(current_topic, TOPIC_SCHEMA["AI与硬科技"])
topic_news = [n for n in news_list if n.get("topic", "AI与硬科技") == current_topic]

# ================= 5. 五宫格“可多选开关方框” (交互形态 B) =================
st.markdown("##### 🧩 版块点选（支持点击多个方框进行组合筛选，再次点击可取消选中）")

sub_keys = list(current_schema.keys())
total_boxes = 1 + len(sub_keys)
MAX_COLS_PER_ROW = 5  # 每行最多 5 个方框，超出自动换行

# 构建所有方框的数据项
box_items = [{
    "key": "__ALL__",
    "title": f"📦 全部精选  ·  {len(topic_news)} 篇",
    "desc": "展示当前领域全部硬核报道",
    "is_active": (len(st.session_state.selected_subs) == 0)
}]

for sk in sub_keys:
    info = current_schema[sk]
    cnt = sum(1 for n in topic_news if n.get("sub_topic") == sk)
    box_items.append({
        "key": sk,
        "title": f"{info['icon']} {sk}  ·  {cnt} 篇",
        "desc": info["desc"],
        "is_active": (sk in st.session_state.selected_subs)
    })

# 按每行最多 5 格渲染自适应方框网格
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
                    # 点击“全部精选”清空子版块多选状态
                    st.session_state.selected_subs = set()
                else:
                    # 形态 B：多选开关切换（已选中则移除，未选中则加入组合）
                    if box["key"] in st.session_state.selected_subs:
                        st.session_state.selected_subs.remove(box["key"])
                    else:
                        st.session_state.selected_subs.add(box["key"])
                    # 若 4 个子方框全部被点亮，自动归位为“全部精选”
                    if len(st.session_state.selected_subs) == len(sub_keys):
                        st.session_state.selected_subs = set()
                st.rerun()

# ================= 6. 辅助过滤栏（评分滑块 + 关键词检索） =================
col_score, col_kw = st.columns([2, 5])
with col_score:
    min_score = st.slider("🎯 最低评分门槛", min_value=8.5, max_value=10.0, value=8.5, step=0.1)
with col_kw:
    search_kw = st.text_input("🔍 关键词检索（支持搜公司名、技术词、数据或打分依据）", "")

st.divider()

# ================= 7. 新闻列表过滤与卡片渲染 =================
active_subs = st.session_state.selected_subs
filtered = [
    n for n in topic_news
    if (len(active_subs) == 0 or n.get("sub_topic") in active_subs)
    and float(n.get("score", 0)) >= min_score
    and (not search_kw or search_kw.lower() in (n.get("title", "") + n.get("snippet", "") + n.get("reason", "")).lower())
]

# 显示当前筛选状态提示
if len(active_subs) == 0:
    filter_tag_str = "📦 **全部精选**"
else:
     filter_tag_str = " + ".join([f"**{current_schema[s]['icon']} {s}**" for s in sub_keys if s in active_subs])

if not filtered:
    st.info(f"当前筛选条件（{filter_tag_str}）下暂无符合条件的文章。")
else:
    st.markdown(f"当前视图：{filter_tag_str} 　|　 共匹配出 **{len(filtered)}** 篇硬核报道：")
    for item in filtered:
        sub_name = item.get("sub_topic", "模型应用")
        sub_icon = current_schema.get(sub_name, {}).get("icon", "🏷️")

        with st.container(border=True):
            c_title, c_score = st.columns([5, 1])
            with c_title:
                st.markdown(f"### [{item['title']}]({item['url']})")
                st.caption(
                    f"🧩 **版块：** `{sub_icon} {sub_name}` 　|　 "
                    f"📰 **来源：** {item.get('source', '未知')} 　|　 "
                    f"🕒 **发布：** {item.get('pub_date', '')}"
                )
            with c_score:
                st.metric(label="质量评分", value=f"{item['score']} / 10")

            st.write(f"**原文前导：** {item.get('snippet', '')}")
            st.success(f"⚖️ **入选依据：** {item.get('reason', '')}  *(评审模型: `{item.get('model', '')}`)*")
