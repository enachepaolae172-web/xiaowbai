"""Streamlit entry point for the Enterprise AI Strategy Research Agent."""

import streamlit as st

from src.config import APP_NAME, APP_VERSION


st.set_page_config(
    page_title=APP_NAME,
    page_icon=None,
    layout="wide",
    initial_sidebar_state="auto",
)

with st.sidebar:
    st.subheader("运行设置")
    mode = st.segmented_control(
        "运行模式",
        options=["样例模式", "实时模式"],
        default="样例模式",
        selection_mode="single",
    )
    st.text_input(
        "豆包 API Key",
        type="password",
        disabled=mode != "实时模式",
        placeholder="仅在当前会话中使用",
    )
    st.text_input(
        "Tavily API Key",
        type="password",
        disabled=mode != "实时模式",
        placeholder="仅在当前会话中使用",
    )

st.title("企业战略研究助手")
st.caption(f"Enterprise AI Strategy Research Agent · {APP_VERSION}")

st.subheader("研究参数")

with st.form("research_parameters"):
    left, right = st.columns(2)
    with left:
        st.text_input("行业", value="企业级 AI Agent")
        st.text_input("地区", value="中国")
        st.text_input("研究对象（选填）", value="火山引擎")
    with right:
        st.number_input("开始年份", min_value=2000, max_value=2100, value=2024)
        st.number_input("结束年份", min_value=2000, max_value=2100, value=2026)

    st.text_area(
        "战略问题",
        value="火山引擎应优先服务哪些客户群，并形成怎样的差异化？",
        height=96,
    )
    st.form_submit_button("开始研究", type="primary", disabled=True)

st.divider()
st.subheader("研究结果")
st.info("尚未运行研究任务。")
