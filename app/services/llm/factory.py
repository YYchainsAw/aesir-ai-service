"""从运行时配置创建共享 LLM 客户端。"""

from app.config import get_llm_settings
from app.services.llm.client import OpenAICompatibleLLMClient, OpenAICompatibleSettings


def create_llm_client() -> OpenAICompatibleLLMClient:
    """创建由环境变量配置的 OpenAI 兼容客户端。"""
    settings = get_llm_settings()
    return OpenAICompatibleLLMClient(
        OpenAICompatibleSettings(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
        )
    )
