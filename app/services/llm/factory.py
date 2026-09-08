"""从运行时配置创建共享 LLM 客户端。"""

from app.config import get_settings
from app.services.llm.client import OpenAICompatibleLLMClient, OpenAICompatibleSettings


def create_llm_client() -> OpenAICompatibleLLMClient:
    """创建由环境变量配置的 OpenAI 兼容客户端。"""
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        OpenAICompatibleSettings(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
