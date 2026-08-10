import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.model_client import DoubaoTimeoutError
from src.models import ModelResponse, ResearchRequest, RunMode
from src.pipeline import (
    InsufficientEvidenceError,
    ResearchPipeline,
    SampleResearchRepository,
)


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


def load_json(name: str) -> Any:
    return json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))


class FakeModelClient:
    def __init__(self) -> None:
        self.responses = {
            "research_plan": load_json("model_research_plan.json"),
            "evidence_extraction": load_json("model_evidence_extraction.json"),
            "conditional_modules_and_action_plan": load_json(
                "conditional_analysis.json"
            ),
        }
        required = load_json("required_strategy_analysis.json")
        self.responses.update(
            {
                "required_pest_analysis": {"pest": required["pest"]},
                "required_market_analysis": {"market": required["market"]},
                "required_five_forces_analysis": {
                    "five_forces": required["five_forces"]
                },
            }
        )
        self.calls: list[str] = []
        self.diagnostics = SimpleNamespace(
            api_calls=0,
            input_tokens=0,
            output_tokens=0,
        )

    def generate_json(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> ModelResponse:
        self.calls.append(task)
        self.diagnostics.api_calls += 1
        self.diagnostics.input_tokens += 100
        self.diagnostics.output_tokens += 50
        return ModelResponse(data=self.responses[task], model="fake")


class FakeSearchClient:
    def __init__(self, *, extracted: bool = True) -> None:
        self.search_results = load_json("search_results.json")[:3]
        self.extract_results = load_json("extract_results.json") if extracted else []
        self.queries: list[str] = []

    def search(self, queries, *, max_results: int = 15):
        self.queries = list(queries)
        return self.search_results

    def extract(self, urls):
        return self.extract_results


class ConditionalTimeoutModelClient(FakeModelClient):
    def generate_json(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> ModelResponse:
        if task == "conditional_modules_and_action_plan":
            raise DoubaoTimeoutError("扩展模块超时")
        return super().generate_json(task=task, payload=payload)


def realtime_request() -> ResearchRequest:
    return ResearchRequest.model_validate(load_json("research_request.json")).model_copy(
        update={"mode": RunMode.REALTIME}
    )


def test_sample_repository_loads_pre_generated_report_without_clients() -> None:
    result = SampleResearchRepository().load()

    assert result.request.mode is RunMode.SAMPLE
    assert result.artifact.audit.is_valid
    assert result.artifact.length_target_met
    assert result.artifact.markdown == (SAMPLE_DIR / "strategy_report.md").read_text(
        encoding="utf-8"
    )
    assert [item.value for item in result.conditional.enabled_modules] == [
        "value_chain",
        "lifecycle",
    ]


def test_realtime_pipeline_runs_fixed_workflow_and_reports_usage() -> None:
    model = FakeModelClient()
    search = FakeSearchClient()
    progress: list[str] = []

    result = ResearchPipeline(model, search).run(
        realtime_request(),
        progress=lambda stage, message: progress.append(stage),
    )

    assert model.calls == [
        "research_plan",
        "evidence_extraction",
        "required_pest_analysis",
        "required_market_analysis",
        "required_five_forces_analysis",
        "conditional_modules_and_action_plan",
    ]
    assert progress == [
        "validating",
        "planning",
        "searching",
        "building_evidence",
        "analyzing",
        "verifying",
        "completed",
    ]
    assert search.queries == result.plan.search_queries
    assert result.artifact.audit.is_valid
    assert result.model_calls == 6
    assert result.model_tokens == 900
    assert result.search_queries == len(result.plan.search_queries)
    assert not hasattr(result, "api_key")


def test_pipeline_stops_when_no_full_text_source_is_available() -> None:
    model = FakeModelClient()

    with pytest.raises(InsufficientEvidenceError, match="证据不足"):
        ResearchPipeline(model, FakeSearchClient(extracted=False)).run(
            realtime_request()
        )

    assert model.calls == ["research_plan"]


def test_pipeline_keeps_base_report_when_conditional_stage_times_out() -> None:
    progress: list[str] = []

    result = ResearchPipeline(
        ConditionalTimeoutModelClient(),
        FakeSearchClient(),
    ).run(
        realtime_request(),
        progress=lambda stage, message: progress.append(stage),
    )

    assert "analyzing_fallback" in progress
    assert not result.conditional.enabled_modules
    assert result.artifact.audit.is_valid
