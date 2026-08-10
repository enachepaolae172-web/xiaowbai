import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.models import (
    ContentOrigin,
    EvidenceFact,
    EvidenceExtraction,
    EvidencePool,
    ModelResponse,
    ResearchRequest,
    RunMode,
    SourceRecord,
    SourceTier,
)
from src.research_model import ModelOutputValidationError
from src.strategy_analysis import RequiredAnalysisService
from src.strategy_models import (
    Confidence,
    ForceName,
    RequiredStrategyAnalysis,
)


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
        mode=RunMode.SAMPLE,
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


def test_offline_required_analysis_fixture_is_valid() -> None:
    analysis = RequiredStrategyAnalysis.model_validate(
        load_json("required_strategy_analysis.json")
    )

    assert len(analysis.pest.assessments) == 4
    assert len(analysis.five_forces.assessments) == 5
    assert len(analysis.market.customer_structure.roles) == 5
    assert analysis.market.total_market.series[0].cagr is None


def test_pest_requires_all_four_dimensions() -> None:
    invalid = load_json("required_strategy_analysis.json")
    invalid["pest"]["assessments"][3]["dimension"] = "political"

    with pytest.raises(ValidationError, match="each dimension"):
        RequiredStrategyAnalysis.model_validate(invalid)


def test_force_score_must_be_between_one_and_five() -> None:
    invalid = load_json("required_strategy_analysis.json")
    invalid["five_forces"]["assessments"][0]["pressure_score"] = 6

    with pytest.raises(ValidationError):
        RequiredStrategyAnalysis.model_validate(invalid)


def test_force_can_remain_unknown_without_forced_score() -> None:
    data = load_json("required_strategy_analysis.json")
    force = data["five_forces"]["assessments"][0]
    force["pressure_score"] = None
    force["facts"] = []
    force["evidence_ids"] = []
    force["confidence"] = "unknown"
    force["unknowns"] = ["缺少竞争者和份额数据"]

    analysis = RequiredStrategyAnalysis.model_validate(data)
    rivalry = next(
        item
        for item in analysis.five_forces.assessments
        if item.force is ForceName.RIVALRY
    )

    assert rivalry.pressure_score is None
    assert rivalry.confidence is Confidence.UNKNOWN


def test_scored_force_cannot_use_unknown_confidence() -> None:
    invalid = load_json("required_strategy_analysis.json")
    invalid["five_forces"]["assessments"][0]["confidence"] = "unknown"

    with pytest.raises(ValidationError, match="stated confidence"):
        RequiredStrategyAnalysis.model_validate(invalid)


def test_unsupported_pest_cannot_claim_opportunity() -> None:
    invalid = load_json("required_strategy_analysis.json")
    pest = invalid["pest"]["assessments"][0]
    pest["facts"] = []
    pest["evidence_ids"] = []
    pest["confidence"] = "unknown"
    pest["unknowns"] = ["缺少政策正文"]
    pest["impact"] = "opportunity"

    with pytest.raises(ValidationError, match="unknown impact"):
        RequiredStrategyAnalysis.model_validate(invalid)


def test_market_series_rejects_mixed_statistical_scope() -> None:
    invalid = load_json("required_strategy_analysis.json")
    points = invalid["market"]["total_market"]["series"][0]["points"]
    points[1]["statistical_scope"] = "另一统计口径"

    with pytest.raises(ValidationError, match="share region, unit, and scope"):
        RequiredStrategyAnalysis.model_validate(invalid)


def test_service_splits_mixed_market_scope_into_comparable_series() -> None:
    data = load_json("required_strategy_analysis.json")
    points = data["market"]["total_market"]["series"][0]["points"]
    points[1]["region"] = "全球"
    points[1]["unit"] = "亿美元"
    points[1]["statistical_scope"] = "全球企业级 AI Agent 收入"
    client = FakeModelClient(data)
    service = RequiredAnalysisService(client)

    analysis = service.analyze(request(), pool(), extraction())

    series = analysis.market.total_market.series
    assert len(series) == 2
    assert all(len(item.points) == 1 for item in series)
    assert all(item.cagr is None for item in series)
    assert len(client.calls) == 1


def test_market_series_rejects_zero_start_value() -> None:
    invalid = load_json("required_strategy_analysis.json")
    invalid["market"]["total_market"]["series"][0]["points"][0]["value"] = 0

    with pytest.raises(ValidationError, match="start value must be positive"):
        RequiredStrategyAnalysis.model_validate(invalid)


def test_single_point_market_series_is_kept_without_cagr() -> None:
    data = load_json("required_strategy_analysis.json")
    data["market"]["total_market"]["series"][0]["points"] = data["market"][
        "total_market"
    ]["series"][0]["points"][:1]
    service = RequiredAnalysisService(FakeModelClient(data))

    analysis = service.analyze(request(), pool(), extraction())

    series = analysis.market.total_market.series[0]
    assert len(series.points) == 1
    assert series.cagr is None
    assert any("单期数据" in item for item in analysis.market.total_market.unknowns)


def test_service_calculates_cagr_and_sends_schema() -> None:
    client = FakeModelClient(load_json("required_strategy_analysis.json"))
    service = RequiredAnalysisService(client)

    analysis = service.analyze(request(), pool(), extraction())

    growth = analysis.market.total_market.series[0].cagr
    assert growth is not None
    assert growth.cagr_percent == pytest.approx(20.0)
    assert client.calls[0][0] == "required_strategy_analysis"
    assert "response_schema" in client.calls[0][1]
    assert "sources" not in client.calls[0][1]
    assert all(
        "excerpt" not in source
        for source in client.calls[0][1]["source_registry"]
    )
    assert analysis.pest.assessments[0].facts
    assert analysis.pest.assessments[0].judgment
    assert analysis.pest.assessments[0].recommendations


def test_service_rejects_search_snippet_as_support() -> None:
    service = RequiredAnalysisService(
        FakeModelClient(load_json("required_strategy_analysis.json"))
    )

    with pytest.raises(ModelOutputValidationError, match="搜索摘要"):
        service.analyze(
            request(),
            pool(second_origin=ContentOrigin.SEARCH_SNIPPET),
            extraction(),
        )


def test_service_rejects_fact_extracted_from_search_snippet() -> None:
    service = RequiredAnalysisService(
        FakeModelClient(load_json("required_strategy_analysis.json"))
    )
    invalid_extraction = extraction().model_copy(deep=True)
    invalid_extraction.items[1].facts = [
        EvidenceFact(statement="未经正文核验的事实", confidence="high")
    ]

    with pytest.raises(ModelOutputValidationError, match="不能包含抽取事实"):
        service.analyze(
            request(),
            pool(second_origin=ContentOrigin.SEARCH_SNIPPET),
            invalid_extraction,
        )


def test_service_filters_market_year_outside_request_period() -> None:
    data = load_json("required_strategy_analysis.json")
    data["market"]["total_market"]["series"][0]["points"][1]["year"] = 2027
    service = RequiredAnalysisService(FakeModelClient(data))

    analysis = service.analyze(request(), pool(), extraction())

    series = analysis.market.total_market.series[0]
    assert [point.year for point in series.points] == [2024]
    assert series.cagr is None
    assert any("2027" in item for item in analysis.market.total_market.unknowns)


def test_service_rejects_unknown_source_reference() -> None:
    invalid = load_json("required_strategy_analysis.json")
    invalid["strategic_implications"][0]["evidence_ids"] = ["S99"]
    service = RequiredAnalysisService(FakeModelClient(invalid))

    with pytest.raises(ModelOutputValidationError, match="未知来源"):
        service.analyze(request(), pool(), extraction())


def test_service_rejects_incomplete_extraction_before_model_call() -> None:
    client = FakeModelClient(load_json("required_strategy_analysis.json"))
    service = RequiredAnalysisService(client)
    incomplete = EvidenceExtraction(items=extraction().items[:1])

    with pytest.raises(ModelOutputValidationError, match="编号不一致"):
        service.analyze(request(), pool(), incomplete)

    assert not client.calls


def test_service_wraps_invalid_model_structure() -> None:
    invalid = load_json("required_strategy_analysis.json")
    invalid["five_forces"]["assessments"] = invalid["five_forces"]["assessments"][:4]
    service = RequiredAnalysisService(FakeModelClient(invalid))

    with pytest.raises(ModelOutputValidationError, match="结构约束"):
        service.analyze(request(), pool(), extraction())
