"""LLM 熔断器测试（SDD T084 / FR-041）。

覆盖：阈值触发、OPEN 状态拒绝、恢复窗口、HALF_OPEN 成功关闭/失败重开、
非流式/流式调用均影响熔断状态、工厂集成。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.services.llm.circuit_breaker import CircuitBreaker, CircuitBreakerLLMClient, CircuitState
from app.services.llm.client import LLMClientError


class _FlakyLLMClient:
    """按调用次数决定成功或失败的测试替身。"""

    def __init__(self, fail_until_call: int | None = None) -> None:
        self.fail_until_call = fail_until_call
        self.calls = 0
        self.last_system_prompt = ""
        self.last_user_prompt = ""

    def generate_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        self.calls += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        if self.fail_until_call is not None and self.calls <= self.fail_until_call:
            raise LLMClientError(f" simulated failure #{self.calls}")
        return {"reply_text": "ok"}

    def stream_completion(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Iterator[str]:
        self.calls += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        if self.fail_until_call is not None and self.calls <= self.fail_until_call:
            raise LLMClientError(f" simulated stream failure #{self.calls}")
        yield "ok"


# ---------------------------------------------------------------------------
# CircuitBreaker 单元测试
# ---------------------------------------------------------------------------

def test_breaker_starts_closed() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=1.0)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True


def test_breaker_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False


def test_breaker_resets_after_recovery(monkeypatch) -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=10.0)
    # 固定时间为 100.0，触发失败后 opened_at = 100.0
    monkeypatch.setattr(
        "app.services.llm.circuit_breaker.time.monotonic",
        lambda: 100.0,
    )
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False

    # 时间跳到 110.0，刚好过恢复窗口
    monkeypatch.setattr(
        "app.services.llm.circuit_breaker.time.monotonic",
        lambda: 110.0,
    )
    assert breaker.can_execute() is True
    assert breaker.state == CircuitState.HALF_OPEN


def test_half_open_success_closes_breaker(monkeypatch) -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=10.0)
    monkeypatch.setattr(
        "app.services.llm.circuit_breaker.time.monotonic",
        lambda: 0.0,
    )
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    monkeypatch.setattr(
        "app.services.llm.circuit_breaker.time.monotonic",
        lambda: 10.0,
    )
    assert breaker.can_execute() is True  # HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_half_open_failure_reopens_breaker(monkeypatch) -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=10.0)
    monkeypatch.setattr(
        "app.services.llm.circuit_breaker.time.monotonic",
        lambda: 0.0,
    )
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    monkeypatch.setattr(
        "app.services.llm.circuit_breaker.time.monotonic",
        lambda: 10.0,
    )
    assert breaker.can_execute() is True  # HALF_OPEN
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def test_success_resets_failure_count() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    breaker.record_failure()
    breaker.record_failure()
    # 之前成功重置了计数，现在只有 2 次失败，不会打开
    assert breaker.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# CircuitBreakerLLMClient 包装测试
# ---------------------------------------------------------------------------

def test_wrapped_client_passes_success() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60.0)
    client = CircuitBreakerLLMClient(_FlakyLLMClient(), breaker)

    result = client.generate_json(system_prompt="s", user_prompt="u")
    assert result == {"reply_text": "ok"}
    assert breaker.state == CircuitState.CLOSED


def test_wrapped_client_counts_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60.0)
    base = _FlakyLLMClient(fail_until_call=2)
    client = CircuitBreakerLLMClient(base, breaker)

    with pytest.raises(LLMClientError):
        client.generate_json(system_prompt="s", user_prompt="u")
    assert breaker.state == CircuitState.CLOSED

    with pytest.raises(LLMClientError):
        client.generate_json(system_prompt="s", user_prompt="u")
    assert breaker.state == CircuitState.OPEN

    # OPEN 后直接拒绝，不再调用 base client
    base.calls = 0
    with pytest.raises(LLMClientError, match="circuit breaker is open"):
        client.generate_json(system_prompt="s", user_prompt="u")
    assert base.calls == 0


def test_stream_completion_counts_success_and_failure() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60.0)
    ok_client = CircuitBreakerLLMClient(_FlakyLLMClient(), breaker)

    chunks = list(ok_client.stream_completion(system_prompt="s", user_prompt="u"))
    assert chunks == ["ok"]
    assert breaker.state == CircuitState.CLOSED

    failing_client = CircuitBreakerLLMClient(_FlakyLLMClient(fail_until_call=1), breaker)
    with pytest.raises(LLMClientError):
        list(failing_client.stream_completion(system_prompt="s", user_prompt="u"))
    assert breaker.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# 工厂集成
# ---------------------------------------------------------------------------

def test_open_state_without_opened_at_raises_instead_of_assert() -> None:
    """CODE-05：生产路径 assert 改为显式 raise，避免 `python -O` 剥离后保护失效。"""
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=10.0)
    # 手动破坏内部不变量：状态为 OPEN 但 opened_at 为 None
    breaker._state = CircuitState.OPEN
    breaker._opened_at = None
    with pytest.raises(RuntimeError, match="circuit breaker invariant broken"):
        breaker.can_execute()


def test_factory_creates_circuit_breaker_wrapped_client(monkeypatch) -> None:
    """create_llm_client returns a CircuitBreakerLLMClient-wrapped client."""
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("AESIR_LLM_CIRCUIT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("AESIR_LLM_CIRCUIT_RECOVERY_SECONDS", "30")

    from app.services.llm.factory import create_llm_client, get_llm_circuit_breaker

    breaker = get_llm_circuit_breaker()
    breaker.reset()
    client = create_llm_client()

    assert isinstance(client, CircuitBreakerLLMClient)
    assert breaker._failure_threshold == 3
    assert breaker._recovery_seconds == 30.0
