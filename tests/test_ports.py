from collections.abc import Mapping, Sequence
from typing import Any

from src.models import ModelResponse
from src.ports import ModelClient, SearchClient


class FakeSearchClient:
    def search(
        self,
        queries: Sequence[str],
        *,
        max_results: int = 15,
    ) -> list[Mapping[str, Any]]:
        return []

    def extract(self, urls: Sequence[str]) -> list[Mapping[str, Any]]:
        return []


class FakeModelClient:
    def generate_json(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
    ) -> ModelResponse:
        return ModelResponse(data={}, model="fake")


def test_fake_clients_satisfy_runtime_protocols() -> None:
    assert isinstance(FakeSearchClient(), SearchClient)
    assert isinstance(FakeModelClient(), ModelClient)
