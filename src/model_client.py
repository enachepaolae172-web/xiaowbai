"""OpenAI-compatible Doubao client with bounded JSON repair and safe diagnostics."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from src.config import (
    DEFAULT_ARK_BASE_URL,
    DEFAULT_ARK_MODEL,
    DEFAULT_MODEL_MAX_RETRIES,
    DEFAULT_MODEL_MAX_TOKENS,
    DEFAULT_MODEL_TIMEOUT,
)
from src.model_tasks import (
    BASE_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    instruction_for,
)
from src.models import ModelResponse


class DoubaoError(RuntimeError):
    """Base error safe to display in the local interface."""


class DoubaoAuthenticationError(DoubaoError):
    """Raised for invalid credentials or unavailable model access."""


class DoubaoRateLimitError(DoubaoError):
    """Raised when the provider rejects the request due to quota or rate."""


class DoubaoTimeoutError(DoubaoError):
    """Raised when the provider cannot be reached within the configured timeout."""


class DoubaoServiceError(DoubaoError):
    """Raised for other provider or transport failures."""


class StructuredOutputError(DoubaoError):
    """Raised when two consecutive responses are not JSON objects."""


@dataclass
class ModelDiagnostics:
    api_calls: int = 0
    repair_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class DoubaoModelClient:
    """Implement ModelClient through the Volcengine Ark OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_ARK_BASE_URL,
        model: str = DEFAULT_ARK_MODEL,
        timeout: float = DEFAULT_MODEL_TIMEOUT,
        max_retries: int = DEFAULT_MODEL_MAX_RETRIES,
        max_tokens: int = DEFAULT_MODEL_MAX_TOKENS,
        client: Any | None = None,
    ) -> None:
        if client is None and not api_key:
            raise ValueError("api_key is required when client is not provided")
        if not base_url.startswith("https://"):
            raise ValueError("base_url must use HTTPS")
        if not model.strip():
            raise ValueError("model must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if not 1 <= max_tokens <= 16000:
            raise ValueError("max_tokens must be between 1 and 16000")

        self._client = client if client is not None else OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model.strip()
        self.max_tokens = max_tokens
        self.diagnostics = ModelDiagnostics()

    def generate_json(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
    ) -> ModelResponse:
        instruction = instruction_for(task)
        serialized_payload = json.dumps(
            dict(payload),
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        messages = [
            {"role": "system", "content": BASE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Task:\n{instruction}\n\nInput JSON:\n{serialized_payload}",
            },
        ]

        first = self._create_completion(messages)
        first_content = _response_content(first)
        first_input, first_output = _response_usage(first)
        self._record_usage(first_input, first_output)

        try:
            data = _parse_json_object(first_content)
            return ModelResponse(
                data=data,
                model=_response_model(first, self.model),
                input_tokens=first_input,
                output_tokens=first_output,
            )
        except (json.JSONDecodeError, StructuredOutputError):
            self.diagnostics.repair_attempts += 1

        repair_messages = [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Repair this response into one JSON object:\n"
                    f"{first_content[:50000]}"
                ),
            },
        ]
        repaired = self._create_completion(repair_messages)
        repaired_content = _response_content(repaired)
        repair_input, repair_output = _response_usage(repaired)
        self._record_usage(repair_input, repair_output)

        try:
            data = _parse_json_object(repaired_content)
        except (json.JSONDecodeError, StructuredOutputError) as exc:
            raise StructuredOutputError(
                "豆包连续两次未返回有效 JSON，请稍后重试。"
            ) from exc

        return ModelResponse(
            data=data,
            model=_response_model(repaired, self.model),
            input_tokens=first_input + repair_input,
            output_tokens=first_output + repair_output,
        )

    def test_connection(self) -> ModelResponse:
        response = self.generate_json(task="connection_test", payload={"ping": True})
        if response.data.get("status") != "ok":
            raise StructuredOutputError("豆包已响应，但连接测试结果格式不正确。")
        return response

    def _create_completion(self, messages: Sequence[Mapping[str, str]]) -> Any:
        self.diagnostics.api_calls += 1
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=self.max_tokens,
            )
            return response
        except AuthenticationError as exc:
            raise DoubaoAuthenticationError(
                "豆包 API Key 无效，或当前账号无权访问配置的模型。"
            ) from exc
        except RateLimitError as exc:
            raise DoubaoRateLimitError(
                "豆包请求达到限流或额度上限，请稍后重试并检查账户额度。"
            ) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise DoubaoTimeoutError(
                "豆包连接超时或网络不可用，请检查网络后重试。"
            ) from exc
        except APIStatusError as exc:
            raise DoubaoServiceError(
                f"豆包服务返回异常状态（HTTP {exc.status_code}）。"
            ) from exc
        except Exception as exc:
            raise DoubaoServiceError("豆包调用失败，请稍后重试。") from exc

    def _record_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.diagnostics.input_tokens += input_tokens
        self.diagnostics.output_tokens += output_tokens


def _response_content(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise StructuredOutputError("豆包响应缺少正文内容。") from exc
    if not isinstance(content, str) or not content.strip():
        raise StructuredOutputError("豆包响应缺少正文内容。")
    return content.strip()


def _response_usage(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    return max(int(input_tokens or 0), 0), max(int(output_tokens or 0), 0)


def _response_model(response: Any, fallback: str) -> str:
    value = getattr(response, "model", None)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise StructuredOutputError("豆包必须返回一个 JSON 对象。")
    return parsed
