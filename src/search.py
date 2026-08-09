"""Tavily adapter with bounded search, extraction, and diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tavily import TavilyClient

from src.config import MAX_SEARCH_QUERIES, MAX_SOURCES, SEARCH_RESULTS_PER_QUERY


TRACKING_QUERY_KEYS = {
    "from",
    "ref",
    "source",
    "spm",
    "tracking_id",
}

SECRET_PATTERNS = (
    re.compile(r"\btvly-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


class SearchError(RuntimeError):
    """Base error for the public web research adapter."""


class SearchServiceError(SearchError):
    """Raised when every Tavily search request fails."""


class NoSearchResultsError(SearchError):
    """Raised when successful searches contain no usable URLs."""


class ExtractionServiceError(SearchError):
    """Raised when the batch extraction request itself fails."""


@dataclass
class SearchDiagnostics:
    query_count: int = 0
    successful_queries: int = 0
    failed_queries: dict[str, str] = field(default_factory=dict)
    duplicate_results: int = 0
    invalid_results: int = 0
    extraction_successes: int = 0
    extraction_failed_urls: list[str] = field(default_factory=list)
    usage: list[Mapping[str, Any]] = field(default_factory=list)


def normalize_url(value: object) -> str | None:
    """Return a stable HTTP(S) URL or None when the value is unusable."""

    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None

        hostname = parsed.hostname.lower().rstrip(".")
        port = parsed.port
        if port and not (
            parsed.scheme.lower() == "http" and port == 80
        ) and not (parsed.scheme.lower() == "https" and port == 443):
            hostname = f"{hostname}:{port}"

        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")

        query_items = []
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
            normalized_key = key.lower()
            if normalized_key.startswith("utm_") or normalized_key in TRACKING_QUERY_KEYS:
                continue
            query_items.append((key, item_value))
        query_items.sort()

        return urlunsplit(
            (
                parsed.scheme.lower(),
                hostname,
                path,
                urlencode(query_items, doseq=True),
                "",
            )
        )
    except (TypeError, ValueError):
        return None


class TavilySearchClient:
    """Implement the SearchClient protocol without storing the API key."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        timeout: float = 30,
    ) -> None:
        if client is None and not api_key:
            raise ValueError("api_key is required when client is not provided")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        self._client = client if client is not None else TavilyClient(api_key=api_key)
        self._timeout = timeout
        self.diagnostics = SearchDiagnostics()

    def search(
        self,
        queries: Sequence[str],
        *,
        max_results: int = MAX_SOURCES,
    ) -> list[Mapping[str, Any]]:
        clean_queries = _clean_queries(queries)
        if not 1 <= max_results <= MAX_SOURCES:
            raise ValueError(f"max_results must be between 1 and {MAX_SOURCES}")

        self.diagnostics = SearchDiagnostics(query_count=len(clean_queries))
        by_url: dict[str, dict[str, Any]] = {}

        for query in clean_queries:
            try:
                response = self._client.search(
                    query=query,
                    search_depth="basic",
                    topic="general",
                    max_results=min(SEARCH_RESULTS_PER_QUERY, max_results),
                    include_answer=False,
                    include_raw_content=False,
                    include_usage=True,
                    timeout=self._timeout,
                )
                self.diagnostics.successful_queries += 1
                usage = response.get("usage") if isinstance(response, Mapping) else None
                if isinstance(usage, Mapping):
                    self.diagnostics.usage.append(usage)
            except Exception as exc:  # Tavily exposes multiple transport errors.
                self.diagnostics.failed_queries[query] = _safe_error(exc)
                continue

            raw_results = response.get("results", []) if isinstance(response, Mapping) else []
            for raw in raw_results:
                if not isinstance(raw, Mapping):
                    self.diagnostics.invalid_results += 1
                    continue
                normalized = normalize_url(raw.get("url"))
                if normalized is None:
                    self.diagnostics.invalid_results += 1
                    continue

                candidate = _normalize_search_result(raw, normalized, query)
                existing = by_url.get(normalized)
                if existing is not None:
                    self.diagnostics.duplicate_results += 1
                    if candidate["score"] > existing["score"]:
                        by_url[normalized] = candidate
                    continue
                by_url[normalized] = candidate

        if self.diagnostics.successful_queries == 0:
            raise SearchServiceError("all Tavily search requests failed")
        if not by_url:
            raise NoSearchResultsError("search returned no usable HTTP(S) results")

        ranked = sorted(
            by_url.values(),
            key=lambda item: (-item["score"], item["url"]),
        )
        return ranked[:max_results]

    def extract(self, urls: Sequence[str]) -> list[Mapping[str, Any]]:
        clean_urls = _clean_urls(urls)
        if not clean_urls:
            return []

        try:
            response = self._client.extract(
                urls=clean_urls,
                extract_depth="basic",
                format="markdown",
                include_usage=True,
                timeout=self._timeout,
            )
        except Exception as exc:
            self.diagnostics.extraction_failed_urls = clean_urls
            raise ExtractionServiceError(_safe_error(exc)) from exc

        if not isinstance(response, Mapping):
            self.diagnostics.extraction_failed_urls = clean_urls
            raise ExtractionServiceError("Tavily extract returned an invalid response")

        usage = response.get("usage")
        if isinstance(usage, Mapping):
            self.diagnostics.usage.append(usage)

        extracted: dict[str, dict[str, Any]] = {}
        for raw in response.get("results", []):
            if not isinstance(raw, Mapping):
                continue
            normalized = normalize_url(raw.get("url"))
            content = raw.get("raw_content") or raw.get("content")
            if normalized is None or not isinstance(content, str) or not content.strip():
                continue
            extracted[normalized] = {
                "url": normalized,
                "raw_content": content.strip(),
            }

        failed_urls = set(clean_urls) - set(extracted)
        for failed in response.get("failed_results", []):
            value = failed.get("url") if isinstance(failed, Mapping) else failed
            normalized = normalize_url(value)
            if normalized:
                failed_urls.add(normalized)

        self.diagnostics.extraction_successes = len(extracted)
        self.diagnostics.extraction_failed_urls = sorted(failed_urls)
        return list(extracted.values())


def _clean_queries(queries: Sequence[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for value in queries:
        if not isinstance(value, str) or not value.strip():
            continue
        query = " ".join(value.split())
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean.append(query)
        if len(clean) == MAX_SEARCH_QUERIES:
            break
    if not clean:
        raise ValueError("at least one non-empty search query is required")
    return clean


def _clean_urls(urls: Sequence[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for value in urls:
        normalized = normalize_url(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        clean.append(normalized)
        if len(clean) == MAX_SOURCES:
            break
    return clean


def _normalize_search_result(
    raw: Mapping[str, Any],
    normalized_url: str,
    query: str,
) -> dict[str, Any]:
    score = raw.get("score", 0)
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = 0.0

    return {
        "title": str(raw.get("title") or "Untitled source").strip(),
        "url": normalized_url,
        "content": str(raw.get("content") or "").strip(),
        "score": numeric_score,
        "query": query,
        "published_date": raw.get("published_date"),
        "publisher": raw.get("publisher"),
    }


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    for pattern in SECRET_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    return message[:300] or exc.__class__.__name__
