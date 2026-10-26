"""影子模式双写比对（阶段 0c）。

``ShadowScheduler`` 同时委托一个 ``InMemoryScheduler`` 与一个
``RedisScheduler``，每次调度操作后比对：

1. **决策返回值**（``try_acquire`` / ``try_enqueue`` / ``owns_running_slot``）
   是否一致；
2. **状态快照**（running / waiting / sessions）在编码域上是否一致。

任一不一致即抛 ``ShadowMismatchError``——这意味着两个后端对「谁先跑、
并发几个、同会话是否串行」给出了不同判定，Redis 后端的语义移植有 bug。

边界：
- 影子模式**只用于测试/验证**，不进生产路径。生产用 ``_build_scheduler``
  单选一个后端（见 ``requests.py``）。
- ``wait()`` 在影子模式下退化为 sleep（与 Redis 后端一致），不依赖内存
  ``Condition.wait`` 的唤醒时序——我们验证的是决策一致性，不是唤醒精度。
- 两个后端的租约 TTL（30s）在测试期间不会过期；如果测试拉长到分钟级，
  需要注入更短的 clock 或租约。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import time

from app.scoped.redis_scheduling import _enc
from app.scoped.scheduling import InMemoryScheduler, _Request


class ShadowMismatchError(AssertionError):
    """两个后端的调度决策或状态不一致。"""


class ShadowScheduler:
    """委托内存 + Redis 两个后端，逐操作比对一致性。

    Parameters
    ----------
    memory:
        ``InMemoryScheduler`` 实例（权威语义基线）。
    redis:
        ``RedisScheduler`` 实例（被验证的移植实现）。
    """

    def __init__(self, memory: InMemoryScheduler, redis) -> None:
        self.memory = memory
        self.redis = redis

    # -- SchedulerBackend -------------------------------------------------
    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self.memory.exclusive(), self.redis.exclusive():
            yield

    def try_acquire(self, key: tuple, entry: _Request) -> bool:
        mem = self.memory.try_acquire(key, entry)
        red = self.redis.try_acquire(key, entry)
        if mem != red:
            # 回滚已占的那个，避免泄漏槽/会话锁。
            if red:
                self.redis.release(key, entry)
            if mem:
                self.memory.release(key, entry)
            raise ShadowMismatchError(
                f"try_acquire mismatch: memory={mem} redis={red} key={key}"
            )
        return mem

    def start(self, key: tuple, entry: _Request) -> None:
        self.memory.start(key, entry)
        self.redis.start(key, entry)
        self._check_state(key)

    def owns_running_slot(self, key: tuple, entry: _Request) -> bool:
        mem = self.memory.owns_running_slot(key, entry)
        red = self.redis.owns_running_slot(key, entry)
        if mem != red:
            raise ShadowMismatchError(
                f"owns_running_slot mismatch: memory={mem} redis={red} key={key}"
            )
        return mem

    def try_enqueue(self, key: tuple, entry: _Request) -> bool:
        mem = self.memory.try_enqueue(key, entry)
        red = self.redis.try_enqueue(key, entry)
        if mem != red:
            if red:
                self.redis.dequeue(key)
            if mem:
                self.memory.dequeue(key)
            raise ShadowMismatchError(
                f"try_enqueue mismatch: memory={mem} redis={red} key={key}"
            )
        return mem

    def dequeue(self, key: tuple) -> None:
        self.memory.dequeue(key)
        self.redis.dequeue(key)
        self._check_state(key)

    def release(self, key: tuple, entry: _Request) -> None:
        self.memory.release(key, entry)
        self.redis.release(key, entry)
        self._check_state(key)

    def wait(self, timeout: float) -> None:
        # 影子模式不依赖内存 Condition 的唤醒时序；与 Redis 后端一致——
        # 释放两把进程内锁，sleep，再拿。协调器每 50ms 复检一次槽位。
        self.memory.condition.release()
        self.redis._lock.release()
        try:
            time.sleep(timeout)
        finally:
            self.redis._lock.acquire()
            self.memory.condition.acquire()

    def notify_all(self) -> None:
        self.memory.notify_all()
        self.redis.notify_all()

    # -- 状态快照比对 -----------------------------------------------------
    def _check_state(self, ctx: tuple) -> None:
        """比对两个后端的 running / waiting / sessions（编码域）。

        在 ``start`` / ``dequeue`` / ``release`` 后调用。``ctx`` 仅用于
        错误信息定位。
        """
        mem = self._memory_snapshot()
        red = self._redis_snapshot()
        if mem != red:
            raise ShadowMismatchError(
                f"state mismatch after ctx={ctx}:\n"
                f"  memory: running={sorted(mem['running'])} "
                f"waiting={mem['waiting']} sessions={sorted(mem['sessions'])}\n"
                f"  redis:  running={sorted(red['running'])} "
                f"waiting={red['waiting']} sessions={sorted(red['sessions'])}"
            )

    def _memory_snapshot(self) -> dict:
        return {
            "running": {_enc(k) for k in self.memory.running.keys()},
            "waiting": [_enc(k) for k in self.memory.waiting.keys()],
            "sessions": {_enc(s) for s in self.memory.sessions},
        }

    def _redis_snapshot(self) -> dict:
        client = self.redis.client
        prefix = self.redis._prefix
        running = {_enc(k) for k in self.redis._owned}
        waiting = [w for w in client.lrange(f"{prefix}:waiting", 0, -1)]
        sessions = set()
        for key in client.scan_iter(f"{prefix}:sess:*"):
            sessions.add(key[len(f"{prefix}:sess:"):])
        return {"running": running, "waiting": waiting, "sessions": sessions}
