"""End-to-end research orchestration for sample and real-time runs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.conditional_analysis import ConditionalAnalysisService
from src.conditional_models import ConditionalAnalysisBundle
from src.evidence import EvidencePoolBuilder
from src.model_client import DoubaoError
from src.models import (
    EvidenceExtraction,
    EvidencePool,
    ModelResponse,
    ResearchPlan,
    ResearchRequest,
)
from src.ports import ModelClient, SearchClient
from src.reporting import (
    MarkdownReportRenderer,
    ReportArtifact,
    audit_citations,
    report_character_count,
)
from src.research_model import (
    ModelOutputValidationError,
    ResearchModelService,
    fallback_evidence_extraction,
    fallback_research_plan,
)
from src.strategy_analysis import RequiredAnalysisService
from src.strategy_models import RequiredStrategyAnalysis


ProgressCallback = Callable[[str, str], None]


class PipelineError(RuntimeError):
    """Base error safe for the product layer to display."""


class InsufficientEvidenceError(PipelineError):
    """Raised when no extracted source can support key facts."""


class CitationVerificationError(PipelineError):
    """Raised when the generated report fails citation checks."""


@dataclass(frozen=True)
class ResearchRunResult:
    request: ResearchRequest
    plan: ResearchPlan
    pool: EvidencePool
    extraction: EvidenceExtraction
    required: RequiredStrategyAnalysis
    conditional: ConditionalAnalysisBundle
    artifact: ReportArtifact
    model_calls: int = 0
    model_tokens: int = 0
    search_queries: int = 0


class ResearchPipeline:
    """Run the fixed research workflow without a framework dependency."""

    def __init__(
        self,
        model_client: ModelClient,
        search_client: SearchClient,
        *,
        evidence_builder: EvidencePoolBuilder | None = None,
        renderer: MarkdownReportRenderer | None = None,
    ) -> None:
        self.model_client = model_client
        self.search_client = search_client
        self.evidence_builder = evidence_builder or EvidencePoolBuilder()
        self.renderer = renderer or MarkdownReportRenderer()

    def run(
        self,
        request: ResearchRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> ResearchRunResult:
        _notify(progress, "validating", "研究参数校验完成")
        model_service = ResearchModelService(self.model_client)

        _notify(progress, "planning", "正在拆解战略问题并生成搜索词")
        try:
            plan = model_service.create_research_plan(request)
        except (DoubaoError, ModelOutputValidationError) as exc:
            _notify(
                progress,
                "planning_fallback",
                "模型规划格式异常，正在使用预设战略问题树",
            )
            plan = fallback_research_plan(request)

        _notify(progress, "searching", "正在搜索并提取公开资料原文")
        search_results = self.search_client.search(plan.search_queries)
        urls = [
            str(item.get("url", ""))
            for item in search_results
            if isinstance(item, Mapping)
        ]
        extracted_results = self.search_client.extract(urls)

        _notify(progress, "building_evidence", "正在去重、分级并建立证据池")
        pool = self.evidence_builder.build(search_results, extracted_results)
        if not pool.sources:
            raise InsufficientEvidenceError("证据不足：搜索结果中没有可用来源。")
        if not pool.key_fact_sources:
            raise InsufficientEvidenceError(
                "证据不足：未提取到可支撑关键事实的网页正文，请调整问题后重试。"
            )
        try:
            extraction = model_service.extract_evidence(pool)
        except (DoubaoError, ModelOutputValidationError) as exc:
            _notify(
                progress,
                "evidence_fallback",
                "证据抽取格式异常，正在保留网页原文并继续分析",
            )
            extraction = fallback_evidence_extraction(pool)

        _notify(progress, "analyzing", "正在运行 PEST、市场、五力和条件模块")
        required = RequiredAnalysisService(self.model_client).analyze(
            request,
            pool,
            extraction,
        )
        conditional_service = ConditionalAnalysisService(self.model_client)
        try:
            conditional = conditional_service.analyze(
                request,
                pool,
                extraction,
                required,
            )
        except (DoubaoError, ModelOutputValidationError) as exc:
            _notify(
                progress,
                "analyzing_fallback",
                "扩展模块未完成，正在保留基础报告并生成 90 天验证计划",
            )
            conditional = conditional_service.fallback(required, reason=str(exc))

        _notify(progress, "verifying", "正在核验引用并生成 Markdown 报告")
        artifact = self.renderer.render(request, pool, required, conditional)
        if not artifact.audit.is_valid:
            raise CitationVerificationError(
                "报告引用核验未通过，已停止输出，请重新运行研究。"
            )

        _notify(progress, "completed", "研究报告已完成")
        diagnostics = getattr(self.model_client, "diagnostics", None)
        return ResearchRunResult(
            request=request,
            plan=plan,
            pool=pool,
            extraction=extraction,
            required=required,
            conditional=conditional,
            artifact=artifact,
            model_calls=max(int(getattr(diagnostics, "api_calls", 0) or 0), 0),
            model_tokens=max(
                int(getattr(diagnostics, "input_tokens", 0) or 0)
                + int(getattr(diagnostics, "output_tokens", 0) or 0),
                0,
            ),
            search_queries=len(plan.search_queries),
        )


class SampleResearchRepository:
    """Load the pre-generated Volcengine case without external calls."""

    def __init__(self, sample_dir: Path | None = None) -> None:
        self.sample_dir = sample_dir or (
            Path(__file__).resolve().parents[1] / "data" / "sample"
        )

    def load(self) -> ResearchRunResult:
        request, plan, pool, extraction, required, conditional = (
            self._load_components()
        )
        markdown = (self.sample_dir / "strategy_report.md").read_text(
            encoding="utf-8"
        )
        artifact = ReportArtifact(
            markdown=markdown,
            audit=audit_citations(markdown, pool),
            character_count=report_character_count(markdown),
        )
        if not artifact.audit.is_valid:
            raise CitationVerificationError("预生成样例报告的引用核验未通过。")
        return ResearchRunResult(
            request=request,
            plan=plan,
            pool=pool,
            extraction=extraction,
            required=required,
            conditional=conditional,
            artifact=artifact,
            search_queries=len(plan.search_queries),
        )

    def render_current(self) -> ReportArtifact:
        """Render the structured fixture for maintainers updating the sample."""
        request, _, pool, _, required, conditional = self._load_components()
        return MarkdownReportRenderer().render(
            request,
            pool,
            required,
            conditional,
        )

    def _load_components(
        self,
    ) -> tuple[
        ResearchRequest,
        ResearchPlan,
        EvidencePool,
        EvidenceExtraction,
        RequiredStrategyAnalysis,
        ConditionalAnalysisBundle,
    ]:
        request = ResearchRequest.model_validate(self._json("research_request.json"))
        plan = ResearchPlan.model_validate(self._json("model_research_plan.json"))
        extraction = EvidenceExtraction.model_validate(
            self._json("model_evidence_extraction.json")
        )
        required = RequiredStrategyAnalysis.model_validate(
            self._json("required_strategy_analysis.json")
        )

        search_results = self._json("search_results.json")
        extracted_results = self._json("extract_results.json")
        complete_pool = EvidencePoolBuilder(minimum_key_fact_sources=1).build(
            search_results,
            extracted_results,
        )
        extraction_ids = {item.source_id for item in extraction.items}
        sources = [
            source for source in complete_pool.sources if source.source_id in extraction_ids
        ]
        pool = EvidencePool(
            sources=sources,
            search_result_count=complete_pool.search_result_count,
            extraction_success_count=complete_pool.extraction_success_count,
            minimum_key_fact_sources=1,
        )

        conditional_client = _StaticModelClient(
            self._json("conditional_analysis.json")
        )
        conditional = ConditionalAnalysisService(conditional_client).analyze(
            request,
            pool,
            extraction,
            required,
        )
        return (
            request,
            plan,
            pool,
            extraction,
            required,
            conditional,
        )

    def _json(self, name: str) -> Any:
        return json.loads((self.sample_dir / name).read_text(encoding="utf-8"))


class _StaticModelClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def generate_json(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> ModelResponse:
        if task != "conditional_modules_and_action_plan":
            raise ValueError(f"unexpected sample task: {task}")
        return ModelResponse(data=self.response, model="sample")


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
) -> None:
    if callback is not None:
        callback(stage, message)
