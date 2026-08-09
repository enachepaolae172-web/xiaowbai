"""Deterministic evidence gates for optional strategy modules."""

from __future__ import annotations

from pydantic import ValidationError

from src.conditional_models import (
    ConditionalAnalysisBundle,
    ConditionalAnalysisDraft,
    ExtensionEvidenceProfile,
    ModuleDecisionRecord,
)
from src.models import ContentOrigin, EvidenceExtraction, EvidencePool, ModuleName, ResearchRequest
from src.ports import ModelClient
from src.research_model import ModelOutputValidationError
from src.strategy_models import RequiredStrategyAnalysis


class ConditionalAnalysisService:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def analyze(
        self,
        request: ResearchRequest,
        pool: EvidencePool,
        extraction: EvidenceExtraction,
        required: RequiredStrategyAnalysis,
    ) -> ConditionalAnalysisBundle:
        if not pool.sources:
            raise ValueError("evidence pool must contain at least one source")
        self._validate_extraction_ids(pool, extraction)

        response = self.client.generate_json(
            task="conditional_modules_and_action_plan",
            payload={
                "request": request.model_dump(mode="json"),
                "sources": [source.model_dump(mode="json") for source in pool.sources],
                "extracted_evidence": extraction.model_dump(mode="json"),
                "required_analysis": required.model_dump(mode="json"),
                "response_schema": ConditionalAnalysisDraft.model_json_schema(),
            },
        )
        draft = self._validate_response(response.data)
        sources = {source.source_id: source for source in pool.sources}
        self._validate_known_ids(sources, draft)
        self._validate_action_plan_sources(sources, draft)
        decisions = [self._decide(item, sources) for item in draft.modules]
        return ConditionalAnalysisBundle(
            decisions=decisions,
            action_plan=draft.action_plan,
        )

    @staticmethod
    def _validate_extraction_ids(
        pool: EvidencePool,
        extraction: EvidenceExtraction,
    ) -> None:
        expected = {source.source_id for source in pool.sources}
        actual = {item.source_id for item in extraction.items}
        if expected != actual:
            raise ModelOutputValidationError(
                "证据抽取结果与证据池来源编号不一致。"
            )
        sources = {source.source_id: source for source in pool.sources}
        for item in extraction.items:
            if (
                sources[item.source_id].origin is ContentOrigin.SEARCH_SNIPPET
                and item.facts
            ):
                raise ModelOutputValidationError(
                    f"{item.source_id} 仅有搜索摘要，不能抽取为事实。"
                )

    @staticmethod
    def _validate_response(data: dict) -> ConditionalAnalysisDraft:
        try:
            return ConditionalAnalysisDraft.model_validate(data)
        except ValidationError as exc:
            summaries = []
            for error in exc.errors(include_input=False)[:8]:
                location = ".".join(str(part) for part in error["loc"])
                summaries.append(f"{location}: {error['msg']}")
            raise ModelOutputValidationError(
                "条件模块输出不符合结构约束：" + "; ".join(summaries)
            ) from exc

    @staticmethod
    def _validate_known_ids(sources: dict, draft: ConditionalAnalysisDraft) -> None:
        referenced: set[str] = set()
        for item in draft.modules:
            referenced.update(item.profile.evidence_ids)
            if item.analysis:
                referenced.update(item.analysis.evidence_ids)
        for choices in (
            draft.action_plan.target_customers,
            draft.action_plan.product_directions,
            draft.action_plan.channel_directions,
            draft.action_plan.value_chain_choices,
        ):
            for choice in choices:
                referenced.update(choice.evidence_ids)
        for action in draft.action_plan.validation_actions:
            referenced.update(action.evidence_ids)

        unknown = sorted(referenced - set(sources))
        if unknown:
            raise ModelOutputValidationError(
                "条件模块引用了未知来源：" + ", ".join(unknown)
            )

    @staticmethod
    def _decide(item, sources: dict) -> ModuleDecisionRecord:
        profile = item.profile
        usable_ids = [
            source_id
            for source_id in profile.evidence_ids
            if sources[source_id].origin is not ContentOrigin.SEARCH_SNIPPET
        ]
        eligible, missing = _evaluate_eligibility(profile, bool(usable_ids))
        missing_evidence = list(dict.fromkeys([*profile.missing_evidence, *missing]))

        if not eligible:
            return ModuleDecisionRecord(
                module=profile.module,
                enabled=False,
                reason=_skip_reason(profile, missing),
                supporting_source_ids=usable_ids,
                missing_evidence=missing_evidence,
            )
        if item.analysis is None:
            return ModuleDecisionRecord(
                module=profile.module,
                enabled=False,
                reason="证据条件满足，但模型未返回可用分析，因此保守跳过。",
                supporting_source_ids=usable_ids,
                missing_evidence=[*missing_evidence, "缺少结构化分析输出"],
            )

        analysis_ids = set(item.analysis.evidence_ids)
        if not analysis_ids.issubset(set(usable_ids)):
            raise ModelOutputValidationError(
                f"{profile.module.value} 分析引用了画像之外或仅有摘要的来源。"
            )
        return ModuleDecisionRecord(
            module=profile.module,
            enabled=True,
            reason="相关性和最低证据条件均满足。",
            supporting_source_ids=usable_ids,
            missing_evidence=missing_evidence,
            analysis=item.analysis,
        )

    @staticmethod
    def _validate_action_plan_sources(
        sources: dict,
        draft: ConditionalAnalysisDraft,
    ) -> None:
        action_ids: set[str] = set()
        for choices in (
            draft.action_plan.target_customers,
            draft.action_plan.product_directions,
            draft.action_plan.channel_directions,
            draft.action_plan.value_chain_choices,
        ):
            for choice in choices:
                action_ids.update(choice.evidence_ids)
        for action in draft.action_plan.validation_actions:
            action_ids.update(action.evidence_ids)
        snippet_ids = sorted(
            source_id
            for source_id in action_ids
            if sources[source_id].origin is ContentOrigin.SEARCH_SNIPPET
        )
        if snippet_ids:
            raise ModelOutputValidationError(
                "搜索摘要不能支撑战略行动方案：" + ", ".join(snippet_ids)
            )


def _evaluate_eligibility(
    profile: ExtensionEvidenceProfile,
    has_usable_source: bool,
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if not profile.relevant_to_question:
        missing.append("与本次战略问题相关性不足")
    if not has_usable_source:
        missing.append("缺少可核验正文来源")

    if profile.module is ModuleName.CONCENTRATION:
        if profile.comparable_periods < 2:
            missing.append("缺少至少两个时期的可比市场份额")
    elif profile.module is ModuleName.VALUE_CHAIN:
        if profile.value_chain_stages < 2:
            missing.append("缺少至少两个价值链环节")
        if not profile.has_profit_or_control_evidence:
            missing.append("缺少利润分布或战略控制点证据")
    elif profile.module is ModuleName.KEY_SUCCESS_FACTORS:
        if profile.compared_competitors < 2:
            missing.append("缺少至少两个竞争者")
        if profile.capability_dimensions < 2:
            missing.append("缺少至少两个可比能力维度")
    elif profile.module is ModuleName.LIFECYCLE:
        if profile.lifecycle_signals < 2:
            missing.append("缺少至少两个生命周期信号")
    elif profile.module is ModuleName.INNOVATION_PRICE_SHARE:
        if profile.comparable_products < 2:
            missing.append("缺少至少两个可比产品")
        if not profile.has_price_evidence:
            missing.append("缺少价格证据")
        if not profile.has_share_evidence:
            missing.append("缺少份额证据")
    return not missing, missing


def _skip_reason(
    profile: ExtensionEvidenceProfile,
    missing: list[str],
) -> str:
    if missing:
        return "跳过：" + "；".join(missing) + "。"
    return "跳过：未满足模块启用条件。"
