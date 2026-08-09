"""Validated data contracts shared across the research workflow."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields and validates assignments."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RunMode(StrEnum):
    SAMPLE = "sample"
    REALTIME = "realtime"


class SourceTier(StrEnum):
    PRIMARY = "primary"
    PROFESSIONAL = "professional"
    LEAD = "lead"


class ContentOrigin(StrEnum):
    FULL_TEXT = "full_text"
    OFFICIAL_SNIPPET = "official_snippet"
    SEARCH_SNIPPET = "search_snippet"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ModuleName(StrEnum):
    PEST = "pest"
    MARKET_OVERVIEW = "market_overview"
    CUSTOMER_STRUCTURE = "customer_structure"
    FIVE_FORCES = "five_forces"
    PRODUCT_STRUCTURE = "product_structure"
    REGIONAL_STRUCTURE = "regional_structure"
    PROCUREMENT_PROCESS = "procurement_process"
    CONCENTRATION = "concentration"
    VALUE_CHAIN = "value_chain"
    KEY_SUCCESS_FACTORS = "key_success_factors"
    LIFECYCLE = "lifecycle"
    INNOVATION_PRICE_SHARE = "innovation_price_share"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    PLANNING = "planning"
    SEARCHING = "searching"
    BUILDING_EVIDENCE = "building_evidence"
    ANALYZING = "analyzing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchRequest(StrictModel):
    industry: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1, max_length=100)
    start_year: int = Field(ge=2000, le=2100)
    end_year: int = Field(ge=2000, le=2100)
    target_company: str | None = Field(default=None, max_length=100)
    strategy_question: str = Field(min_length=10, max_length=1000)
    mode: RunMode = RunMode.SAMPLE

    @field_validator("target_company", mode="before")
    @classmethod
    def normalize_optional_company(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_year_range(self) -> ResearchRequest:
        if self.start_year > self.end_year:
            raise ValueError("start_year must not be later than end_year")
        return self


class SourceRecord(StrictModel):
    source_id: str = Field(pattern=r"^S\d{2,3}$")
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    published_at: date | None = None
    url: AnyHttpUrl
    tier: SourceTier
    origin: ContentOrigin
    excerpt: str = Field(min_length=1, max_length=4000)
    used_in: list[str] = Field(default_factory=list)
    time_scope: str | None = Field(default=None, max_length=100)
    region_scope: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=100)
    statistical_scope: str | None = Field(default=None, max_length=300)

    @property
    def supports_key_fact(self) -> bool:
        return self.origin is not ContentOrigin.SEARCH_SNIPPET


class ModuleDecision(StrictModel):
    module: ModuleName
    enabled: bool
    reason: str = Field(min_length=1, max_length=1000)
    supporting_source_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)

    @field_validator("supporting_source_ids")
    @classmethod
    def validate_source_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) not in {3, 4} or not value.startswith("S") or not value[1:].isdigit():
                raise ValueError(f"invalid source id: {value}")
        if len(values) != len(set(values)):
            raise ValueError("supporting_source_ids must be unique")
        return values


class AnalysisSection(StrictModel):
    module: ModuleName
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    facts: list[str] = Field(default_factory=list)
    judgments: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ResearchReport(StrictModel):
    schema_version: str = "0.1"
    request: ResearchRequest
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    core_conclusions: list[str] = Field(default_factory=list)
    module_decisions: list[ModuleDecision] = Field(default_factory=list)
    sections: list[AnalysisSection] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identifiers(self) -> ResearchReport:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")

        modules = [decision.module for decision in self.module_decisions]
        if len(modules) != len(set(modules)):
            raise ValueError("module decisions must be unique by module")

        known_ids = set(source_ids)
        referenced_ids = {
            source_id
            for decision in self.module_decisions
            for source_id in decision.supporting_source_ids
        }
        referenced_ids.update(
            source_id for section in self.sections for source_id in section.evidence_ids
        )
        missing_ids = sorted(referenced_ids - known_ids)
        if missing_ids:
            raise ValueError(f"unknown source ids referenced: {', '.join(missing_ids)}")
        return self

    @property
    def enabled_modules(self) -> list[ModuleName]:
        return [decision.module for decision in self.module_decisions if decision.enabled]

    @property
    def skipped_modules(self) -> list[ModuleName]:
        return [decision.module for decision in self.module_decisions if not decision.enabled]


class WorkflowEvent(StrictModel):
    status: WorkflowStatus
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note: str | None = Field(default=None, max_length=500)


class WorkflowRun(StrictModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    request: ResearchRequest
    status: WorkflowStatus = WorkflowStatus.PENDING
    history: list[WorkflowEvent] = Field(default_factory=list)
    result: ResearchReport | None = None
    error: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> WorkflowRun:
        if self.status is WorkflowStatus.COMPLETED and self.result is None:
            raise ValueError("completed workflow must contain a result")
        if self.status is WorkflowStatus.FAILED and not self.error:
            raise ValueError("failed workflow must contain an error")
        return self


class ModelResponse(StrictModel):
    data: dict[str, Any]
    model: str = Field(min_length=1, max_length=200)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
