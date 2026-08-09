import json
from pathlib import Path
from typing import Any

from src.conditional_analysis import ConditionalAnalysisService
from src.models import (
    ContentOrigin,
    EvidenceExtraction,
    EvidencePool,
    ModelResponse,
    ResearchRequest,
    SourceRecord,
    SourceTier,
)
from src.reporting import MarkdownReportRenderer, audit_citations
from src.strategy_analysis import RequiredAnalysisService


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))


class FakeModelClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    def generate_json(self, *, task: str, payload: dict[str, Any]) -> ModelResponse:
        return ModelResponse(data=self.responses[task], model="fake")


def request() -> ResearchRequest:
    return ResearchRequest(
        industry="企业级 AI Agent",
        region="中国",
        start_year=2024,
        end_year=2026,
        target_company="火山引擎",
        strategy_question="火山引擎应优先服务哪些客户群，并形成怎样的差异化？",
    )


def pool() -> EvidencePool:
    return EvidencePool(
        sources=[
            SourceRecord(
                source_id="S01",
                title="官方产品资料",
                publisher="火山引擎",
                url="https://www.volcengine.com/official",
                tier=SourceTier.PRIMARY,
                origin=ContentOrigin.FULL_TEXT,
                excerpt="正式来源正文一",
            ),
            SourceRecord(
                source_id="S02",
                title="行业研究资料",
                publisher="研究机构",
                url="https://www.caict.ac.cn/report",
                tier=SourceTier.PROFESSIONAL,
                origin=ContentOrigin.FULL_TEXT,
                excerpt="正式来源正文二",
            ),
        ],
        minimum_key_fact_sources=1,
    )


def build_report():
    sources = pool()
    extraction = EvidenceExtraction.model_validate(
        load_json("model_evidence_extraction.json")
    )
    client = FakeModelClient(
        {
            "required_strategy_analysis": load_json(
                "required_strategy_analysis.json"
            ),
            "conditional_modules_and_action_plan": load_json(
                "conditional_analysis.json"
            ),
        }
    )
    required = RequiredAnalysisService(client).analyze(
        request(),
        sources,
        extraction,
    )
    conditional = ConditionalAnalysisService(client).analyze(
        request(),
        sources,
        extraction,
        required,
    )
    return MarkdownReportRenderer().render(
        request(),
        sources,
        required,
        conditional,
    )


def test_report_has_valid_citations_and_required_sections() -> None:
    artifact = build_report()

    assert artifact.audit.is_valid
    assert not artifact.audit.unknown_source_ids
    assert "## 2. 宏观环境分析（PEST）" in artifact.markdown
    assert "## 4. 行业结构（波特五力）" in artifact.markdown
    assert "## 6. 战略行动方案" in artifact.markdown
    assert "第 90 天" in artifact.markdown
    assert "分析建议：" in artifact.markdown


def test_report_renders_only_enabled_extension_sections() -> None:
    markdown = build_report().markdown

    assert "### 5.1 价值链" in markdown
    assert "### 5.2 产品生命周期" in markdown
    assert "### 5.1 行业集中度" not in markdown
    assert "### 5.3 关键成功要素" not in markdown


def test_report_meets_target_length() -> None:
    artifact = build_report()

    assert artifact.length_target_met, artifact.character_count


def test_markdown_can_be_downloaded_and_reopened_as_utf8(tmp_path: Path) -> None:
    artifact = build_report()
    output = tmp_path / "strategy-report.md"

    output.write_text(artifact.markdown, encoding="utf-8")

    assert output.read_text(encoding="utf-8") == artifact.markdown
    assert "企业战略研究报告" in output.read_text(encoding="utf-8")


def test_citation_audit_reports_unknown_and_uncited_claims() -> None:
    markdown = "事实：该结论没有引用。\n判断：另一结论 [S99]\n"

    audit = audit_citations(markdown, pool())

    assert audit.unknown_source_ids == ["S99"]
    assert "事实：该结论没有引用。" in audit.uncited_fact_lines
    assert not audit.is_valid
