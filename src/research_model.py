"""Pydantic-validated model tasks for research planning and evidence extraction."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.models import (
    ContentOrigin,
    EvidenceExtraction,
    EvidencePool,
    ResearchPlan,
    ResearchRequest,
)
from src.ports import ModelClient


class ModelOutputValidationError(RuntimeError):
    """Raised when JSON is valid but violates the task contract."""


ModelT = TypeVar("ModelT", bound=BaseModel)


class ResearchModelService:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def create_research_plan(self, request: ResearchRequest) -> ResearchPlan:
        response = self.client.generate_json(
            task="research_plan",
            payload={
                "request": request.model_dump(mode="json"),
                "response_schema": ResearchPlan.model_json_schema(),
            },
        )
        return _validate(ResearchPlan, response.data)

    def extract_evidence(self, pool: EvidencePool) -> EvidenceExtraction:
        if not pool.sources:
            raise ValueError("evidence pool must contain at least one source")

        response = self.client.generate_json(
            task="evidence_extraction",
            payload={
                "sources": [
                    source.model_dump(mode="json")
                    for source in pool.sources
                ],
                "response_schema": EvidenceExtraction.model_json_schema(),
            },
        )
        extraction = _validate(EvidenceExtraction, response.data)
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


def _validate(model_type: type[ModelT], data: dict[str, Any]) -> ModelT:
    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        summaries = []
        for error in exc.errors(include_input=False)[:5]:
            location = ".".join(str(part) for part in error["loc"])
            summaries.append(f"{location}: {error['msg']}")
        raise ModelOutputValidationError(
            "豆包 JSON 不符合结构约束：" + "; ".join(summaries)
        ) from exc
