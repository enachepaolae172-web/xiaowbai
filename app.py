"""Streamlit product interface for the Enterprise AI Strategy Research Agent."""

from __future__ import annotations

from pydantic import ValidationError
import streamlit as st

from src.config import APP_VERSION
from src.model_client import DoubaoError, DoubaoModelClient
from src.models import RunMode, ResearchRequest
from src.pipeline import (
    PipelineError,
    ResearchPipeline,
    ResearchRunResult,
    SampleResearchRepository,
)
from src.research_model import ModelOutputValidationError
from src.search import SearchError, TavilySearchClient


PEST_LABELS = {
    "political": "政治与监管",
    "economic": "经济与商业",
    "social": "社会与组织",
    "technological": "技术",
}
FORCE_LABELS = {
    "rivalry": "现有竞争",
    "new_entrants": "潜在进入者",
    "substitutes": "替代品",
    "supplier_power": "供应商议价能力",
    "buyer_power": "客户议价能力",
}
MODULE_LABELS = {
    "concentration": "行业集中度",
    "value_chain": "价值链",
    "key_success_factors": "关键成功要素",
    "lifecycle": "产品生命周期",
    "innovation_price_share": "创新与价格份额",
}


st.set_page_config(
    page_title="企业战略研究助手",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown(
    """
    <style>
      :root { color-scheme: light; }
      html, body, [class*="css"] { letter-spacing: 0; }
      [data-testid="stAppViewContainer"] { background: #f6f7f5; color: #19201c; }
      [data-testid="stHeader"] { background: rgba(246, 247, 245, 0.94); }
      [data-testid="stSidebar"] {
        background: #e9eeeb;
        border-right: 1px solid #cfd7d2;
      }
      .block-container { max-width: 1260px; padding-top: 2rem; padding-bottom: 4rem; }
      h1 { font-size: 2.35rem !important; line-height: 1.15 !important; }
      h2 { font-size: 1.35rem !important; }
      h3 { font-size: 1.05rem !important; }
      div[data-testid="stForm"] {
        background: #ffffff;
        border: 1px solid #d9dfdb;
        border-radius: 6px;
        padding: 1.1rem;
      }
      div[data-testid="stMetric"] {
        border-left: 3px solid #24705a;
        padding: 0.25rem 0 0.25rem 0.75rem;
      }
      div[data-testid="stMetric"] label { color: #53605a; }
      .stButton button, .stDownloadButton button { border-radius: 5px; }
      button[kind="primary"], .stDownloadButton button[kind="primary"] {
        background: #1f6a54;
        border-color: #1f6a54;
      }
      [data-baseweb="tab-list"] { gap: 0.35rem; border-bottom: 1px solid #d5dcd7; }
      [data-baseweb="tab"] { border-radius: 0; padding-left: 0.7rem; padding-right: 0.7rem; }
      [data-testid="stDataFrame"] { border: 1px solid #d9dfdb; border-radius: 4px; }
      @media (max-width: 700px) {
        .block-container { padding: 1rem 0.85rem 3rem; }
        h1 { font-size: 1.85rem !important; }
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        div[data-testid="stHorizontalBlock"] > div { min-width: 240px; flex: 1 1 100%; }
        div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div {
          min-width: 145px;
          flex: 1 1 45%;
        }
        [data-baseweb="tab-list"] { overflow-x: auto; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def load_sample_result() -> ResearchRunResult:
    return SampleResearchRepository().load()


def join_text(values: list[str]) -> str:
    return "；".join(value for value in values if value) or "未知"


def citations(values: list[str]) -> str:
    return " ".join(f"[{value}]" for value in values)


def render_choices(title: str, values) -> None:
    st.markdown(f"### {title}")
    for item in values:
        st.markdown(f"**{item.choice}**")
        st.write(item.rationale)
        st.caption(f"来源 {citations(item.evidence_ids)} · 置信度 {item.confidence.value}")


def render_result(result: ResearchRunResult, *, display_mode: str) -> None:
    st.divider()
    heading, download = st.columns([4, 1])
    with heading:
        st.subheader("研究结果")
        st.caption(
            f"当前展示：{display_mode} · {result.request.target_company or result.request.industry}"
        )
    with download:
        st.download_button(
            "下载 Markdown",
            data=result.artifact.markdown.encode("utf-8"),
            file_name="enterprise-strategy-report.md",
            mime="text/markdown",
            type="primary",
            width="stretch",
        )

    metric_columns = st.columns(4)
    metric_columns[0].metric("证据来源", len(result.pool.sources))
    metric_columns[1].metric("启用扩展模块", len(result.conditional.enabled_modules))
    metric_columns[2].metric("报告字符", result.artifact.character_count)
    metric_columns[3].metric(
        "引用核验",
        "通过" if result.artifact.audit.is_valid else "待处理",
    )

    tabs = st.tabs(
        ["核心结论", "宏观与市场", "行业结构", "战略建议", "来源与未知项"]
    )

    with tabs[0]:
        st.markdown("## 核心结论")
        for index, item in enumerate(result.required.core_conclusions, start=1):
            st.markdown(f"### {index:02d}  {item.conclusion}")
            st.write(f"反例或不确定性：{join_text(item.counterpoints)}")
            st.caption(
                f"来源 {citations(item.evidence_ids)} · 置信度 {item.confidence.value}"
            )

        st.markdown("## 研究问题")
        for item in result.plan.questions:
            st.markdown(f"**{item.question}**")
            st.caption(f"优先级 {item.priority} · {item.area.value}")

    with tabs[1]:
        st.markdown("## PEST")
        pest_rows = []
        for item in result.required.pest.assessments:
            pest_rows.append(
                {
                    "维度": PEST_LABELS[item.dimension.value],
                    "事实": join_text(item.facts),
                    "判断": item.judgment,
                    "影响": item.impact.value,
                    "反例/未知": join_text([*item.counterpoints, *item.unknowns]),
                    "来源": citations(item.evidence_ids),
                }
            )
        st.dataframe(pest_rows, width="stretch", hide_index=True)

        market = result.required.market
        st.markdown("## 市场与客户")
        st.markdown(f"**市场判断：** {market.total_market.judgment}")
        st.write(f"发展阶段：{market.total_market.growth_stage.value}")
        st.write(f"优先客群：{join_text(market.customer_structure.priority_segments)}")
        st.write(f"客户结构判断：{market.customer_structure.judgment}")
        procurement = market.procurement_drivers
        driver_rows = [
            {
                "排序": item.priority,
                "采购驱动": item.driver,
                "判断": item.rationale,
                "来源": citations(procurement.evidence_ids),
            }
            for item in procurement.ranked_drivers
        ]
        if driver_rows:
            st.markdown("### 采购驱动")
            st.dataframe(driver_rows, width="stretch", hide_index=True)

    with tabs[2]:
        st.markdown("## 波特五力")
        force_rows = []
        for item in result.required.five_forces.assessments:
            force_rows.append(
                {
                    "力量": FORCE_LABELS[item.force.value],
                    "压力评分": item.pressure_score or "未知",
                    "判断": item.judgment,
                    "反例/未知": join_text(
                        [*item.counterpoints, item.uncertainty, *item.unknowns]
                    ),
                    "来源": citations(item.evidence_ids),
                }
            )
        st.dataframe(force_rows, width="stretch", hide_index=True)

        enabled = [item for item in result.conditional.decisions if item.enabled]
        if enabled:
            st.markdown("## 已启用的扩展分析")
        for decision in enabled:
            analysis = decision.analysis
            if analysis is None:
                continue
            st.markdown(f"### {MODULE_LABELS[decision.module.value]}")
            st.write(analysis.summary)
            st.markdown(f"**判断：** {analysis.judgment}")
            st.write(f"反例或不确定性：{join_text([*analysis.counterpoints, *analysis.unknowns])}")
            st.caption(
                f"来源 {citations(analysis.evidence_ids)} · 置信度 {analysis.confidence.value}"
            )

    with tabs[3]:
        plan = result.conditional.action_plan
        render_choices("目标客户", plan.target_customers)
        render_choices("产品方向", plan.product_directions)
        render_choices("渠道方向", plan.channel_directions)
        render_choices("价值链选择", plan.value_chain_choices)

        st.markdown("## 90 天验证计划")
        action_rows = [
            {
                "节点": f"第 {item.milestone_day} 天",
                "行动": item.action,
                "负责人": item.owner,
                "成功标准": item.success_metric,
                "来源": citations(item.evidence_ids),
            }
            for item in sorted(plan.validation_actions, key=lambda value: value.milestone_day)
        ]
        st.dataframe(action_rows, width="stretch", hide_index=True)

    with tabs[4]:
        st.markdown("## 来源与核验")
        if result.pool.warnings:
            for warning in result.pool.warnings:
                st.warning(warning)
        source_rows = [
            {
                "编号": source.source_id,
                "来源": source.title,
                "机构": source.publisher,
                "等级": source.tier.value,
                "内容": source.origin.value,
                "日期": source.published_at.isoformat() if source.published_at else "未知",
                "链接": str(source.url),
            }
            for source in result.pool.sources
        ]
        st.dataframe(
            source_rows,
            width="stretch",
            hide_index=True,
            column_config={"链接": st.column_config.LinkColumn("链接")},
        )

        st.markdown("## 跳过模块与未知项")
        skipped_rows = [
            {
                "模块": MODULE_LABELS[item.module.value],
                "原因": item.reason,
                "缺失证据": join_text(item.missing_evidence),
            }
            for item in result.conditional.decisions
            if not item.enabled
        ]
        if skipped_rows:
            st.dataframe(skipped_rows, width="stretch", hide_index=True)
        unknowns = list(result.required.unknowns)
        for item in result.conditional.decisions:
            unknowns.extend(item.missing_evidence)
        for item in dict.fromkeys(unknowns):
            st.markdown(f"- {item}")

        with st.expander("完整 Markdown 报告"):
            st.markdown(result.artifact.markdown)


with st.sidebar:
    st.subheader("运行设置")
    mode = st.segmented_control(
        "运行模式",
        options=["样例模式", "实时模式"],
        default="样例模式",
        selection_mode="single",
    )
    is_realtime = mode == "实时模式"
    doubao_api_key = st.text_input(
        "豆包 API Key",
        type="password",
        disabled=not is_realtime,
        placeholder="仅在当前会话中使用",
    )
    tavily_api_key = st.text_input(
        "Tavily API Key",
        type="password",
        disabled=not is_realtime,
        placeholder="仅在当前会话中使用",
    )
    test_doubao = st.button(
        "测试豆包连接",
        disabled=not is_realtime or not doubao_api_key,
        width="stretch",
    )
    if test_doubao:
        try:
            with st.spinner("正在测试豆包连接..."):
                connection = DoubaoModelClient(api_key=doubao_api_key).test_connection()
            st.success(
                "连接成功 · "
                f"{connection.model} · "
                f"{connection.input_tokens + connection.output_tokens} tokens"
            )
        except DoubaoError as exc:
            st.error(str(exc))
    st.caption("密钥不会写入报告、日志或项目文件。")


try:
    sample_result = load_sample_result()
except (OSError, ValueError, PipelineError) as exc:
    st.error(f"样例数据加载失败：{exc}")
    st.stop()

if "research_result" not in st.session_state:
    st.session_state.research_result = sample_result
    st.session_state.result_mode = "样例模式"
if st.session_state.get("selected_mode") != mode:
    st.session_state.selected_mode = mode
    if mode == "样例模式":
        st.session_state.research_result = sample_result
        st.session_state.result_mode = "样例模式"


st.title("企业战略研究助手")
st.caption(f"Enterprise AI Strategy Research Agent · {APP_VERSION}")

st.subheader("研究参数")
sample_request = sample_result.request
with st.form("research_parameters"):
    left, right = st.columns(2)
    with left:
        industry = st.text_input(
            "行业",
            value=sample_request.industry,
            disabled=not is_realtime,
        )
        region = st.text_input(
            "地区",
            value=sample_request.region,
            disabled=not is_realtime,
        )
        target_company = st.text_input(
            "研究对象（选填）",
            value=sample_request.target_company or "",
            disabled=not is_realtime,
        )
    with right:
        start_year = st.number_input(
            "开始年份",
            min_value=2000,
            max_value=2100,
            value=sample_request.start_year,
            disabled=not is_realtime,
        )
        end_year = st.number_input(
            "结束年份",
            min_value=2000,
            max_value=2100,
            value=sample_request.end_year,
            disabled=not is_realtime,
        )
    strategy_question = st.text_area(
        "战略问题",
        value=sample_request.strategy_question,
        height=96,
        disabled=not is_realtime,
    )
    missing_keys = is_realtime and (not doubao_api_key or not tavily_api_key)
    submitted = st.form_submit_button(
        "开始研究" if is_realtime else "重新加载样例",
        type="primary",
        disabled=missing_keys,
    )

if is_realtime and (not doubao_api_key or not tavily_api_key):
    st.info("实时模式需要豆包和 Tavily API Key。")
elif is_realtime:
    st.caption("完整研究会多次调用搜索与模型，通常需要 1-3 分钟，请保持页面开启。")

if submitted:
    if not is_realtime:
        st.session_state.research_result = sample_result
        st.session_state.result_mode = "样例模式"
    else:
        try:
            request = ResearchRequest(
                industry=industry,
                region=region,
                start_year=int(start_year),
                end_year=int(end_year),
                target_company=target_company,
                strategy_question=strategy_question,
                mode=RunMode.REALTIME,
            )
            with st.status("研究任务运行中", expanded=True) as status:
                def update_progress(stage: str, message: str) -> None:
                    status.write(message)

                pipeline = ResearchPipeline(
                    DoubaoModelClient(api_key=doubao_api_key),
                    TavilySearchClient(api_key=tavily_api_key),
                )
                result = pipeline.run(request, progress=update_progress)
                status.update(label="研究报告已完成", state="complete", expanded=False)
            st.session_state.research_result = result
            st.session_state.result_mode = "实时模式"
        except ValidationError as exc:
            st.error(f"研究参数不符合要求：{exc.errors(include_input=False)[0]['msg']}")
        except (DoubaoError, SearchError, ModelOutputValidationError, PipelineError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("研究任务未完成，请检查网络与 API 配置后重试。")


render_result(
    st.session_state.research_result,
    display_mode=st.session_state.result_mode,
)
