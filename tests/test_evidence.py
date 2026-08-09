import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.evidence import EvidencePoolBuilder, SourceClassifier
from src.models import ContentOrigin, EvidencePool, SourceTier


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "sample"


def _load(name: str) -> list[dict[str, object]]:
    return json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))


def test_source_classifier_uses_explicit_domain_rules() -> None:
    classifier = SourceClassifier(primary_domains=["official.example"])

    assert classifier.classify("https://docs.official.example/a") is SourceTier.PRIMARY
    assert classifier.classify("https://www.caict.ac.cn/report") is SourceTier.PROFESSIONAL
    assert classifier.classify("https://news.example/story") is SourceTier.LEAD


def test_builder_creates_deduplicated_citable_sources() -> None:
    builder = EvidencePoolBuilder()

    pool = builder.build(_load("search_results.json"), _load("extract_results.json"))

    assert [source.source_id for source in pool.sources] == ["S01", "S02", "S03"]
    assert [source.tier for source in pool.sources] == [
        SourceTier.PRIMARY,
        SourceTier.PROFESSIONAL,
        SourceTier.LEAD,
    ]
    assert pool.sources[0].origin is ContentOrigin.FULL_TEXT
    assert pool.sources[1].origin is ContentOrigin.FULL_TEXT
    assert pool.sources[2].origin is ContentOrigin.SEARCH_SNIPPET
    assert pool.sources[2].supports_key_fact is False
    assert pool.search_result_count == 5
    assert pool.extraction_success_count == 2


def test_builder_marks_insufficient_key_fact_sources() -> None:
    pool = EvidencePoolBuilder(minimum_key_fact_sources=3).build(
        _load("search_results.json"),
        _load("extract_results.json"),
    )

    assert pool.is_sufficient is False
    assert len(pool.key_fact_sources) == 2
    assert any("证据不足" in warning for warning in pool.warnings)
    assert any("搜索摘要" in warning for warning in pool.warnings)


def test_pool_round_trip() -> None:
    pool = EvidencePoolBuilder(minimum_key_fact_sources=2).build(
        _load("search_results.json"),
        _load("extract_results.json"),
    )

    restored = EvidencePool.model_validate_json(pool.model_dump_json())

    assert restored == pool
    assert restored.is_sufficient is True


def test_pool_rejects_duplicate_urls() -> None:
    pool = EvidencePoolBuilder(minimum_key_fact_sources=2).build(
        _load("search_results.json"),
        _load("extract_results.json"),
    )
    data = pool.model_dump(mode="json")
    duplicate = dict(data["sources"][0])
    duplicate["source_id"] = "S99"
    data["sources"].append(duplicate)

    with pytest.raises(ValidationError, match="URLs must be unique"):
        EvidencePool.model_validate(data)


def test_builder_respects_maximum_sources() -> None:
    search_results = [
        {
            "title": f"Source {index}",
            "url": f"https://example.com/{index}",
            "content": "Search snippet",
            "score": 1,
        }
        for index in range(20)
    ]

    pool = EvidencePoolBuilder(max_sources=15).build(search_results, [])

    assert len(pool.sources) == 15
