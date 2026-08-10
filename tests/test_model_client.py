from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError

from src.config import (
    DEFAULT_MODEL_MAX_RETRIES,
    DEFAULT_MODEL_MAX_TOKENS,
    DEFAULT_MODEL_TIMEOUT,
)
from src.model_client import (
    DoubaoAuthenticationError,
    DoubaoModelClient,
    DoubaoRateLimitError,
    DoubaoTimeoutError,
    StructuredOutputError,
)
from src.ports import ModelClient


def completion(
    content: str,
    *,
    model: str = "doubao-test",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        ),
    )


class FakeCompletions:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class FakeOpenAI:
    def __init__(self, outputs: list[Any]) -> None:
        self.completions = FakeCompletions(outputs)
        self.chat = SimpleNamespace(completions=self.completions)


def test_doubao_client_satisfies_model_protocol_and_tracks_usage() -> None:
    fake = FakeOpenAI([completion('{"status":"ok"}')])
    client = DoubaoModelClient(client=fake)

    response = client.generate_json(task="connection_test", payload={})

    assert isinstance(client, ModelClient)
    assert response.data == {"status": "ok"}
    assert response.input_tokens == 10
    assert response.output_tokens == 5
    assert client.diagnostics.api_calls == 1
    assert client.diagnostics.input_tokens == 10
    assert fake.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert fake.completions.calls[0]["max_tokens"] == DEFAULT_MODEL_MAX_TOKENS


def test_markdown_json_fence_is_accepted_without_repair() -> None:
    fake = FakeOpenAI([completion('```json\n{"status":"ok"}\n```')])
    client = DoubaoModelClient(client=fake)

    response = client.test_connection()

    assert response.data["status"] == "ok"
    assert client.diagnostics.repair_attempts == 0
    assert len(fake.completions.calls) == 1


def test_invalid_json_is_repaired_once_and_usage_is_summed() -> None:
    fake = FakeOpenAI(
        [
            completion("not json", input_tokens=8, output_tokens=2),
            completion('{"status":"ok"}', input_tokens=6, output_tokens=3),
        ]
    )
    client = DoubaoModelClient(client=fake)

    response = client.test_connection()

    assert response.input_tokens == 14
    assert response.output_tokens == 5
    assert client.diagnostics.repair_attempts == 1
    assert client.diagnostics.api_calls == 2
    assert "repair" in fake.completions.calls[1]["messages"][0]["content"].lower()


def test_two_invalid_json_responses_stop_after_one_repair() -> None:
    fake = FakeOpenAI([completion("not json"), completion("still not json")])
    client = DoubaoModelClient(client=fake)

    with pytest.raises(StructuredOutputError, match="连续两次"):
        client.generate_json(task="connection_test", payload={})

    assert client.diagnostics.repair_attempts == 1
    assert len(fake.completions.calls) == 2


def test_unsupported_task_is_rejected_before_api_call() -> None:
    fake = FakeOpenAI([])
    client = DoubaoModelClient(client=fake)

    with pytest.raises(ValueError, match="unsupported model task"):
        client.generate_json(task="unknown", payload={})

    assert not fake.completions.calls


def _status_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://ark.example.test/chat")
    return httpx.Response(status_code, request=request)


def test_authentication_error_has_safe_user_message() -> None:
    error = AuthenticationError(
        "invalid key FAKE_API_KEY_VALUE",
        response=_status_response(401),
        body=None,
    )
    client = DoubaoModelClient(client=FakeOpenAI([error]))

    with pytest.raises(DoubaoAuthenticationError) as captured:
        client.generate_json(task="connection_test", payload={})

    assert "FAKE_API_KEY_VALUE" not in str(captured.value)
    assert "API Key 无效" in str(captured.value)
    assert client.diagnostics.api_calls == 1


def test_rate_limit_error_is_mapped() -> None:
    error = RateLimitError(
        "rate limited",
        response=_status_response(429),
        body=None,
    )
    client = DoubaoModelClient(client=FakeOpenAI([error]))

    with pytest.raises(DoubaoRateLimitError, match="限流"):
        client.generate_json(task="connection_test", payload={})


def test_timeout_error_is_mapped() -> None:
    request = httpx.Request("POST", "https://ark.example.test/chat")
    client = DoubaoModelClient(client=FakeOpenAI([APITimeoutError(request=request)]))

    with pytest.raises(DoubaoTimeoutError, match="180 秒"):
        client.generate_json(task="connection_test", payload={})


def test_default_model_settings_allow_long_research_calls() -> None:
    assert DEFAULT_MODEL_TIMEOUT == 180.0
    assert DEFAULT_MODEL_MAX_RETRIES == 1
