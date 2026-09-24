"""从运行时配置创建共享 LLM 客户端（含熔断包装）。"""

from app.config import get_settings
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitBreakerLLMClient
from app.services.llm.client import LLMClient, OpenAICompatibleLLMClient, OpenAICompatibleSettings

# 进程内共享的 LLM 熔断器：所有通过 factory 创建的客户端共用同一状态。
_LLm_CIRCUIT_BREAKER = CircuitBreaker()


def create_llm_client() -> LLMClient:
    """创建由环境变量配置的 OpenAI 兼容客户端，并包装熔断器。

    测试或特殊场景可直接构造 ``OpenAICompatibleLLMClient`` 并注入业务层，
    绕过熔断；生产链路统一走本工厂，共享熔断状态。
    """
    settings = get_settings()
    base_client = OpenAICompatibleLLMClient(
        OpenAICompatibleSettings(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
    _LLm_CIRCUIT_BREAKER._failure_threshold = settings.llm_circuit_failure_threshold
    _LLm_CIRCUIT_BREAKER._recovery_seconds = settings.llm_circuit_recovery_seconds
    return CircuitBreakerLLMClient(base_client, _LLm_CIRCUIT_BREAKER)


def get_llm_circuit_breaker() -> CircuitBreaker:
    """返回共享熔断器实例（调试/测试/控制台用）。"""
    return _LLm_CIRCUIT_BREAKER
