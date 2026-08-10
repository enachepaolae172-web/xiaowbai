"""Pydantic-validated model tasks for research planning and evidence extraction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
