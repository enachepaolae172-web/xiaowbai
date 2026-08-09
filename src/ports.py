"""External service boundaries used by the deterministic workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from src.models import ModelResponse


@runtime_checkable
class SearchClient(Protocol):
    """Search and extract public web sources without exposing vendor details."""

    def search(
        self,
        queries: Sequence[str],
        *,
        max_results: int = 15,
    ) -> list[Mapping[str, Any]]: ...

    def extract(self, urls: Sequence[str]) -> list[Mapping[str, Any]]: ...


@runtime_checkable
class ModelClient(Protocol):
    """Generate validated JSON-shaped data for one named workflow task."""

    def generate_json(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
    ) -> ModelResponse: ...
