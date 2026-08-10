"""Pydantic-validated model tasks for research planning and evidence extraction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.models import (
    Confidence,
    ContentOrigin,
    EvidenceFact,
    EvidenceExtraction,
    EvidencePool,
    ResearchArea,
    ResearchPlan,
    ResearchRequest,
    ResearchSubQuestion,
    SourceEvidence,
)
from src.ports import ModelClient


class ModelOutputValidationError(RuntimeError):
    """Raised when JSON is valid but violates the task contract."""


ModelT = TypeVar("ModelT", bound=BaseModel)


class ResearchModelService:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def create_research_plan(self, request: ResearchRequest) -> ResearchPlan:
        return generate_validated_model(
            client=self.client,
            task="research_plan",
            payload={
                "request": request.model_dump(mode="json"),
            },
            model_type=ResearchPlan,
            error_label="研究计划",
        )

    def extract_evidence(self, pool: EvidencePool) -> EvidenceExtraction:
        if not pool.sources:
            raise ValueError("evidence pool must contain at least one source")

        extraction = generate_validated_model(
            client=self.client,
            task="evidence_extraction",
            payload={
                "sources": [
                    source.model_dump(mode="json")
                    for source in pool.sources
                ],
            },
            model_type=EvidenceExtraction,
            error_label="证据抽取",
        )
        self._validate_extraction_against_pool(pool, extraction)
        return extraction

    @staticmethod
    def _validate_extraction_against_pool(
        pool: EvidencePool,
        extraction: EvidenceExtraction,
    ) -> None:
        sources_by_id = {source.source_id: source for source in pool.sources}
        returned_ids = {item.source_id for item in extraction.items}
        expected_ids = set(sources_by_id)
        if returned_ids != expected_ids:
            missing = sorted(expected_ids - returned_ids)
            unknown = sorted(returned_ids - expected_ids)
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown: {', '.join(unknown)}")
            raise ModelOutputValidationError(
                "证据抽取来源编号不完整（" + "; ".join(details) + "）。"
            )

        for item in extraction.items:
            source = sources_by_id[item.source_id]
            if source.origin is ContentOrigin.SEARCH_SNIPPET and item.facts:
                raise ModelOutputValidationError(
                    f"{item.source_id} 只有搜索摘要，不能输出关键事实。"
                )


def fallback_research_plan(request: ResearchRequest) -> ResearchPlan:
    """Build a bounded deterministic plan when model planning is unavailable."""

    subject = request.target_company or request.industry
    queries = [
        f"{subject} {request.industry} 官方 产品 客户",
        f"{request.region} {request.industry} 市场规模 增长",
        f"{request.region} {request.industry} 竞争格局",
        f"{request.region} {request.industry} 政策 监管",
    ]
    questions = [
        ResearchSubQuestion(
            area=ResearchArea.BUSINESS,
            question=f"{subject}的核心业务、客户与差异化能力是什么？",
            rationale="确认业务边界和客户价值，避免研究口径混淆。",
            priority=5,
            search_queries=[queries[0]],
        ),
        ResearchSubQuestion(
            area=ResearchArea.MARKET,
            question=f"{request.region}{request.industry}市场规模与增长阶段如何？",
            rationale="市场容量、增速和阶段决定战略优先级。",
            priority=5,
            search_queries=[queries[1]],
        ),
        ResearchSubQuestion(
            area=ResearchArea.INDUSTRY,
            question=f"{request.industry}的竞争结构和主要替代方案是什么？",
            rationale="识别竞争压力、进入壁垒和差异化空间。",
            priority=4,
            search_queries=[queries[2]],
        ),
        ResearchSubQuestion(
            area=ResearchArea.RISK,
            question=f"影响{request.industry}的政策、合规与宏观风险是什么？",
            rationale="补充 PEST 和战略风险判断所需证据。",
            priority=4,
            search_queries=[queries[3]],
        ),
    ]
    return ResearchPlan(
        questions=questions,
        search_queries=queries,
        unknowns=["模型规划不可用，已采用程序预设问题树。"],
    )


def fallback_evidence_extraction(pool: EvidencePool) -> EvidenceExtraction:
    """Preserve traceability by turning extracted page text into low-confidence facts."""

    items: list[SourceEvidence] = []
    for source in pool.sources:
        excerpt = " ".join(source.excerpt.split())[:900]
        if source.origin is ContentOrigin.SEARCH_SNIPPET:
            items.append(
                SourceEvidence(
                    source_id=source.source_id,
                    facts=[],
                    explanatory_context=[excerpt],
                    unknowns=["仅有搜索摘要，不能作为关键事实。"],
                )
            )
            continue

        items.append(
            SourceEvidence(
                source_id=source.source_id,
                facts=[
                    EvidenceFact(
                        statement=f"原文摘录：{excerpt}",
                        confidence=Confidence.LOW,
                        time_scope=source.time_scope,
                        region_scope=source.region_scope,
                        unit=source.unit,
                        statistical_scope=source.statistical_scope,
                    )
                ],
                explanatory_context=[],
                unknowns=["该事实由程序保留原文摘录，尚未经过模型归纳。"],
            )
        )
    return EvidenceExtraction(items=items)


def generate_validated_model(
    *,
    client: ModelClient,
    task: str,
    payload: Mapping[str, Any],
    model_type: type[ModelT],
    error_label: str,
    normalizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> ModelT:
    """Generate a model contract and make one bounded schema-only repair attempt."""

    schema = model_type.model_json_schema()
    response = client.generate_json(
        task=task,
        payload={**dict(payload), "response_schema": schema},
    )
    normalized = normalizer(response.data) if normalizer else response.data
    try:
        return _validate(model_type, normalized, error_label=error_label)
    except ModelOutputValidationError as first_error:
        repaired = client.generate_json(
            task=task,
            payload={
                "repair_instruction": (
                    "Correct only the JSON structure. Preserve supported facts, source IDs, "
                    "numbers, and uncertainty exactly; do not add new claims."
                ),
                "invalid_response": normalized,
                "validation_errors": str(first_error),
                "response_schema": schema,
            },
        )
        normalized_repair = normalizer(repaired.data) if normalizer else repaired.data
        try:
            return _validate(model_type, normalized_repair, error_label=error_label)
        except ModelOutputValidationError as repaired_error:
            raise ModelOutputValidationError(
                f"{error_label}结构自动纠错失败：{repaired_error}"
            ) from repaired_error


def compact_source_registry(pool: EvidencePool) -> list[dict[str, Any]]:
    """Return source metadata for downstream analysis without resending excerpts."""

    return [
        source.model_dump(
            mode="json",
            exclude={"excerpt", "used_in"},
        )
        for source in pool.sources
    ]


def _validate(
    model_type: type[ModelT],
    data: dict[str, Any],
    *,
    error_label: str = "豆包 JSON",
) -> ModelT:
    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        summaries = []
        for error in exc.errors(include_input=False)[:5]:
            location = ".".join(str(part) for part in error["loc"])
            summaries.append(f"{location}: {error['msg']}")
        raise ModelOutputValidationError(
            f"{error_label}不符合结构约束：" + "; ".join(summaries)
        ) from exc
