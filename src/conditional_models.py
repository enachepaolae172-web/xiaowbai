"""Contracts for evidence-gated extension modules and strategic action plans."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.models import Confidence, ModuleName, StrictModel
from src.strategy_models import EvidenceBackedFinding, LongText, ShortText, SourceId


EXTENSION_MODULES = {
    ModuleName.CONCENTRATION,
    ModuleName.VALUE_CHAIN,
    ModuleName.KEY_SUCCESS_FACTORS,
    ModuleName.LIFECYCLE,
    ModuleName.INNOVATION_PRICE_SHARE,
}


class ExtensionEvidenceProfile(StrictModel):
    module: ModuleName
    relevant_to_question: bool
    rationale: LongText
    evidence_ids: list[SourceId] = Field(default_factory=list, max_length=15)
    missing_evidence: list[LongText] = Field(default_factory=list, max_length=10)
    comparable_periods: int = Field(default=0, ge=0, le=20)
    value_chain_stages: int = Field(default=0, ge=0, le=20)
    has_profit_or_control_evidence: bool = False
    compared_competitors: int = Field(default=0, ge=0, le=20)
    capability_dimensions: int = Field(default=0, ge=0, le=20)
    lifecycle_signals: int = Field(default=0, ge=0, le=20)
    comparable_products: int = Field(default=0, ge=0, le=20)
    has_price_evidence: bool = False
    has_share_evidence: bool = False

    @field_validator("module")
    @classmethod
    def validate_extension_module(cls, value: ModuleName) -> ModuleName:
        if value not in EXTENSION_MODULES:
            raise ValueError("profile module must be an extension module")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("profile evidence_ids must be unique")
        return values


class ExtensionModuleAnalysis(EvidenceBackedFinding):
    module: ModuleName
    title: ShortText
    summary: LongText

    @field_validator("module")
    @classmethod
    def validate_extension_module(cls, value: ModuleName) -> ModuleName:
        if value not in EXTENSION_MODULES:
            raise ValueError("analysis module must be an extension module")
        return value


class ExtensionModuleDraft(StrictModel):
    profile: ExtensionEvidenceProfile
    analysis: ExtensionModuleAnalysis | None = None

    @model_validator(mode="after")
    def validate_matching_module(self) -> ExtensionModuleDraft:
        if self.analysis and self.analysis.module is not self.profile.module:
            raise ValueError("profile and analysis modules must match")
        return self


class StrategyChoice(StrictModel):
    choice: LongText
    rationale: LongText
    evidence_ids: list[SourceId] = Field(min_length=1, max_length=15)
    confidence: Confidence

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("choice evidence_ids must be unique")
        return values


class ValidationAction(StrictModel):
    milestone_day: int = Field(ge=1, le=90)
    action: LongText
    owner: ShortText
    success_metric: LongText
    evidence_ids: list[SourceId] = Field(min_length=1, max_length=15)

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("validation action evidence_ids must be unique")
        return values


class StrategicActionPlan(StrictModel):
    target_customers: list[StrategyChoice] = Field(min_length=1, max_length=5)
    product_directions: list[StrategyChoice] = Field(min_length=1, max_length=5)
    channel_directions: list[StrategyChoice] = Field(min_length=1, max_length=5)
    value_chain_choices: list[StrategyChoice] = Field(min_length=1, max_length=5)
    validation_actions: list[ValidationAction] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_milestones(self) -> StrategicActionPlan:
        days = [item.milestone_day for item in self.validation_actions]
        if set(days) != {30, 60, 90}:
            raise ValueError("validation actions must use 30, 60, and 90 day milestones")
        return self


class ConditionalAnalysisDraft(StrictModel):
    modules: list[ExtensionModuleDraft] = Field(min_length=5, max_length=5)
    action_plan: StrategicActionPlan

    @model_validator(mode="after")
    def validate_all_extension_modules(self) -> ConditionalAnalysisDraft:
        modules = [item.profile.module for item in self.modules]
        if set(modules) != EXTENSION_MODULES:
            raise ValueError("draft must contain each extension module exactly once")
        return self


class ModuleDecisionRecord(StrictModel):
    module: ModuleName
    enabled: bool
    reason: LongText
    supporting_source_ids: list[SourceId] = Field(default_factory=list, max_length=15)
    missing_evidence: list[LongText] = Field(default_factory=list, max_length=10)
    analysis: ExtensionModuleAnalysis | None = None

    @model_validator(mode="after")
    def validate_enabled_state(self) -> ModuleDecisionRecord:
        if self.enabled != (self.analysis is not None):
            raise ValueError("enabled state must match analysis presence")
        return self


class ConditionalAnalysisBundle(StrictModel):
    decisions: list[ModuleDecisionRecord] = Field(min_length=5, max_length=5)
    action_plan: StrategicActionPlan

    @model_validator(mode="after")
    def validate_all_extension_modules(self) -> ConditionalAnalysisBundle:
        modules = [item.module for item in self.decisions]
        if set(modules) != EXTENSION_MODULES:
            raise ValueError("bundle must contain each extension module exactly once")
        return self

    @property
    def enabled_modules(self) -> list[ModuleName]:
        return [item.module for item in self.decisions if item.enabled]

    @property
    def skipped_modules(self) -> list[ModuleName]:
        return [item.module for item in self.decisions if not item.enabled]
