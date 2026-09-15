"""厂商无关的 OpenAI 兼容 LLM 客户端。

业务层只依赖 ``LLMClient`` 协议，因此可替换为其他云端或本地 Provider，
而不用修改陪伴对话和战术解析逻辑。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class LLMClientError(RuntimeError):
    """LLM 配置、网络或响应格式出现问题时抛出。"""


class LLMClient(Protocol):
    """所有 LLM Provider Adapter 的共同接口。"""

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """生成并解析一个 JSON 对象。"""

    def stream_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """流式生成，逐段产出原始文本增量（不做 JSON 解析）。"""


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float = 15.0


class OpenAICompatibleLLMClient:
    """调用 ``/chat/completions`` 的最小 OpenAI 兼容实现。"""

    def __init__(
        self,
        settings: OpenAICompatibleSettings,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not settings.api_key or not settings.model or not settings.base_url:
            raise LLMClientError("LLM_API_KEY, LLM_MODEL and LLM_BASE_URL must be configured.")

        self._settings = settings
        try:
            self._http_client = http_client or httpx.Client(timeout=settings.timeout_seconds)
        except (ImportError, ValueError) as error:
            raise LLMClientError("Unable to initialize the configured LLM HTTP client.") from error

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        try:
            response = self._http_client.post(
                f"{self._settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            response_body = response.json()
            content = response_body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMClientError("LLM request failed or returned an invalid response.") from error

        if not isinstance(content, str):
            raise LLMClientError("LLM response content must be a JSON string.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise LLMClientError("LLM response is not valid JSON.") from error

        if not isinstance(parsed, dict):
            raise LLMClientError("LLM response root must be a JSON object.")
        return parsed

    def stream_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """流式调用 ``/chat/completions``，逐段产出 ``delta.content`` 文本增量。

        客户端只做原始增量透传（DeepSeek 的 ``reasoning_content`` 一律忽略），
        JSON 解析与校验留给业务层，与非流式 ``generate_json`` 的分工一致。
        """
        payload = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": True,
        }

        try:
            with self._http_client.stream(
                "POST",
                f"{self._settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.api_key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                yield from self._iter_sse_content(response)
        except LLMClientError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMClientError("LLM stream request failed or returned an invalid response.") from error

    def _iter_sse_content(self, response: httpx.Response) -> Iterator[str]:
        """解析 SSE 行，产出每个 data 块里的 ``choices[0].delta.content``。"""
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
                content = chunk["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                raise LLMClientError("LLM stream chunk is not a valid completion delta.") from error
            if isinstance(content, str) and content:
                yield content
