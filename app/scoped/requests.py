"""Bounded request lifecycles; generation runs without runtime/NPC locks.

Lock order for callers remains runtime -> NPC -> request token.  No callback
or timing check runs while the scheduler condition is held.

阶段 0a：易失调度态（并发槽/会话串行/排队深度/唤醒）已抽到
``app.scoped.scheduling`` 的 ``SchedulerBackend`` 后面；本模块只保留请求
注册表（``_entries``）与控制流。默认后端 ``InMemoryScheduler`` 逐字节保留
原单进程语义，既有并发测试不因此改变时序。
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import threading
import time
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.scoped.context import RequestScope
from app.scoped.errors import ScopeError
from app.scoped.idempotency import NotStartedError
from app.scoped.scheduling import InMemoryScheduler, SchedulerBackend, _Request
from app.scoped.timing import TimingBudget, current_budget, use_budget


_active: ContextVar[_Request | None] = ContextVar("scoped_active_request", default=None)


def _cancelled(entry: _Request) -> None:
    # Caller may already hold this RLock in final_commit/storage commit_guard.
    with entry.lock:
        if entry.cancel_requested:
            raise ScopeError(409, "REQUEST_CANCELLED", "The logical request was cancelled.", entry.request_id)


def has_active_request() -> bool:
    """Whether this call belongs to a coordinated request (legacy stays False)."""
    return _active.get() is not None


def check_current(scope: RequestScope | None = None) -> None:
    """Only check the active cancellation token; never acquire runtime/NPC locks."""
    entry = _active.get()
    if entry is not None:
        _cancelled(entry)


def _check(entry: _Request) -> None:
    _cancelled(entry)
    if entry.budget is not None:
        entry.budget.check()
    if entry.validate is not None:
        entry.validate()
    _cancelled(entry)
    if entry.budget is not None:
        entry.budget.check()


@contextmanager
def final_commit() -> Iterator[None]:
    """Linearize final effects with cancellation under the caller's outer locks.

    The marker survives context exit: cancellation cannot revoke committed facts,
    and any later failure has an unknown outcome. Legacy calls have no token.
    """
    entry = _active.get()
    if entry is None:
        yield
        return
    with entry.lock:
        _cancelled(entry)
        # Full binding/epoch validation belongs to the outer commit_guard. Do
        # not acquire runtime/NPC locks here while holding the token lock.
        if entry.budget is not None:
            entry.budget.check()
        entry.commit_started = True
        yield


@contextmanager
def upstream_attempt() -> Iterator[str]:
    """Identify and count an actual upstream attempt, checking both boundaries."""
    entry = _active.get()
    attempt_id = str(uuid4())
    if entry is None:
        yield attempt_id
        return
    _check(entry)
    with entry.lock:
        _cancelled(entry)
        entry.upstream_attempts += 1
    try:
        yield attempt_id
    finally:
        _check(entry)


def timeout_for_upstream(default_seconds: float) -> float:
    """Clamp a provider timeout to the request's remaining monotonic budget."""
    entry = _active.get()
    if entry is None:
        return default_seconds
    _check(entry)
    if entry.budget is None:
        return default_seconds
    remaining = entry.budget.remaining_ms / 1000
    if remaining <= 0:
        raise ScopeError(409, "REQUEST_EXPIRED", "The logical request has expired.", entry.request_id)
    return min(default_seconds, remaining)


class RequestCoordinator:
    def __init__(self, *, max_generation_concurrency: int = 2, queue_limit: int = 16,
                 session_queue_limit: int = 4, max_entries: int = 1024,
                 retention_seconds: float = 300,
                 clock: Callable[[], float] = time.monotonic,
                 scheduler: SchedulerBackend | None = None,
                 status_fallback: Callable[[RequestScope, str, str], dict | None] | None = None) -> None:
        if (max_generation_concurrency < 1 or queue_limit < 1 or session_queue_limit < 1
                or max_entries < 1 or retention_seconds <= 0):
            raise ValueError("Request coordination limits must be positive.")
        self.max_generation_concurrency = max_generation_concurrency
        self.queue_limit = queue_limit
        self.session_queue_limit = session_queue_limit
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self.clock = clock
        # 请求注册表（含完成态保留）。SQL 模式下其权威版本由 journal 承担。
        self._entries: OrderedDict[tuple[str, ...], _Request] = OrderedDict()
        # 阶段 1：status 内存 miss 时的跨进程 fallback（仅 SQL 模式注入）。
        # 返回 None 表示 journal 也没有该请求 → 真正 404。
        self._status_fallback = status_fallback
        # 易失调度后端。默认 InMemoryScheduler 逐字节保留原单进程语义；
        # 0b 将注入 RedisScheduler。
        self.scheduler: SchedulerBackend = scheduler or InMemoryScheduler(
            max_generation_concurrency=max_generation_concurrency,
            queue_limit=queue_limit,
            session_queue_limit=session_queue_limit,
            clock=clock,
        )

    @staticmethod
    def _key(scope: RequestScope, operation: str, request_id) -> tuple[str, ...]:
        return (*scope.key, operation, str(request_id))

    def _prune(self) -> None:
        # Called under the condition only. inflight remains true even after
        # accepted cancellation, until the original action has actually exited.
        now = self.clock()
        expired = [key for key, value in self._entries.items()
                   if not value.inflight and value.state != "unknown" and value.finished_at is not None
                   and value.finished_at + self.retention_seconds <= now]
        for key in expired:
            del self._entries[key]

    @staticmethod
    def _same_scope(entry: _Request, scope: RequestScope) -> None:
        if entry.scope != scope:
            raise ScopeError(409, "REQUEST_ID_CONFLICT", "The logical ID is bound to another request scope.", entry.request_id)

    @staticmethod
    def _capacity(request_id) -> NotStartedError:
        return NotStartedError(503, "REQUEST_QUEUE_FULL", "No request coordination capacity is available.", request_id)

    def _record(self, entry: _Request) -> dict:
        with entry.lock:
            now = self.clock()
            # A cancelled provider may still consume processing time until its
            # owner exits; do not freeze that running duration at cancel arrival.
            end = now if entry.inflight and entry.started_at is not None else (
                entry.finished_at if entry.finished_at is not None else now)
            start = entry.started_at if entry.started_at is not None else end
            return {
                "target_request_id": entry.request_id,
                "operation": entry.operation,
                "state": entry.state,
                "reason_code": entry.reason_code,
                "queue_ms": max(0, int((start - entry.created_at) * 1000)),
                "processing_ms": max(0, int((end - start) * 1000)),
                "total_ms": max(0, int((end - entry.created_at) * 1000)),
                "upstream_attempts": entry.upstream_attempts,
                "cancel_requested": entry.cancel_requested,
            }

    def status(self, scope, operation, target_request_id) -> dict:
        key = self._key(scope, operation, target_request_id)
        with self.scheduler.exclusive():
            self._prune()
            entry = self._entries.get(key)
        if entry is None:
            # 阶段 1：多 worker 非粘性部署下，请求可能在别的 worker 完成。
            # 内存 miss 时 fallback 到 journal（仅 SQL 模式注入了回调）。
            if self._status_fallback is not None:
                record = self._status_fallback(scope, operation, str(target_request_id))
                if record is not None:
                    return record
            raise ScopeError(404, "REQUEST_UNKNOWN", "The logical request is not retained.", target_request_id)
        self._same_scope(entry, scope)
        return self._record(entry)

    def cancel(self, scope, operation, target_request_id, reason_code="USER_CANCELLED") -> dict:
        key = self._key(scope, operation, target_request_id)
        with self.scheduler.exclusive():
            self._prune()
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self.max_entries:
                    raise self._capacity(target_request_id)
                now = self.clock()
                # Publish a complete tombstone atomically. A concurrent execute
                # must never observe an unowned queued entry as a cached None.
                entry = _Request(scope, operation, str(target_request_id), now,
                                 inflight=False, state="cancelled", reason_code=reason_code,
                                 cancel_requested=True, finished_at=now)
                self._entries[key] = entry
        self._same_scope(entry, scope)
        with entry.lock:
            if not entry.commit_started and entry.state in {"queued", "running", "cancelled"}:
                entry.cancel_requested = True
                entry.state, entry.reason_code = "cancelled", reason_code
                if entry.finished_at is None:
                    entry.finished_at = self.clock()
        # Never hold the token while taking the scheduler condition.
        with self.scheduler.exclusive():
            if entry.cancel_requested:
                self.scheduler.dequeue(key)
            self.scheduler.notify_all()
        return self._record(entry)

    def _replay(self, entry) -> Any:
        _check(entry)
        with entry.lock:
            if entry.state == "unknown":
                raise ScopeError(503, "REQUEST_OUTCOME_UNKNOWN", "Do not automatically execute this request again.", entry.request_id)
            if entry.error is not None:
                raise ScopeError(entry.error.status_code, entry.error.code, entry.error.message, entry.request_id)
            return deepcopy(entry.result)

    def execute(self, scope, operation, request_id, action, *, serial=True,
                budget=None, validate=None) -> Any:
        budget = budget if budget is not None else current_budget()
        probe = _Request(scope, operation, str(request_id), self.clock(), budget=budget, validate=validate)
        _check(probe)
        key = self._key(scope, operation, request_id)
        owner = False
        with self.scheduler.exclusive():
            self._prune()
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self.max_entries:
                    raise self._capacity(request_id)
                entry = probe
                entry.serial = serial
                # An immediately eligible request consumes no waiting capacity.
                immediate = (not serial or self.scheduler.try_acquire(key, entry))
                if serial and not immediate:
                    # 深度检查 + 入队由后端原子完成；失败即容量拒绝。
                    if not self.scheduler.try_enqueue(key, entry):
                        raise self._capacity(request_id)
                self._entries[key] = entry
                owner = True
                if serial and immediate:
                    self.scheduler.start(key, entry)
            self._same_scope(entry, scope)
        if not owner:
            if entry.budget is not None and budget is not None and entry.budget is not budget:
                entry.budget.retry(budget.input)
            while True:
                _check(probe)
                _cancelled(entry)
                with self.scheduler.exclusive():
                    if not entry.inflight:
                        break
                    self.scheduler.wait(0.05)
            return self._replay(entry)

        active_token = _active.set(entry)
        try:
            with use_budget(entry.budget):
                while serial:
                    _check(entry)
                    with self.scheduler.exclusive():
                        if self.scheduler.owns_running_slot(key, entry):
                            break
                        if self.scheduler.try_acquire(key, entry):
                            self.scheduler.start(key, entry)
                            break
                        self.scheduler.wait(0.05)
                with entry.lock:
                    _cancelled(entry)
                    entry.started_at, entry.state = self.clock(), "running"
                _check(entry)
                result = action()
                _check(entry)
                cached = deepcopy(result)
                with entry.lock:
                    _cancelled(entry)
                    entry.result = cached
                    entry.state, entry.finished_at = "completed", self.clock()
                return result
        except Exception as error:
            with entry.lock:
                if entry.commit_started:
                    entry.state, entry.reason_code = "unknown", "REQUEST_OUTCOME_UNKNOWN"
                    terminal_error = ScopeError(503, "REQUEST_OUTCOME_UNKNOWN", "Request outcome is uncertain; do not automatically retry.", request_id)
                elif entry.cancel_requested:
                    entry.state = "cancelled"
                    terminal_error = ScopeError(409, "REQUEST_CANCELLED", "The logical request was cancelled.", request_id)
                elif isinstance(error, ScopeError):
                    entry.state = "expired" if error.code in {"REQUEST_EXPIRED", "SNAPSHOT_EXPIRED"} else "failed"
                    entry.reason_code, terminal_error = error.code, error
                else:
                    entry.state, entry.reason_code = "failed", "REQUEST_FAILED"
                    terminal_error = ScopeError(503, "REQUEST_FAILED", "Request processing failed.", request_id)
                entry.error, entry.finished_at = terminal_error, self.clock()
            if terminal_error is error:
                raise
            raise terminal_error from error
        finally:
            _active.reset(active_token)
            # No token is held here; wake cancelled, duplicate and FIFO waiters.
            with self.scheduler.exclusive():
                entry.inflight = False
                self.scheduler.release(key, entry)
                self.scheduler.notify_all()

    def failure_after_operation(self, scope, operation, request_id, error: Exception) -> Exception:
        """Preserve uncertainty if an outer owner's final checks fail after commit.

        Only used for the owner, never for a later replay whose validity expired.
        The idempotency store invokes this without holding its condition lock.
        """
        with self.scheduler.exclusive():
            entry = self._entries.get(self._key(scope, operation, request_id))
        if entry is None or entry.scope != scope:
            return error
        with entry.lock:
            if not entry.commit_started:
                return error
            terminal = ScopeError(
                503, "REQUEST_OUTCOME_UNKNOWN",
                "Committed effects may exist; do not automatically retry.", request_id,
            )
            entry.state, entry.reason_code = "unknown", terminal.code
            entry.error, entry.finished_at = terminal, self.clock()
            return terminal

    def clear(self) -> None:
        # Live actions must observe cancellation before disappearing. A request
        # already committing remains retained until its original owner exits.
        with self.scheduler.exclusive():
            entries = list(self._entries.items())
        for key, entry in entries:
            with entry.lock:
                if entry.inflight and not entry.commit_started:
                    entry.cancel_requested, entry.state = True, "cancelled"
                    entry.reason_code = "REQUEST_COORDINATOR_CLEARED"
            with self.scheduler.exclusive():
                if self._entries.get(key) is entry and not entry.inflight:
                    del self._entries[key]
                if entry.cancel_requested:
                    self.scheduler.dequeue(key)
                self.scheduler.notify_all()


_coordinator: RequestCoordinator | None = None
_singleton_lock = threading.RLock()


def _build_scheduler(settings) -> SchedulerBackend | None:
    """按配置选择易失调度后端；返回 None 时 RequestCoordinator 用默认 InMemoryScheduler。

    redis 后端惰性导入 ``redis-py`` 并立即 ``ping()``：连不上就在启动期快速失败，
    绝不带半残状态进服务。memory 后端路径完全不依赖 redis-py。
    """
    backend = getattr(settings, "coordination_backend", "memory")
    if backend != "redis":
        return None
    from app.scoped.redis_scheduling import RedisScheduler
    import redis
    client = redis.Redis.from_url(
        settings.coordination_redis_url.get_secret_value(), socket_timeout=5,
        decode_responses=True,
    )
    client.ping()
    return RedisScheduler(
        client,
        max_generation_concurrency=getattr(settings, "scope_max_generation_concurrency", 2),
        queue_limit=getattr(settings, "scope_request_queue_limit", 16),
        session_queue_limit=getattr(settings, "scope_session_queue_limit", 4),
        clock=time.monotonic,
        lease_seconds=getattr(settings, "coordination_lease_seconds", 30.0),
    )


def reset_coordinator() -> RequestCoordinator:
    global _coordinator
    settings = get_settings()
    # 阶段 1：SQL 模式下注入 journal status fallback（内存 miss 时跨进程查）。
    # 惰性导入避免循环依赖：journal 已反向依赖 scoped.context / errors。
    status_fallback = None
    try:
        from app.persistence.database import database_enabled
        if database_enabled():
            from app.persistence.journal import get_durable_request_store

            def _status_fallback(scope, operation, request_id):
                return get_durable_request_store().read_status(scope, operation, request_id)

            status_fallback = _status_fallback
    except Exception:
        # 数据库不可用时退化为纯内存 status（与阶段 0 前行为一致）。
        status_fallback = None
    coordinator = RequestCoordinator(
        max_generation_concurrency=getattr(settings, "scope_max_generation_concurrency", 2),
        queue_limit=getattr(settings, "scope_request_queue_limit", 16),
        session_queue_limit=getattr(settings, "scope_session_queue_limit", 4),
        max_entries=getattr(settings, "scope_request_state_limit", 1024),
        scheduler=_build_scheduler(settings),
        status_fallback=status_fallback,
    )
    with _singleton_lock:
        _coordinator = coordinator
    return coordinator


def get_coordinator() -> RequestCoordinator:
    with _singleton_lock:
        return _coordinator if _coordinator is not None else reset_coordinator()
