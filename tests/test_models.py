import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models import (
    ContentOrigin,
    ModuleDecision,
    ModuleName,
    ResearchReport,
    ResearchRequest,
    RunMode,
    SourceRecord,
    SourceTier,
    WorkflowRun,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "sample"


def test_request_normalizes_text_and_blank_company() -> None:
    request = ResearchRequest(
        industry="  企业软件  ",
        region=" 中国 ",
        start_year=2024,
        end_year=2024,
        target_company="   ",
        strategy_question="  企业应优先服务哪些客户群体？  ",
    )

    assert request.industry == "企业软件"
    assert request.region == "中国"
    assert request.target_company is None
    assert request.mode is RunMode.SAMPLE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("industry", ""),
        ("region", ""),
        ("strategy_question", "太短"),
    ],
)
def test_request_rejects_empty_or_short_text(field: str, value: str) -> None:
    data = {
        "industry": "企业软件",
        "region": "中国",
        "start_year": 2024,
        "end_year": 2026,
        "strategy_question": "企业应优先服务哪些客户群体？",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        ResearchRequest(**data)


def test_request_rejects_reversed_years() -> None:
    with pytest.raises(ValidationError, match="start_year"):
        ResearchRequest(
            industry="企业软件",
            region="中国",
            start_year=2027,
            end_year=2026,
            strategy_question="企业应优先服务哪些客户群体？",
        )


def test_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ResearchRequest(
            industry="企业软件",
            region="中国",
            start_year=2024,
            end_year=2026,
            strategy_question="企业应优先服务哪些客户群体？",
            unexpected=True,
        )


def test_search_snippet_cannot_support_key_fact() -> None:
    source = SourceRecord(
        source_id="S01",
        title="搜索结果",
        publisher="搜索引擎",
        url="https://example.com/result",
        tier=SourceTier.LEAD,
        origin=ContentOrigin.SEARCH_SNIPPET,
        excerpt="搜索摘要。",
    )

    assert source.supports_key_fact is False


def test_module_decision_rejects_duplicate_source_ids() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        ModuleDecision(
            module=ModuleName.PEST,
            enabled=True,
            reason="测试。",
            supporting_source_ids=["S01", "S01"],
        )


def test_report_round_trip(research_report: ResearchReport) -> None:
    payload = research_report.model_dump_json()
    restored = ResearchReport.model_validate_json(payload)

    assert restored == research_report
    assert restored.enabled_modules == [ModuleName.PEST]
    assert restored.skipped_modules == []


def test_report_rejects_unknown_source_reference(research_report: ResearchReport) -> None:
    data = research_report.model_dump(mode="json")
    data["sections"][0]["evidence_ids"] = ["S99"]

    with pytest.raises(ValidationError, match="unknown source ids"):
        ResearchReport.model_validate(data)


def test_offline_json_fixtures_are_valid() -> None:
    request = ResearchRequest.model_validate_json(
        (SAMPLE_DIR / "research_request.json").read_text(encoding="utf-8")
    )
    report = ResearchReport.model_validate_json(
        (SAMPLE_DIR / "research_report.json").read_text(encoding="utf-8")
    )
    run = WorkflowRun.model_validate_json(
        (SAMPLE_DIR / "workflow_run.json").read_text(encoding="utf-8")
    )

    assert report.request == request
    assert run.request == request
    assert json.loads(report.model_dump_json())["schema_version"] == "0.1"
