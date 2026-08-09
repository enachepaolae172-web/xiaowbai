from datetime import date

import pytest

from src.models import (
    AnalysisSection,
    Confidence,
    ContentOrigin,
    ModuleDecision,
    ModuleName,
    ResearchReport,
    ResearchRequest,
    RunMode,
    SourceRecord,
    SourceTier,
)


@pytest.fixture
def research_request() -> ResearchRequest:
    return ResearchRequest(
        industry="企业级 AI Agent",
        region="中国",
        start_year=2024,
        end_year=2026,
        target_company="火山引擎",
        strategy_question="火山引擎应优先服务哪些客户群，并形成怎样的差异化？",
        mode=RunMode.SAMPLE,
    )


@pytest.fixture
def research_report(research_request: ResearchRequest) -> ResearchReport:
    source = SourceRecord(
        source_id="S01",
        title="产品文档",
        publisher="火山引擎",
        published_at=date(2026, 6, 23),
        url="https://www.volcengine.com/docs/example",
        tier=SourceTier.PRIMARY,
        origin=ContentOrigin.FULL_TEXT,
        excerpt="用于测试的原始来源摘录。",
        used_in=["pest"],
    )
    return ResearchReport(
        request=research_request,
        core_conclusions=["测试结论。"],
        module_decisions=[
            ModuleDecision(
                module=ModuleName.PEST,
                enabled=True,
                reason="必选模块。",
                supporting_source_ids=["S01"],
            )
        ],
        sections=[
            AnalysisSection(
                module=ModuleName.PEST,
                title="宏观环境",
                summary="测试章节。",
                evidence_ids=["S01"],
                confidence=Confidence.LOW,
            )
        ],
        sources=[source],
    )
