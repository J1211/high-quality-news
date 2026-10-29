import json
import os
import streamlit as st

st.set_page_config(
    page_title="高信噪比硬核新闻监控",
    page_icon="📡",
    layout="wide"
)

st.title("📡 高质量新闻筛选器 (Score ≥ 8.5)")
st.caption("过滤流量党、情绪化渲染与商业软文 · 仅保留高事实密度、有横向基准数据的一手报道")

DATA_FILE = "high_quality_news.json"

def load_news():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

news_list = load_news()

# 顶部筛选栏
col1, col2, col3 = st.columns([2, 2, 4])
with col1:
    topics = ["全部领域"] + sorted(list({item.get("topic", "AI与硬科技") for item in news_list}))
    selected_topic = st.selectbox("📂 领域筛选", topics)
with col2:
    min_score = st.slider("🎯 最低评分门槛", min_value=8.5, max_value=10.0, value=8.5, step=0.1)
with col3:
    search_kw = st.text_input("🔍 关键词检索（标题/摘要/打分依据）", "")

st.divider()

# 过滤展示
filtered = [
    n for n in news_list
    if (selected_topic == "全部领域" or n.get("topic") == selected_topic)
    and float(n.get("score", 0)) >= min_score
    and (not search_kw or search_kw.lower() in (n.get("title", "") + n.get("snippet", "") + n.get("reason", "")).lower())
]

if not filtered:
    st.info("当前条件下暂无符合 ≥ 8.5 分严苛标准的新闻。请等待 GitHub Actions 定时任务拉取更新，或手动在 GitHub Actions 中触发一次运行。")
else:
    st.markdown(f"共筛选出 **{len(filtered)}** 篇硬核报道：")
    for item in filtered:
        with st.container(border=True):
            c_title, c_score = st.columns([5, 1])
            with c_title:
                st.markdown(f"### [{item['title']}]({item['url']})")
                st.caption(f"📰 **来源：** {item.get('source', '未知')} 　|　 🕒 **发布：** {item.get('pub_date', '')} 　|　 🏷️ **分类：** `{item.get('topic', 'AI与硬科技')}`")
            with c_score:
                st.metric(label="质量评分", value=f"{item['score']} / 10")

            # 原文导语（未加工）
            st.write(f"**原文前导：** {item.get('snippet', '')}")

            # AI 评审通过依据
            st.success(f"⚖️ **入选依据：** {item.get('reason', '')}  *(评审模型: `{item.get('model', '')}`)*")
