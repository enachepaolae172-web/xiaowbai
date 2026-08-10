"""Deterministic Markdown rendering and citation auditing."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import Field

from src.conditional_models import ConditionalAnalysisBundle, StrategyChoice
from src.models import EvidencePool, ModuleName, ResearchRequest, StrictModel
from src.strategy_models import RequiredStrategyAnalysis


CITATION_PATTERN = re.compile(r"\[(S\d{2,3})\]")
FACTUAL_LABELS = ("事实：", "判断：", "核心结论：", "分析建议：")

MODULE_LABELS = {
    ModuleName.CONCENTRATION: "行业集中度",
    ModuleName.VALUE_CHAIN: "价值链",
    ModuleName.KEY_SUCCESS_FACTORS: "关键成功要素",
    ModuleName.LIFECYCLE: "产品生命周期",
    ModuleName.INNOVATION_PRICE_SHARE: "创新与价格-份额",
}

PEST_LABELS = {
    "political": "政治/监管",
    "economic": "经济/商业",
    "social": "社会/组织",
    "technological": "技术",
}

FORCE_LABELS = {
    "rivalry": "现有竞争",
    "new_entrants": "潜在进入者",
    "substitutes": "替代品",
    "supplier_power": "供应商议价",
    "buyer_power": "客户议价",
}

ROLE_LABELS = {
    "product_user": "产品使用者",
    "business_owner": "业务负责人",
    "technical_evaluator": "技术评估者",
    "procurement_decider": "采购决策者",
    "final_payer": "最终付费者",
}


class CitationAudit(StrictModel):
    cited_source_ids: list[str] = Field(default_factory=list)
    unknown_source_ids: list[str] = Field(default_factory=list)
    unused_source_ids: list[str] = Field(default_factory=list)
    uncited_fact_lines: list[str] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.unknown_source_ids and not self.uncited_fact_lines


class ReportArtifact(StrictModel):
    markdown: str = Field(min_length=100)
    audit: CitationAudit
    character_count: int = Field(ge=100)
    target_min: int = 2500
    target_max: int = 4000

    @property
    def length_target_met(self) -> bool:
        return self.target_min <= self.character_count <= self.target_max


class MarkdownReportRenderer:
    def render(
        self,
        request: ResearchRequest,
        pool: EvidencePool,
        required: RequiredStrategyAnalysis,
        conditional: ConditionalAnalysisBundle,
    ) -> ReportArtifact:
        subject = request.target_company or request.industry
        lines = [
            f"# {subject}企业战略研究报告",
            "",
            f"- 行业：{request.industry}",
            f"- 地区：{request.region}",
            f"- 研究期间：{request.start_year}–{request.end_year}",
            f"- 战略问题：{request.strategy_question}",
            f"- 生成日期：{datetime.now(timezone.utc).date().isoformat()}",
            "",
            "> 本报告为基于公开资料的研究底稿，不构成投资或经营建议。",
            "",
            "## 1. 核心结论",
            "",
        ]
        for item in required.core_conclusions:
            lines.append(
                f"- 核心结论：{_clean(item.conclusion)} {_citations(item.evidence_ids)} "
                f"（置信度：{item.confidence.value}；反例/不确定性："
                f"{_join(item.counterpoints)}）"
            )

        lines.extend(["", "## 2. 宏观环境分析（PEST）", ""])
        lines.extend(
            [
                "| 维度 | 事实 | 判断 | 影响 | 反例/不确定性 | 分析建议 | 来源/置信度 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for item in required.pest.assessments:
            lines.append(
                "| "
                + " | ".join(
                    [
                        PEST_LABELS[item.dimension.value],
                        _join(item.facts) or "未知",
                        _clean(item.judgment),
                        item.impact.value,
                        _join([*item.counterpoints, *item.unknowns]),
                        _join(item.recommendations),
                        f"{_citations(item.evidence_ids)} / {item.confidence.value}",
                    ]
                )
                + " |"
            )

        market = required.market
        total = market.total_market
        lines.extend(
            [
                "",
                "## 3. 市场、客户与采购",
                "",
                "### 3.1 市场总量与发展阶段",
                "",
                f"- 事实：{_join(total.facts) or '未知'} {_citations(total.evidence_ids)}",
                f"- 判断：{_clean(total.judgment)} {_citations(total.evidence_ids)}",
                f"- 发展阶段：{total.growth_stage.value}。{_clean(total.stage_rationale)} "
                f"{_citations(total.evidence_ids)}",
                f"- 反例/不确定性：{_join([*total.counterpoints, *total.unknowns])}",
                f"- 分析建议：{_join(total.recommendations)} {_citations(total.evidence_ids)}",
            ]
        )
        for series in total.series:
            lines.extend(
                [
                    "",
                    f"**{_clean(series.metric_name)}**",
                    "",
                    "| 年份 | 数值 | 地区 | 单位 | 统计口径 | 类型 | 来源 |",
                    "|---:|---:|---|---|---|---|---|",
                ]
            )
            for point in series.points:
                lines.append(
                    f"| {point.year} | {point.value:g} | {_clean(point.region)} | "
                    f"{_clean(point.unit)} | {_clean(point.statistical_scope)} | "
                    f"{'预测' if point.is_forecast else '实际'} | [{point.source_id}] |"
                )
            if series.cagr:
                source_ids = [point.source_id for point in series.points]
                lines.append(
                    f"- 程序计算 CAGR（{series.cagr.start_year}–{series.cagr.end_year}）："
                    f"{series.cagr.cagr_percent:.2f}% {_citations(source_ids)}"
                )

        customer = market.customer_structure
        lines.extend(
            [
                "",
                "### 3.2 客户结构与决策角色",
                "",
                f"- 事实：{_join(customer.facts) or '未知'} {_citations(customer.evidence_ids)}",
                f"- 判断：{_clean(customer.judgment)} {_citations(customer.evidence_ids)}",
                f"- 分层维度：{_join(customer.segmentation_dimensions)} "
                f"{_citations(customer.evidence_ids)}",
                f"- 优先客群：{_join(customer.priority_segments) or '未知'} "
                f"{_citations(customer.evidence_ids)}",
                f"- 分析建议：{_join(customer.recommendations)} {_citations(customer.evidence_ids)}",
                "",
                "| 角色 | 核心判断 | 反例/未知 | 来源/置信度 |",
                "|---|---|---|---|",
            ]
        )
        for role in customer.roles:
            lines.append(
                f"| {ROLE_LABELS[role.role.value]} | {_clean(role.judgment)} | "
                f"{_join([*role.counterpoints, *role.unknowns])} | "
                f"{_citations(role.evidence_ids)} / {role.confidence.value} |"
            )

        procurement = market.procurement_drivers
        lines.extend(
            [
                "",
                "### 3.3 采购驱动",
                "",
                f"- 判断：{_clean(procurement.judgment)} {_citations(procurement.evidence_ids)}",
                f"- 分析建议：{_join(procurement.recommendations)} {_citations(procurement.evidence_ids)}",
                "",
                "| 优先级 | 驱动因素 | 理由 | 来源 |",
                "|---:|---|---|---|",
            ]
        )
        for driver in sorted(procurement.ranked_drivers, key=lambda item: item.priority):
            lines.append(
                f"| {driver.priority} | {_clean(driver.driver)} | {_clean(driver.rationale)} | "
                f"{_citations(procurement.evidence_ids)} |"
            )
        if not procurement.ranked_drivers:
            lines.append("| - | 未知 | 缺少可核验的采购驱动证据 | - |")

        lines.extend(
            [
                "",
                "## 4. 行业结构（波特五力）",
                "",
                "| 力量 | 压力评分 | 判断 | 反例/不确定性 | 分析建议 | 来源/置信度 |",
                "|---|---:|---|---|---|---|",
            ]
        )
        for force in required.five_forces.assessments:
            score = str(force.pressure_score) if force.pressure_score is not None else "未知"
            lines.append(
                "| "
                + " | ".join(
                    [
                        FORCE_LABELS[force.force.value],
                        score,
                        _clean(force.judgment),
                        _join([*force.counterpoints, force.uncertainty, *force.unknowns]),
                        _join(force.recommendations),
                        f"{_citations(force.evidence_ids)} / {force.confidence.value}",
                    ]
                )
                + " |"
            )

        lines.extend(
            [
                "",
                "## 5. 条件模块决策",
                "",
                "| 模块 | 状态 | 原因 | 缺失证据 | 来源 |",
                "|---|---|---|---|---|",
            ]
        )
        for decision in conditional.decisions:
            lines.append(
                f"| {MODULE_LABELS[decision.module]} | "
                f"{'启用' if decision.enabled else '跳过'} | {_clean(decision.reason)} | "
                f"{_join(decision.missing_evidence) or '-'} | "
                f"{_citations(decision.supporting_source_ids) or '-'} |"
            )
        for decision in conditional.decisions:
            if not decision.enabled or decision.analysis is None:
                continue
            analysis = decision.analysis
            lines.extend(
                [
                    "",
                    f"### 5.{conditional.enabled_modules.index(decision.module) + 1} "
                    f"{MODULE_LABELS[decision.module]}",
                    "",
                    f"- 事实：{_join(analysis.facts)} {_citations(analysis.evidence_ids)}",
                    f"- 判断：{_clean(analysis.judgment)} {_citations(analysis.evidence_ids)}",
                    f"- 反例/不确定性：{_join([*analysis.counterpoints, *analysis.unknowns])}",
                    f"- 分析建议：{_join(analysis.recommendations)} "
                    f"{_citations(analysis.evidence_ids)}",
                ]
            )

        lines.extend(["", "## 6. 战略行动方案", ""])
        self._render_choices(lines, "6.1 目标客户", conditional.action_plan.target_customers)
        self._render_choices(lines, "6.2 产品方向", conditional.action_plan.product_directions)
        self._render_choices(lines, "6.3 渠道方向", conditional.action_plan.channel_directions)
        self._render_choices(lines, "6.4 价值链选择", conditional.action_plan.value_chain_choices)
        lines.extend(
            [
                "",
                "### 6.5 90 天验证计划",
                "",
                "| 里程碑 | 分析建议 | 负责人 | 成功指标 | 来源 |",
                "|---:|---|---|---|---|",
            ]
        )
        for action in sorted(
            conditional.action_plan.validation_actions,
            key=lambda item: item.milestone_day,
        ):
            lines.append(
                f"| 第 {action.milestone_day} 天 | 分析建议：{_clean(action.action)} | "
                f"{_clean(action.owner)} | {_clean(action.success_metric)} | "
                f"{_citations(action.evidence_ids)} |"
            )

        unknowns = list(required.unknowns)
        for decision in conditional.decisions:
            unknowns.extend(decision.missing_evidence)
        lines.extend(["", "## 7. 风险、反例与未知项", ""])
        for item in dict.fromkeys(unknowns):
            lines.append(f"- {_clean(item)}")
        if not unknowns:
            lines.append("- 当前结构化结果未记录额外未知项。")

        body = "\n".join(lines).strip() + "\n"
        lines.extend(["", "## 8. 来源", ""])
        for source in pool.sources:
            published = source.published_at.isoformat() if source.published_at else "日期未知"
            lines.append(
                f"- [{source.source_id}] [{_clean(source.title)}]({source.url})；"
                f"{_clean(source.publisher)}；{published}；{source.tier.value}；{source.origin.value}"
            )
        markdown = "\n".join(lines).strip() + "\n"
        audit = audit_citations(body, pool)
        character_count = report_character_count(markdown)
        return ReportArtifact(
            markdown=markdown,
            audit=audit,
            character_count=character_count,
        )

    @staticmethod
    def _render_choices(
        lines: list[str],
        title: str,
        choices: list[StrategyChoice],
    ) -> None:
        lines.extend(["", f"### {title}", ""])
        for choice in choices:
            lines.append(
                f"- 分析建议：{_clean(choice.choice)}；理由：{_clean(choice.rationale)} "
                f"{_citations(choice.evidence_ids)}（置信度：{choice.confidence.value}）"
            )


def audit_citations(markdown_body: str, pool: EvidencePool) -> CitationAudit:
    known_ids = {source.source_id for source in pool.sources}
    cited_ids = set(CITATION_PATTERN.findall(markdown_body))
    uncited_lines = []
    for line in markdown_body.splitlines():
        stripped = line.strip()
        if any(label in stripped for label in FACTUAL_LABELS) and not CITATION_PATTERN.search(stripped):
            uncited_lines.append(stripped[:300])
    return CitationAudit(
        cited_source_ids=sorted(cited_ids & known_ids),
        unknown_source_ids=sorted(cited_ids - known_ids),
        unused_source_ids=sorted(known_ids - cited_ids),
        uncited_fact_lines=uncited_lines,
    )


def report_character_count(markdown: str) -> int:
    """Count report-body characters without inflating totals with source URLs."""
    body = markdown.split("\n## 8. 来源", maxsplit=1)[0]
    return len(re.sub(r"\s+", "", body))


def _citations(source_ids: list[str]) -> str:
    return " ".join(f"[{source_id}]" for source_id in dict.fromkeys(source_ids))


def _join(values: list[str]) -> str:
    return "；".join(_clean(value) for value in values if value)


def _clean(value: object) -> str:
    return str(value).replace("|", "｜").replace("\r", " ").replace("\n", " ").strip()
