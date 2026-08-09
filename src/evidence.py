"""Convert normalized search and extract output into a citable evidence pool."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from urllib.parse import urlsplit

from src.config import MAX_SOURCES, MIN_KEY_FACT_SOURCES
from src.models import (
    ContentOrigin,
    EvidencePool,
    SourceRecord,
    SourceTier,
)
from src.search import normalize_url


DEFAULT_PRIMARY_DOMAINS = {
    "cninfo.com.cn",
    "gov.cn",
    "sse.com.cn",
    "stats.gov.cn",
    "szse.cn",
    "volcengine.com",
}

DEFAULT_PROFESSIONAL_DOMAINS = {
    "caict.ac.cn",
    "deloitte.com",
    "ey.com",
    "gartner.com",
    "idc.com",
    "kpmg.com",
    "mckinsey.com",
    "pwc.com",
}


class SourceClassifier:
    """Classify sources using explicit domains instead of model guesses."""

    def __init__(
        self,
        *,
        primary_domains: Sequence[str] = (),
        professional_domains: Sequence[str] = (),
    ) -> None:
        self.primary_domains = {
            domain.lower().strip(". ")
            for domain in (*DEFAULT_PRIMARY_DOMAINS, *primary_domains)
            if domain.strip(". ")
        }
        self.professional_domains = {
            domain.lower().strip(". ")
            for domain in (*DEFAULT_PROFESSIONAL_DOMAINS, *professional_domains)
            if domain.strip(". ")
        }

    def classify(self, url: str) -> SourceTier:
        hostname = (urlsplit(url).hostname or "").lower()
        if _matches_domain(hostname, self.primary_domains) or hostname.endswith(".gov.cn"):
            return SourceTier.PRIMARY
        if _matches_domain(hostname, self.professional_domains):
            return SourceTier.PROFESSIONAL
        return SourceTier.LEAD


class EvidencePoolBuilder:
    """Create SourceRecord objects and expose evidence sufficiency warnings."""

    def __init__(
        self,
        *,
        classifier: SourceClassifier | None = None,
        max_sources: int = MAX_SOURCES,
        minimum_key_fact_sources: int = MIN_KEY_FACT_SOURCES,
    ) -> None:
        if not 1 <= max_sources <= MAX_SOURCES:
            raise ValueError(f"max_sources must be between 1 and {MAX_SOURCES}")
        if minimum_key_fact_sources < 1:
            raise ValueError("minimum_key_fact_sources must be positive")
        self.classifier = classifier or SourceClassifier()
        self.max_sources = max_sources
        self.minimum_key_fact_sources = minimum_key_fact_sources

    def build(
        self,
        search_results: Sequence[Mapping[str, object]],
        extracted_results: Sequence[Mapping[str, object]],
    ) -> EvidencePool:
        extracted = _index_extracted_results(extracted_results)
        sources: list[SourceRecord] = []
        seen_urls: set[str] = set()

        for raw in search_results:
            normalized = normalize_url(raw.get("url"))
            if normalized is None or normalized in seen_urls:
                continue

            full_text = extracted.get(normalized)
            search_snippet = _clean_text(raw.get("content"))
            excerpt = _clean_text(full_text) if full_text else search_snippet
            if not excerpt:
                continue

            seen_urls.add(normalized)
            source_id = f"S{len(sources) + 1:02d}"
            origin = (
                ContentOrigin.FULL_TEXT
                if full_text
                else ContentOrigin.SEARCH_SNIPPET
            )
            hostname = urlsplit(normalized).hostname or "unknown"
            publisher_value = raw.get("publisher")
            publisher = (
                str(publisher_value).strip()
                if publisher_value and str(publisher_value).strip()
                else hostname.removeprefix("www.")
            )

            sources.append(
                SourceRecord(
                    source_id=source_id,
                    title=str(raw.get("title") or hostname).strip(),
                    publisher=publisher,
                    published_at=_parse_date(raw.get("published_date")),
                    url=normalized,
                    tier=self.classifier.classify(normalized),
                    origin=origin,
                    excerpt=excerpt[:4000],
                    time_scope=_optional_text(raw.get("time_scope"), 100),
                    region_scope=_optional_text(raw.get("region_scope"), 100),
                    unit=_optional_text(raw.get("unit"), 100),
                    statistical_scope=_optional_text(
                        raw.get("statistical_scope"),
                        300,
                    ),
                )
            )
            if len(sources) == self.max_sources:
                break

        key_fact_count = sum(source.supports_key_fact for source in sources)
        warnings: list[str] = []
        snippet_count = len(sources) - key_fact_count
        if snippet_count:
            warnings.append(
                f"{snippet_count} 个来源只有搜索摘要，不能单独支撑关键事实。"
            )
        if key_fact_count < self.minimum_key_fact_sources:
            warnings.append(
                "证据不足：可支撑关键事实的正文来源少于 "
                f"{self.minimum_key_fact_sources} 个。"
            )

        return EvidencePool(
            sources=sources,
            warnings=warnings,
            search_result_count=len(search_results),
            extraction_success_count=len(extracted),
            minimum_key_fact_sources=self.minimum_key_fact_sources,
        )


def _index_extracted_results(
    extracted_results: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for raw in extracted_results:
        normalized = normalize_url(raw.get("url"))
        content = raw.get("raw_content") or raw.get("content")
        cleaned = _clean_text(content)
        if normalized and cleaned:
            indexed[normalized] = cleaned
    return indexed


def _matches_domain(hostname: str, domains: set[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _optional_text(value: object, max_length: int) -> str | None:
    cleaned = _clean_text(value)
    return cleaned[:max_length] if cleaned else None


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        try:
            return date.fromisoformat(normalized[:10])
        except ValueError:
            return None
