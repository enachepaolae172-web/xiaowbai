from typing import Any

import pytest

from src.ports import SearchClient
from src.search import (
    ExtractionServiceError,
    NoSearchResultsError,
    SearchServiceError,
    TavilySearchClient,
    normalize_url,
)


class FakeTavilyClient:
    def __init__(
        self,
        *,
        responses: dict[str, dict[str, Any]] | None = None,
        extract_response: dict[str, Any] | None = None,
        failed_queries: set[str] | None = None,
        fail_extract: bool = False,
    ) -> None:
        self.responses = responses or {}
        self.extract_response = extract_response or {"results": [], "failed_results": []}
        self.failed_queries = failed_queries or set()
        self.fail_extract = fail_extract

    def search(self, query: str, **_: Any) -> dict[str, Any]:
        if query in self.failed_queries:
            raise TimeoutError(f"timeout for {query}")
        return self.responses.get(query, {"results": []})

    def extract(self, urls: list[str], **_: Any) -> dict[str, Any]:
        if self.fail_extract:
            raise TimeoutError("extract timeout")
        return self.extract_response


def test_tavily_adapter_satisfies_search_client_protocol() -> None:
    assert isinstance(TavilySearchClient(client=FakeTavilyClient()), SearchClient)


def test_normalize_url_removes_tracking_fragment_and_default_port() -> None:
    normalized = normalize_url(
        "HTTPS://Example.COM:443/path/?utm_source=test&b=2&a=1#section"
    )

    assert normalized == "https://example.com/path?a=1&b=2"


def test_search_deduplicates_filters_and_ranks_results() -> None:
    fake = FakeTavilyClient(
        responses={
            "query one": {
                "usage": {"credits": 1},
                "results": [
                    {
                        "title": "Lower score",
                        "url": "https://example.com/report?utm_source=a",
                        "content": "A",
                        "score": 0.4,
                    },
                    {
                        "title": "Invalid",
                        "url": "ftp://example.com/report",
                        "content": "B",
                        "score": 1,
                    },
                ],
            },
            "query two": {
                "results": [
                    {
                        "title": "Higher score",
                        "url": "https://example.com/report#top",
                        "content": "C",
                        "score": 0.9,
                    },
                    {
                        "title": "Second source",
                        "url": "https://example.org/other",
                        "content": "D",
                        "score": 0.8,
                    },
                ]
            },
        }
    )
    client = TavilySearchClient(client=fake)

    results = client.search([" query one ", "query two", "QUERY TWO"])

    assert [item["title"] for item in results] == ["Higher score", "Second source"]
    assert results[0]["url"] == "https://example.com/report"
    assert client.diagnostics.query_count == 2
    assert client.diagnostics.duplicate_results == 1
    assert client.diagnostics.invalid_results == 1
    assert client.diagnostics.usage == [{"credits": 1}]


def test_search_keeps_successes_when_one_query_fails() -> None:
    fake = FakeTavilyClient(
        responses={
            "works": {
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com",
                        "content": "Content",
                        "score": 1,
                    }
                ]
            }
        },
        failed_queries={"fails"},
    )
    client = TavilySearchClient(client=fake)

    results = client.search(["fails", "works"])

    assert len(results) == 1
    assert "fails" in client.diagnostics.failed_queries


def test_search_raises_when_all_queries_fail() -> None:
    client = TavilySearchClient(
        client=FakeTavilyClient(failed_queries={"one", "two"})
    )

    with pytest.raises(SearchServiceError, match="all Tavily"):
        client.search(["one", "two"])


def test_diagnostics_redact_api_keys_from_provider_errors() -> None:
    class KeyEchoingClient(FakeTavilyClient):
        def search(self, query: str, **_: Any) -> dict[str, Any]:
            raise RuntimeError("request failed for tvly-supersecret123")

    client = TavilySearchClient(client=KeyEchoingClient())

    with pytest.raises(SearchServiceError):
        client.search(["failing query"])

    message = client.diagnostics.failed_queries["failing query"]
    assert "tvly-supersecret123" not in message
    assert "[REDACTED]" in message


def test_search_raises_when_no_usable_results() -> None:
    client = TavilySearchClient(client=FakeTavilyClient())

    with pytest.raises(NoSearchResultsError, match="no usable"):
        client.search(["empty"])


def test_extract_returns_successes_and_tracks_failures() -> None:
    fake = FakeTavilyClient(
        extract_response={
            "usage": {"credits": 1},
            "results": [
                {
                    "url": "https://example.com/a?utm_source=test",
                    "raw_content": "Full text A",
                }
            ],
            "failed_results": [{"url": "https://example.com/b"}],
        }
    )
    client = TavilySearchClient(client=fake)

    results = client.extract(
        ["https://example.com/a", "https://example.com/b", "https://example.com/a"]
    )

    assert results == [
        {"url": "https://example.com/a", "raw_content": "Full text A"}
    ]
    assert client.diagnostics.extraction_successes == 1
    assert client.diagnostics.extraction_failed_urls == ["https://example.com/b"]


def test_extract_wraps_provider_failure() -> None:
    client = TavilySearchClient(client=FakeTavilyClient(fail_extract=True))

    with pytest.raises(ExtractionServiceError, match="extract timeout"):
        client.extract(["https://example.com/a"])
