"""Validated contracts for the mandatory strategy analysis modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from src.models import Confidence, StrictModel


ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1200),
]
SourceId = Annotated[str, StringConstraints(pattern=r"^S\d{2,3}$")]


class PestDimension(StrEnum):
    POLITICAL = "political"
    ECONOMIC = "economic"
    SOCIAL = "social"
    TECHNOLOGICAL = "technological"


class ExternalImpact(StrEnum):
    OPPORTUNITY = "opportunity"
    THREAT = "threat"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class GrowthStage(StrEnum):
    INTRODUCTION = "introduction"
    GROWTH = "growth"
    MATURITY = "maturity"
    ADJUSTMENT = "adjustment"
    UNKNOWN = "unknown"


class CustomerRole(StrEnum):
    PRODUCT_USER = "product_user"
    BUSINESS_OWNER = "business_owner"
    TECHNICAL_EVALUATOR = "technical_evaluator"
    PROCUREMENT_DECIDER = "procurement_decider"
    FINAL_PAYER = "final_payer"


class ForceName(StrEnum):
    RIVALRY = "rivalry"
    NEW_ENTRANTS = "new_entrants"
    SUBSTITUTES = "substitutes"
    SUPPLIER_POWER = "supplier_power"
    BUYER_POWER = "buyer_power"


class EvidenceBackedFinding(StrictModel):
    facts: list[LongText] = Field(default_factory=list, max_length=10)
    judgment: LongText
    recommendations: list[LongText] = Field(min_length=1, max_length=8)
    evidence_ids: list[SourceId] = Field(default_factory=list, max_length=15)
    counterpoints: list[LongText] = Field(min_length=1, max_length=8)
    unknowns: list[LongText] = Field(default_factory=list, max_length=8)
    confidence: Confidence

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_ids must be unique")
        return values

    @model_validator(mode="after")
    def validate_evidence_state(self) -> EvidenceBackedFinding:
        if self.evidence_ids and not self.facts:
            raise ValueError("evidence-backed findings must include facts")
        if not self.evidence_ids:
            if self.facts:
                raise ValueError("facts require evidence_ids")
            if self.confidence is not Confidence.UNKNOWN:
                raise ValueError("unsupported findings must use unknown confidence")
            if not self.unknowns:
                raise ValueError("unsupported findings must explain what is unknown")
        return self


class PestAssessment(EvidenceBackedFinding):
    dimension: PestDimension
    impact: ExternalImpact

    @model_validator(mode="after")
    def validate_unsupported_impact(self) -> PestAssessment:
        if not self.evidence_ids and self.impact is not ExternalImpact.UNKNOWN:
            raise ValueError("unsupported PEST assessments must use unknown impact")
        return self


class PestAnalysis(StrictModel):
    assessments: list[PestAssessment] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_all_dimensions(self) -> PestAnalysis:
        dimensions = [item.dimension for item in self.assessments]
        if set(dimensions) != set(PestDimension):
            raise ValueError("PEST must contain each dimension exactly once")
        return self


class ComputedGrowth(StrictModel):
    start_year: int = Field(ge=2000, le=2100)
    end_year: int = Field(ge=2000, le=2100)
    start_value: float = Field(gt=0)
    end_value: float = Field(ge=0)
    cagr_percent: float = Field(ge=-100)

    @model_validator(mode="after")
    def validate_period(self) -> ComputedGrowth:
        if self.end_year <= self.start_year:
            raise ValueError("growth end_year must be later than start_year")
        return self


class MarketDataPoint(StrictModel):
    year: int = Field(ge=2000, le=2100)
    value: float = Field(ge=0)
    region: ShortText
    unit: ShortText
    statistical_scope: ShortText
    source_id: SourceId
    is_forecast: bool = False


class MarketSeries(StrictModel):
    metric_name: ShortText
    points: list[MarketDataPoint] = Field(min_length=1, max_length=20)
    cagr: ComputedGrowth | None = None

    @model_validator(mode="after")
    def validate_comparable_points(self) -> MarketSeries:
        years = [point.year for point in self.points]
        if years != sorted(years) or len(years) != len(set(years)):
            raise ValueError("market series years must be unique and ascending")
        if self.points[0].value <= 0:
            raise ValueError("market series start value must be positive")
        scopes = {
            (point.region, point.unit, point.statistical_scope)
            for point in self.points
        }
        if len(scopes) != 1:
            raise ValueError("market series points must share region, unit, and scope")
        return self


class MarketTotalAssessment(EvidenceBackedFinding):
    series: list[MarketSeries] = Field(default_factory=list, max_length=15)
    growth_stage: GrowthStage
    stage_rationale: LongText

    @model_validator(mode="after")
    def validate_unsupported_market_state(self) -> MarketTotalAssessment:
        if not self.evidence_ids:
            if self.series:
                raise ValueError("market series require supporting evidence")
            if self.growth_stage is not GrowthStage.UNKNOWN:
                raise ValueError("unsupported markets must use unknown growth stage")
        return self


class CustomerRoleAssessment(EvidenceBackedFinding):
    role: CustomerRole


class CustomerStructureAssessment(EvidenceBackedFinding):
    segmentation_dimensions: list[ShortText] = Field(min_length=2, max_length=5)
    priority_segments: list[ShortText] = Field(default_factory=list, max_length=8)
    roles: list[CustomerRoleAssessment] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_customer_roles(self) -> CustomerStructureAssessment:
        roles = [item.role for item in self.roles]
        if set(roles) != set(CustomerRole):
            raise ValueError("customer analysis must distinguish all five roles")
        if not self.evidence_ids and self.priority_segments:
            raise ValueError("priority segments require supporting evidence")
        return self


class ProcurementDriver(StrictModel):
    driver: ShortText
    priority: int = Field(ge=1, le=10)
    rationale: LongText


class ProcurementAssessment(EvidenceBackedFinding):
    ranked_drivers: list[ProcurementDriver] = Field(default_factory=list, max_length=10)

    @field_validator("ranked_drivers")
    @classmethod
    def validate_driver_priorities(
        cls,
        values: list[ProcurementDriver],
    ) -> list[ProcurementDriver]:
        priorities = [item.priority for item in values]
        if len(priorities) != len(set(priorities)):
            raise ValueError("procurement driver priorities must be unique")
        return values

    @model_validator(mode="after")
    def validate_unsupported_ranking(self) -> ProcurementAssessment:
        if not self.evidence_ids and self.ranked_drivers:
            raise ValueError("ranked procurement drivers require supporting evidence")
        return self


class MarketAnalysis(StrictModel):
    total_market: MarketTotalAssessment
    customer_structure: CustomerStructureAssessment
    procurement_drivers: ProcurementAssessment


class ForceAssessment(EvidenceBackedFinding):
    force: ForceName
    pressure_score: int | None = Field(default=None, ge=1, le=5)
    uncertainty: LongText

    @model_validator(mode="after")
    def validate_pressure_score(self) -> ForceAssessment:
        if self.pressure_score is None:
            if self.confidence is not Confidence.UNKNOWN:
                raise ValueError("unscored forces must use unknown confidence")
            if not self.unknowns:
                raise ValueError("unscored forces must explain missing evidence")
        elif not self.evidence_ids:
            raise ValueError("scored forces require evidence_ids")
        elif self.confidence is Confidence.UNKNOWN:
            raise ValueError("scored forces require a stated confidence level")
        return self


class FiveForcesAnalysis(StrictModel):
    assessments: list[ForceAssessment] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_all_forces(self) -> FiveForcesAnalysis:
        forces = [item.force for item in self.assessments]
        if set(forces) != set(ForceName):
            raise ValueError("five forces must contain each force exactly once")
        return self


class StrategicConclusion(StrictModel):
    conclusion: LongText
    evidence_ids: list[SourceId] = Field(min_length=1, max_length=15)
    counterpoints: list[LongText] = Field(min_length=1, max_length=5)
    confidence: Confidence

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("conclusion evidence_ids must be unique")
        return values


class StrategicImplication(StrictModel):
    action: LongText
    rationale: LongText
    evidence_ids: list[SourceId] = Field(min_length=1, max_length=15)
    validation_step: LongText
    confidence: Confidence

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("implication evidence_ids must be unique")
        return values


class RequiredStrategyAnalysis(StrictModel):
    pest: PestAnalysis
    market: MarketAnalysis
    five_forces: FiveForcesAnalysis
    core_conclusions: list[StrategicConclusion] = Field(min_length=1, max_length=5)
    strategic_implications: list[StrategicImplication] = Field(
        min_length=1,
        max_length=8,
    )
    unknowns: list[LongText] = Field(default_factory=list, max_length=20)
