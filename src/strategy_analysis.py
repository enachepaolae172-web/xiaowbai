"""Mandatory PEST, market, customer, procurement, and five-forces analysis."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from src.metrics import compute_market_series_growth
from src.models import ContentOrigin, EvidenceExtraction, EvidencePool, ResearchRequest
from src.ports import ModelClient
from src.research_model import ModelOutputValidationError
from src.strategy_models import (
    EvidenceBackedFinding,
    RequiredStrategyAnalysis,
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

        response = self.client.generate_json(
            task="required_strategy_analysis",
            payload={
                "request": request.model_dump(mode="json"),
                "sources": [source.model_dump(mode="json") for source in pool.sources],
                "extracted_evidence": extraction.model_dump(mode="json"),
                "response_schema": RequiredStrategyAnalysis.model_json_schema(),
            },
        )
        analysis = self._validate_response(response.data)
        self._validate_market_period(request, analysis)
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
    def _validate_market_period(
        request: ResearchRequest,
        analysis: RequiredStrategyAnalysis,
    ) -> None:
        out_of_range = sorted(
            {
                point.year
                for series in analysis.market.total_market.series
                for point in series.points
                if not request.start_year <= point.year <= request.end_year
            }
        )
        if out_of_range:
            years = ", ".join(str(year) for year in out_of_range)
            raise ModelOutputValidationError(
                f"市场数据年份超出研究期间：{years}。"
            )

    @staticmethod
    def _validate_response(data: dict) -> RequiredStrategyAnalysis:
        try:
            return RequiredStrategyAnalysis.model_validate(data)
        except ValidationError as exc:
            summaries = []
            for error in exc.errors(include_input=False)[:8]:
                location = ".".join(str(part) for part in error["loc"])
                summaries.append(f"{location}: {error['msg']}")
            raise ModelOutputValidationError(
                "必选战略分析不符合结构约束：" + "; ".join(summaries)
            ) from exc

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
