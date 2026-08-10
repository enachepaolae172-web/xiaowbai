"""Mandatory PEST, market, customer, procurement, and five-forces analysis."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable
from typing import Any

from src.metrics import compute_market_series_growth
from src.model_client import DoubaoError
from src.models import (
    Confidence,
    ContentOrigin,
    EvidenceExtraction,
    EvidencePool,
    ResearchRequest,
)
from src.ports import ModelClient
from src.research_model import (
    ModelOutputValidationError,
    compact_source_registry,
    generate_validated_model,
)
from src.strategy_models import (
    CustomerRole,
    CustomerRoleAssessment,
    CustomerStructureAssessment,
    EvidenceBackedFinding,
    ExternalImpact,
    FiveForcesAnalysis,
    FiveForcesModuleOutput,
    ForceAssessment,
    ForceName,
    GrowthStage,
    MarketAnalysis,
    MarketModuleOutput,
    MarketTotalAssessment,
    PestAnalysis,
    PestAssessment,
    PestDimension,
    PestModuleOutput,
    ProcurementAssessment,
    RequiredStrategyAnalysis,
    StrategicConclusion,
    StrategicImplication,
)


class RequiredAnalysisService:
    """Generate and verify the three mandatory strategy modules."""

    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def analyze(
        self,
        request: ResearchRequest,
        pool: EvidencePool,
        extraction: EvidenceExtraction,
    ) -> RequiredStrategyAnalysis:
        if not pool.sources:
            raise ValueError("evidence pool must contain at least one source")
        self._validate_extraction_ids(pool, extraction)

        payload = {
            "request": request.model_dump(mode="json"),
            "source_registry": compact_source_registry(pool),
            "extracted_evidence": extraction.model_dump(mode="json"),
        }
        module_failures: list[str] = []
        try:
            pest = generate_validated_model(
                client=self.client,
                task="required_pest_analysis",
                payload=payload,
                model_type=PestModuleOutput,
                error_label="PEST 分析",
            ).pest
        except (DoubaoError, ModelOutputValidationError) as exc:
            module_failures.append(f"PEST 模块已降级：{exc}")
            pest = _unknown_pest()

        try:
            market = generate_validated_model(
                client=self.client,
                task="required_market_analysis",
                payload=payload,
                model_type=MarketModuleOutput,
                error_label="市场与客户分析",
                normalizer=_split_mixed_market_series,
            ).market
        except (DoubaoError, ModelOutputValidationError) as exc:
            module_failures.append(f"市场模块已降级：{exc}")
            market = _unknown_market()

        try:
            five_forces = generate_validated_model(
                client=self.client,
                task="required_five_forces_analysis",
                payload=payload,
                model_type=FiveForcesModuleOutput,
                error_label="波特五力分析",
            ).five_forces
        except (DoubaoError, ModelOutputValidationError) as exc:
            module_failures.append(f"五力模块已降级：{exc}")
            five_forces = _unknown_five_forces()
        analysis = _assemble_required_analysis(
            pest=pest,
            market=market,
            five_forces=five_forces,
            extraction=extraction,
        )
        analysis.unknowns = [*analysis.unknowns, *module_failures][:20]
        self._filter_market_period(request, analysis)
        self._validate_source_references(pool, analysis)
        self._compute_growth_metrics(analysis)
        return analysis

    @staticmethod
    def _validate_extraction_ids(
        pool: EvidencePool,
        extraction: EvidenceExtraction,
    ) -> None:
        expected = {source.source_id for source in pool.sources}
        actual = {item.source_id for item in extraction.items}
        if expected != actual:
            raise ModelOutputValidationError(
                "证据抽取结果与证据池来源编号不一致。"
            )
        sources = {source.source_id: source for source in pool.sources}
        for item in extraction.items:
            if (
                sources[item.source_id].origin is ContentOrigin.SEARCH_SNIPPET
                and item.facts
            ):
                raise ModelOutputValidationError(
                    f"{item.source_id} 只有搜索摘要，不能包含抽取事实。"
                )

    @staticmethod
    def _filter_market_period(
        request: ResearchRequest,
        analysis: RequiredStrategyAnalysis,
    ) -> None:
        total_market = analysis.market.total_market
        excluded_years: set[int] = set()
        retained_series = []
        for series in total_market.series:
            retained_points = []
            for point in series.points:
                if request.start_year <= point.year <= request.end_year:
                    retained_points.append(point)
                else:
                    excluded_years.add(point.year)
            if retained_points:
                series.points = retained_points
                series.cagr = None
                retained_series.append(series)

        total_market.series = retained_series
        if excluded_years and len(total_market.unknowns) < 8:
            years = ", ".join(str(year) for year in sorted(excluded_years))
            total_market.unknowns = [
                *total_market.unknowns,
                f"已排除研究期间 {request.start_year}-{request.end_year} 之外的市场数据：{years}。",
            ]

    @staticmethod
    def _validate_source_references(
        pool: EvidencePool,
        analysis: RequiredStrategyAnalysis,
    ) -> None:
        sources = {source.source_id: source for source in pool.sources}
        referenced_ids = set(_analysis_evidence_ids(analysis))
        unknown_ids = sorted(referenced_ids - set(sources))
        if unknown_ids:
            raise ModelOutputValidationError(
                "必选战略分析引用了未知来源：" + ", ".join(unknown_ids)
            )

        snippet_ids = sorted(
            source_id
            for source_id in referenced_ids
            if sources[source_id].origin is ContentOrigin.SEARCH_SNIPPET
        )
        if snippet_ids:
            raise ModelOutputValidationError(
                "搜索摘要不能支撑分析事实或评分：" + ", ".join(snippet_ids)
            )

    @staticmethod
    def _compute_growth_metrics(analysis: RequiredStrategyAnalysis) -> None:
        total_market = analysis.market.total_market
        for series in total_market.series:
            if len(series.points) >= 2:
                series.cagr = compute_market_series_growth(series)
                continue

            series.cagr = None
            note = f"{series.metric_name}仅有单期数据，无法计算 CAGR 或判断趋势。"
            if note not in total_market.unknowns and len(total_market.unknowns) < 8:
                total_market.unknowns = [*total_market.unknowns, note]


def _analysis_findings(
    analysis: RequiredStrategyAnalysis,
) -> Iterable[EvidenceBackedFinding]:
    yield from analysis.pest.assessments
    yield analysis.market.total_market
    yield analysis.market.customer_structure
    yield from analysis.market.customer_structure.roles
    yield analysis.market.procurement_drivers
    yield from analysis.five_forces.assessments


def _assemble_required_analysis(
    *,
    pest,
    market,
    five_forces,
    extraction: EvidenceExtraction,
) -> RequiredStrategyAnalysis:
    findings: list[EvidenceBackedFinding] = [
        market.customer_structure,
        market.total_market,
        market.procurement_drivers,
        *pest.assessments,
        *five_forces.assessments,
    ]
    supported = next(
        (item for item in findings if item.evidence_ids and item.facts),
        None,
    )

    if supported is not None:
        evidence_ids = supported.evidence_ids
        conclusion = supported.judgment
        counterpoints = supported.counterpoints
        confidence = supported.confidence
        action = supported.recommendations[0]
        rationale = supported.judgment
    else:
        extracted = next(
            (item for item in extraction.items if item.facts),
            None,
        )
        if extracted is None:
            raise ModelOutputValidationError(
                "公开证据不足，无法形成可引用的基础战略结论。"
            )
        evidence_ids = [extracted.source_id]
        conclusion = "现有公开证据不足以支持明确的战略优先级。"
        counterpoints = ["仍需补充客户、市场和竞争数据后再作判断。"]
        confidence = Confidence.LOW
        action = "先补充关键客户访谈和同口径市场数据。"
        rationale = extracted.facts[0].statement

    unknowns = list(
        dict.fromkeys(
            unknown
            for finding in findings
            for unknown in finding.unknowns
        )
    )[:20]
    return RequiredStrategyAnalysis(
        pest=pest,
        market=market,
        five_forces=five_forces,
        core_conclusions=[
            StrategicConclusion(
                conclusion=conclusion,
                evidence_ids=evidence_ids,
                counterpoints=counterpoints or ["仍需通过一手调研复核。"],
                confidence=confidence,
            )
        ],
        strategic_implications=[
            StrategicImplication(
                action=action,
                rationale=rationale,
                evidence_ids=evidence_ids,
                validation_step="在 30 天内通过客户访谈或 PoC 核验该判断。",
                confidence=confidence,
            )
        ],
        unknowns=unknowns,
    )


def _unknown_finding_values(subject: str) -> dict[str, Any]:
    return {
        "facts": [],
        "judgment": f"当前证据或模型输出不足，暂不能判断{subject}。",
        "recommendations": [f"补充{subject}的正式来源与一手访谈后复核。"],
        "evidence_ids": [],
        "counterpoints": ["缺少证据时不应形成确定性判断。"],
        "unknowns": [f"{subject}证据不足。"],
        "confidence": Confidence.UNKNOWN,
    }


def _unknown_pest() -> PestAnalysis:
    return PestAnalysis(
        assessments=[
            PestAssessment(
                dimension=dimension,
                impact=ExternalImpact.UNKNOWN,
                **_unknown_finding_values(f"{dimension.value}环境"),
            )
            for dimension in PestDimension
        ]
    )


def _unknown_market() -> MarketAnalysis:
    roles = [
        CustomerRoleAssessment(
            role=role,
            **_unknown_finding_values(f"{role.value}角色"),
        )
        for role in CustomerRole
    ]
    return MarketAnalysis(
        total_market=MarketTotalAssessment(
            series=[],
            growth_stage=GrowthStage.UNKNOWN,
            stage_rationale="缺少足够的同口径市场数据。",
            **_unknown_finding_values("市场规模与阶段"),
        ),
        customer_structure=CustomerStructureAssessment(
            segmentation_dimensions=["行业", "企业规模"],
            priority_segments=[],
            roles=roles,
            **_unknown_finding_values("客户结构"),
        ),
        procurement_drivers=ProcurementAssessment(
            ranked_drivers=[],
            **_unknown_finding_values("采购驱动"),
        ),
    )


def _unknown_five_forces() -> FiveForcesAnalysis:
    return FiveForcesAnalysis(
        assessments=[
            ForceAssessment(
                force=force,
                pressure_score=None,
                uncertainty="缺少可核验的竞争结构证据。",
                **_unknown_finding_values(f"{force.value}压力"),
            )
            for force in ForceName
        ]
    )


def _analysis_evidence_ids(
    analysis: RequiredStrategyAnalysis,
) -> Iterable[str]:
    for finding in _analysis_findings(analysis):
        yield from finding.evidence_ids
    for series in analysis.market.total_market.series:
        for point in series.points:
            yield point.source_id
    for conclusion in analysis.core_conclusions:
        yield from conclusion.evidence_ids
    for implication in analysis.strategic_implications:
        yield from implication.evidence_ids


def _split_mixed_market_series(data: dict[str, Any]) -> dict[str, Any]:
    """Split market points by comparable region, unit, and statistical scope."""

    normalized = deepcopy(data)
    try:
        total_market = normalized["market"]["total_market"]
        series_items = total_market["series"]
    except (KeyError, TypeError):
        return normalized
    if not isinstance(series_items, list):
        return normalized

    split_series: list[dict[str, Any]] = []
    for series in series_items:
        if not isinstance(series, dict) or not isinstance(series.get("points"), list):
            split_series.append(series)
            continue

        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for point in series["points"]:
            if not isinstance(point, dict):
                groups.setdefault(("", "", ""), []).append(point)
                continue
            key = tuple(
                str(point.get(field, "")).strip()
                for field in ("region", "unit", "statistical_scope")
            )
            groups.setdefault(key, []).append(point)

        for key, points in groups.items():
            item = deepcopy(series)
            item["points"] = sorted(
                points,
                key=lambda point: point.get("year", 0) if isinstance(point, dict) else 0,
            )
            item["cagr"] = None
            if len(groups) > 1:
                scope = "｜".join(value or "未注明" for value in key)
                item["metric_name"] = f"{series.get('metric_name', '市场指标')}（{scope}）"[:500]
            split_series.append(item)

    if len(split_series) > 15:
        unknowns = total_market.get("unknowns")
        if isinstance(unknowns, list) and len(unknowns) < 8:
            unknowns.append(
                f"市场数据包含 {len(split_series)} 个不同统计口径，仅保留前 15 个。"
            )
        split_series = split_series[:15]
    total_market["series"] = split_series
    return normalized
