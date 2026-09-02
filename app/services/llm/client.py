"""厂商无关的 OpenAI 兼容 LLM 客户端。

业务层只依赖 ``LLMClient`` 协议，因此可替换为其他云端或本地 Provider，
而不用修改陪伴对话和战术解析逻辑。
"""

from __future__ import annotations

import json
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
        self._http_client = http_client or httpx.Client(timeout=settings.timeout_seconds)

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
