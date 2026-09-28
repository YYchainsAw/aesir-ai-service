"""LLM 调用熔断器（SDD T084 / FR-041）。

当 LLM 连续失败达到阈值时，熔断器进入 OPEN 状态，在恢复窗口内直接拒绝新的
LLM 调用，避免把外部故障拖垮本地服务。OPEN 状态经过恢复时间后进入 HALF_OPEN，
下一次调用若成功则关闭，若失败则重新打开。

所有 LLM 调用统一通过 ``create_llm_client`` 返回的包装客户端接入熔断，因此：
- 陪伴对话、战术意图解析、v0.1 命令解析三条链路共享同一熔断状态
- 熔断触发后，各链路的既有 fallback（规则/mock）自动生效，不阻塞游戏流程
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

from app.services.llm.client import LLMClient, LLMClientError


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """基于连续失败计数与时间窗口的熔断器。

    线程安全：内部状态变更受锁保护，可在多线程 Web 服务中使用。
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_seconds: float = 60.0,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if recovery_seconds <= 0:
            raise ValueError("recovery_seconds must be positive")

        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def can_execute(self) -> bool:
        """当前是否允许执行被保护调用。"""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                return True
            # OPEN 状态：检查是否已过恢复时间
            if self._opened_at is None:
                raise RuntimeError("circuit breaker invariant broken: opened_at is None in OPEN state")
            if time.monotonic() - self._opened_at >= self._recovery_seconds:
                self._state = CircuitState.HALF_OPEN
                return True
            return False

    def record_success(self) -> None:
        """调用成功后调用：失败计数清零，状态回到 CLOSED。"""
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    def record_failure(self) -> None:
        """调用失败后调用：增加失败计数，达到阈值则打开熔断。"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                # 半开状态再次失败：立即重新打开
                self._open()
                return

            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._open()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()

    def reset(self) -> None:
        """测试/调试用：重置为 CLOSED。"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None


class CircuitBreakerLLMClient:
    """包装任意 LLMClient，为其增加熔断能力。"""

    def __init__(self, client: LLMClient, breaker: CircuitBreaker) -> None:
        self._client = client
        self._breaker = breaker

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self._breaker.can_execute():
            raise LLMClientError("LLM circuit breaker is open; fallback to rule/mock path.")
        try:
            result = self._client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
            )
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return result

    def stream_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        if not self._breaker.can_execute():
            raise LLMClientError("LLM circuit breaker is open; fallback to rule/mock path.")

        # 流式结果无法简单判断「整轮」成功/失败，只能在迭代器层面捕获异常。
        # 约定：只要流式调用启动成功（迭代器被消费且未抛异常）即记成功；
        # 消费过程中抛异常记失败。这与非流式语义一致。
        try:
            yield from self._client.stream_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
            )
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
