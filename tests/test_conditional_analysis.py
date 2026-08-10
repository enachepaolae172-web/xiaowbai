import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.conditional_analysis import ConditionalAnalysisService
from src.conditional_models import ConditionalAnalysisDraft
from src.models import (
    ContentOrigin,
    EvidenceExtraction,
    EvidencePool,
    ModelResponse,
    ModuleName,
    ResearchRequest,
    SourceRecord,
    SourceTier,
)
from src.research_model import ModelOutputValidationError
from src.strategy_models import RequiredStrategyAnalysis


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))


def request() -> ResearchRequest:
    return ResearchRequest(
        industry="企业级 AI Agent",
        region="中国",
        start_year=2024,
        end_year=2026,
        target_company="火山引擎",
        strategy_question="火山引擎应优先服务哪些客户群，并形成怎样的差异化？",
    )


def pool(*, second_origin: ContentOrigin = ContentOrigin.FULL_TEXT) -> EvidencePool:
    return EvidencePool(
        sources=[
            SourceRecord(
                source_id="S01",
                title="官方来源",
                publisher="官方机构",
                url="https://www.volcengine.com/official",
                tier=SourceTier.PRIMARY,
                origin=ContentOrigin.FULL_TEXT,
                excerpt="正式来源正文一",
            ),
            SourceRecord(
                source_id="S02",
                title="专业来源",
                publisher="研究机构",
                url="https://www.caict.ac.cn/report",
                tier=SourceTier.PROFESSIONAL,
                origin=second_origin,
                excerpt="正式来源正文二或搜索摘要",
            ),
        ],
        minimum_key_fact_sources=1,
    )


def extraction() -> EvidenceExtraction:
    return EvidenceExtraction.model_validate(
        load_json("model_evidence_extraction.json")
    )


def required() -> RequiredStrategyAnalysis:
    return RequiredStrategyAnalysis.model_validate(
        load_json("required_strategy_analysis.json")
    )


class FakeModelClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate_json(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> ModelResponse:
        self.calls.append((task, payload))
        return ModelResponse(data=self.response, model="fake")


def test_offline_conditional_fixture_is_valid() -> None:
    draft = ConditionalAnalysisDraft.model_validate(
        load_json("conditional_analysis.json")
    )

    assert len(draft.modules) == 5
    assert [item.milestone_day for item in draft.action_plan.validation_actions] == [
        30,
        60,
        90,
    ]


def test_draft_requires_every_extension_module() -> None:
    invalid = load_json("conditional_analysis.json")
    invalid["modules"] = invalid["modules"][:4]

    with pytest.raises(ValidationError):
        ConditionalAnalysisDraft.model_validate(invalid)


def test_action_plan_requires_30_60_90_day_milestones() -> None:
    invalid = load_json("conditional_analysis.json")
    invalid["action_plan"]["validation_actions"][2]["milestone_day"] = 80

    with pytest.raises(ValidationError, match="30, 60, and 90"):
        ConditionalAnalysisDraft.model_validate(invalid)


def test_service_enables_only_evidence_qualified_modules() -> None:
    client = FakeModelClient(load_json("conditional_analysis.json"))
    service = ConditionalAnalysisService(client)

    bundle = service.analyze(request(), pool(), extraction(), required())

    assert bundle.enabled_modules == [ModuleName.VALUE_CHAIN, ModuleName.LIFECYCLE]
    assert set(bundle.skipped_modules) == {
        ModuleName.CONCENTRATION,
        ModuleName.KEY_SUCCESS_FACTORS,
        ModuleName.INNOVATION_PRICE_SHARE,
    }
    assert all(
        decision.analysis is not None
        for decision in bundle.decisions
        if decision.enabled
    )
    assert all(
        decision.analysis is None
        for decision in bundle.decisions
        if not decision.enabled
    )
    assert client.calls[0][0] == "conditional_modules_and_action_plan"
    assert "response_schema" in client.calls[0][1]
    assert "sources" not in client.calls[0][1]
    assert all(
        "excerpt" not in source
        for source in client.calls[0][1]["source_registry"]
    )


def test_ineligible_model_output_is_discarded() -> None:
    data = load_json("conditional_analysis.json")
    concentration = data["modules"][0]
    concentration["analysis"] = {
        **data["modules"][1]["analysis"],
        "module": "concentration",
        "evidence_ids": ["S02"],
    }
    service = ConditionalAnalysisService(FakeModelClient(data))

    bundle = service.analyze(request(), pool(), extraction(), required())
    decision = next(
        item for item in bundle.decisions if item.module is ModuleName.CONCENTRATION
    )

    assert not decision.enabled
    assert decision.analysis is None
    assert "两个时期" in decision.reason


def test_eligible_module_without_analysis_is_safely_skipped() -> None:
    data = load_json("conditional_analysis.json")
    data["modules"][1]["analysis"] = None
    service = ConditionalAnalysisService(FakeModelClient(data))

    bundle = service.analyze(request(), pool(), extraction(), required())
    decision = next(
        item for item in bundle.decisions if item.module is ModuleName.VALUE_CHAIN
    )

    assert not decision.enabled
    assert "未返回可用分析" in decision.reason


def test_enabled_analysis_must_use_profile_sources() -> None:
    data = load_json("conditional_analysis.json")
    data["modules"][1]["profile"]["evidence_ids"] = ["S01"]
    service = ConditionalAnalysisService(FakeModelClient(data))

    with pytest.raises(ModelOutputValidationError, match="画像之外"):
        service.analyze(request(), pool(), extraction(), required())


def test_unknown_source_reference_is_rejected() -> None:
    data = load_json("conditional_analysis.json")
    data["action_plan"]["target_customers"][0]["evidence_ids"] = ["S99"]
    service = ConditionalAnalysisService(FakeModelClient(data))

    with pytest.raises(ModelOutputValidationError, match="未知来源"):
        service.analyze(request(), pool(), extraction(), required())


def test_search_snippet_cannot_support_action_plan() -> None:
    service = ConditionalAnalysisService(
        FakeModelClient(load_json("conditional_analysis.json"))
    )

    with pytest.raises(ModelOutputValidationError, match="行动方案"):
        service.analyze(
            request(),
            pool(second_origin=ContentOrigin.SEARCH_SNIPPET),
            extraction(),
            required(),
        )


def test_extraction_must_match_evidence_pool() -> None:
    incomplete = EvidenceExtraction(items=extraction().items[:1])
    service = ConditionalAnalysisService(
        FakeModelClient(load_json("conditional_analysis.json"))
    )

    with pytest.raises(ModelOutputValidationError, match="来源编号不一致"):
        service.analyze(request(), pool(), incomplete, required())


def test_search_snippet_cannot_be_extracted_as_fact() -> None:
    data = load_json("model_evidence_extraction.json")
    data["items"][1]["facts"] = data["items"][0]["facts"]
    invalid_extraction = EvidenceExtraction.model_validate(data)
    service = ConditionalAnalysisService(
        FakeModelClient(load_json("conditional_analysis.json"))
    )

    with pytest.raises(ModelOutputValidationError, match="不能抽取为事实"):
        service.analyze(
            request(),
            pool(second_origin=ContentOrigin.SEARCH_SNIPPET),
            invalid_extraction,
            required(),
        )
