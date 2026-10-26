"""易失请求调度原语：并发槽、会话串行、排队深度、唤醒。

本模块是阶段 0（请求协调器外置）的 0a 产物：把 ``RequestCoordinator`` 内部
直接操作的四个调度态（``_condition`` / ``_running`` / ``_waiting`` / ``_sessions``）
收拢到一个可替换的后端后面。

0a 阶段只提供 ``InMemoryScheduler``，它**逐字节复用**原有的单把
``threading.Condition`` 与同一套锁/wait/notify 语义——也就是说行为与重构前
完全等价，既有并发测试（依赖 ``wait_for(state == "queued")`` 这类时序）不会
引入 flaky。0b 阶段将新增 ``RedisScheduler`` 实现同一 Protocol，届时
``RequestCoordinator`` 的控制流（FIFO 循环、``_check`` 边界、``final_commit``）
无需改动，仅替换后端。

边界：
- 调度态（本模块）只解决"谁先跑、并发几个、同会话是否串行"。
- 请求注册表（``_entries``）、结果/错误、取消 tombstone 仍留在 ``RequestCoordinator``；
  SQL 模式下它们的权威版本由 ``app.persistence.journal`` 承担，不在此模块。
- JSON 模式 + 多 worker 不受支持：幂等在内存，多 worker 必然双执行，
  这一启动期拒绝由配置层负责（见 ``app.config``）。
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
from typing import Any, Protocol

from app.scoped.context import RequestScope


@dataclass
class _Request:
    """一条逻辑请求的易失运行时状态。

    字段与重构前 ``RequestCoordinator`` 内部 ``_Request`` 完全一致；挪到此处
    是因为它本质是调度条目，``RequestCoordinator`` 与 ``SchedulerBackend``
    都需要访问。
    """

    scope: RequestScope
    operation: str
    request_id: str
    created_at: float
    serial: bool = True
    budget: Any = None  # TimingBudget | None
    validate: Callable[[], Any] | None = None
    state: str = "queued"
    reason_code: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    upstream_attempts: int = 0
    cancel_requested: bool = False
    commit_started: bool = False
    inflight: bool = True
    result: Any = None
    error: Any = None  # ScopeError | None
    lock: Any = field(default_factory=threading.RLock)


class SchedulerBackend(Protocol):
    """易失调度后端的接口。

    所有方法的调用约定：
    - ``exclusive()`` 必须先进入，其后的 ``try_acquire`` / ``start`` /
      ``try_enqueue`` / ``dequeue`` / ``release`` 都在该临界区内调用。
    - ``wait`` 会释放锁并阻塞，被 ``notify_all`` 唤醒后重新拿锁。
    """

    def exclusive(self) -> Iterator[None]:
        """进入全局调度临界区。"""
        ...

    def try_acquire(self, key: tuple, entry: _Request) -> bool:
        """原子判定并占一个全局生成槽。

        仅当同时满足才占槽并返回 True：
        1. 当前运行数 < max_generation_concurrency；
        2. ``entry.scope.session_key`` 不在运行会话集；
        3. 在排队队列里，当前会话没有更老的、会话空闲的请求排在前面
           （保留全局到达顺序，但跳过被自己会话挡住的老请求）。

        否则返回 False，不修改任何状态。
        """
        ...

    def start(self, key: tuple, entry: _Request) -> None:
        """占槽：把 entry 从排队集移除、加入运行集、登记运行会话。"""
        ...

    def owns_running_slot(self, key: tuple, entry: _Request) -> bool:
        """该进程当前是否为 ``key`` 持有运行槽（owner 重入判定）。

        取代旧实现里 ``scheduler.running.get(key) is entry`` 的对象身份比较——
        那是内存专有的；Redis 后端无法存放 Python 对象，改用「本进程是否持槽」
        的本地标记表达同一语义。
        """
        ...

    def try_enqueue(self, key: tuple, entry: _Request) -> bool:
        """深度检查后入队。

        总排队数 >= queue_limit 或该会话排队数 >= session_queue_limit 时
        返回 False；否则入队并返回 True。
        """
        ...

    def dequeue(self, key: tuple) -> None:
        """把 key 从排队集移除（取消/完成时调用）。"""
        ...

    def release(self, key: tuple, entry: _Request) -> None:
        """释放 entry 占用的槽，并清掉其会话登记。"""
        ...

    def wait(self, timeout: float) -> None:
        """在 ``exclusive()`` 内调用：释放锁、阻塞至 ``notify_all`` 或超时。"""
        ...

    def notify_all(self) -> None:
        """唤醒所有在 ``wait`` 上阻塞的协作者。"""
        ...


class InMemoryScheduler:
    """单进程调度后端。

    逐字节保留重构前的语义：一把 ``threading.Condition(RLock)`` 同时保护
    运行集、排队集、会话集。0b 的 Redis 实现将用分布式锁/Lua/Pub-Sub 替代，
    但 ``RequestCoordinator`` 通过本接口与之交互的方式不变。
    """

    def __init__(self, *, max_generation_concurrency: int, queue_limit: int,
                 session_queue_limit: int, clock: Callable[[], float]) -> None:
        self.max_generation_concurrency = max_generation_concurrency
        self.queue_limit = queue_limit
        self.session_queue_limit = session_queue_limit
        self.clock = clock
        # 这把 Condition 就是重构前 RequestCoordinator._condition 的同一把锁语义。
        self.condition = threading.Condition(threading.RLock())
        self.waiting: "OrderedDict[tuple, _Request]" = OrderedDict()
        self.running: dict[tuple, _Request] = {}
        self.sessions: set[tuple] = set()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self.condition:
            yield

    def try_acquire(self, key: tuple, entry: _Request) -> bool:
        if len(self.running) >= self.max_generation_concurrency:
            return False
        if entry.scope.session_key in self.sessions:
            return False
        # 全局到达顺序：跳过被自己会话挡住的老请求，保留该会话的 FIFO。
        for waiting_key, waiting in self.waiting.items():
            if waiting.scope.session_key not in self.sessions:
                return waiting_key == key
        return True

    def start(self, key: tuple, entry: _Request) -> None:
        if self.waiting.get(key) is entry:
            del self.waiting[key]
        self.running[key] = entry
        self.sessions.add(entry.scope.session_key)

    def owns_running_slot(self, key: tuple, entry: _Request) -> bool:
        return self.running.get(key) is entry

    def try_enqueue(self, key: tuple, entry: _Request) -> bool:
        if len(self.waiting) >= self.queue_limit:
            return False
        session_waiting = sum(
            1 for waiting in self.waiting.values()
            if waiting.scope.session_key == entry.scope.session_key
        )
        if session_waiting >= self.session_queue_limit:
            return False
        self.waiting[key] = entry
        return True

    def dequeue(self, key: tuple) -> None:
        self.waiting.pop(key, None)

    def release(self, key: tuple, entry: _Request) -> None:
        self.waiting.pop(key, None)
        self.running.pop(key, None)
        self.sessions.discard(entry.scope.session_key)

    def wait(self, timeout: float) -> None:
        self.condition.wait(timeout=timeout)

    def notify_all(self) -> None:
        self.condition.notify_all()
