import json
from pathlib import Path
from typing import Any

import pytest

from src.models import (
    ContentOrigin,
    EvidencePool,
    ModelResponse,
    ResearchPlan,
    ResearchRequest,
    RunMode,
    SourceRecord,
    SourceTier,
)
from src.research_model import ModelOutputValidationError, ResearchModelService


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


class FakeModelClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate_json(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> ModelResponse:
        self.calls.append((task, payload))
        return ModelResponse(data=self.responses[task], model="fake")


def request() -> ResearchRequest:
    return ResearchRequest(
        industry="企业级 AI Agent",
        region="中国",
        start_year=2024,
        end_year=2026,
        target_company="火山引擎",
        strategy_question="火山引擎应优先服务哪些客户群，并形成怎样的差异化？",
        mode=RunMode.SAMPLE,
    )


def evidence_pool() -> EvidencePool:
    return EvidencePool(
        sources=[
            SourceRecord(
                source_id="S01",
                title="官方产品页面",
                publisher="火山引擎",
                url="https://www.volcengine.com/product",
                tier=SourceTier.PRIMARY,
                origin=ContentOrigin.FULL_TEXT,
                excerpt="官方正文内容",
            ),
            SourceRecord(
                source_id="S02",
                title="市场线索",
                publisher="example.com",
                url="https://example.com/lead",
                tier=SourceTier.LEAD,
                origin=ContentOrigin.SEARCH_SNIPPET,
                excerpt="尚未打开的搜索摘要",
            ),
        ],
        minimum_key_fact_sources=1,
    )


def load_sample(name: str) -> dict[str, Any]:
    return json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))


def test_create_research_plan_validates_fixture_and_sends_schema() -> None:
    client = FakeModelClient(
        {"research_plan": load_sample("model_research_plan.json")}
    )
    service = ResearchModelService(client)

    plan = service.create_research_plan(request())

    assert isinstance(plan, ResearchPlan)
    assert len(plan.questions) == 2
    assert len(plan.search_queries) == 3
    assert client.calls[0][0] == "research_plan"
    assert "response_schema" in client.calls[0][1]


def test_invalid_plan_is_rejected_with_readable_error() -> None:
    invalid = load_sample("model_research_plan.json")
    invalid["search_queries"] = ["duplicate", "DUPLICATE"]
    service = ResearchModelService(FakeModelClient({"research_plan": invalid}))

    with pytest.raises(ModelOutputValidationError, match="结构约束"):
        service.create_research_plan(request())


def test_overlong_plan_unknown_is_rejected() -> None:
    invalid = load_sample("model_research_plan.json")
    invalid["unknowns"] = ["x" * 501]
    service = ResearchModelService(FakeModelClient({"research_plan": invalid}))

    with pytest.raises(ModelOutputValidationError, match="结构约束"):
        service.create_research_plan(request())


def test_extract_evidence_validates_all_source_ids() -> None:
    client = FakeModelClient(
        {"evidence_extraction": load_sample("model_evidence_extraction.json")}
    )
    service = ResearchModelService(client)

    result = service.extract_evidence(evidence_pool())

    assert [item.source_id for item in result.items] == ["S01", "S02"]
    assert result.items[0].facts
    assert result.items[1].facts == []


def test_search_snippet_cannot_be_promoted_to_fact() -> None:
    invalid = load_sample("model_evidence_extraction.json")
    invalid["items"][1]["facts"] = [
        {"statement": "Unverified market size", "confidence": "high"}
    ]
    service = ResearchModelService(
        FakeModelClient({"evidence_extraction": invalid})
    )

    with pytest.raises(ModelOutputValidationError, match="搜索摘要"):
        service.extract_evidence(evidence_pool())


def test_missing_source_id_is_rejected() -> None:
    invalid = load_sample("model_evidence_extraction.json")
    invalid["items"] = invalid["items"][:1]
    service = ResearchModelService(
        FakeModelClient({"evidence_extraction": invalid})
    )

    with pytest.raises(ModelOutputValidationError, match="missing: S02"):
        service.extract_evidence(evidence_pool())


def test_empty_evidence_pool_is_rejected_before_model_call() -> None:
    client = FakeModelClient({})
    service = ResearchModelService(client)

    with pytest.raises(ValueError, match="at least one source"):
        service.extract_evidence(EvidencePool())

    assert not client.calls
