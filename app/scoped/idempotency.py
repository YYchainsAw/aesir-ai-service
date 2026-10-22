"""Bounded, process-local single-flight; no durable exactly-once claim."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import threading
import time
from typing import Any, Hashable

from app.scoped.errors import ScopeError
from app.scoped.timing import TimingBudget, use_budget


def fingerprint(payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    payload = deepcopy(payload)
    if isinstance(payload, dict) and isinstance(payload.get("timing"), dict):
        payload["timing"].pop("capture_age_ms", None)
        payload["timing"].pop("request_age_ms", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class NotStartedError(ScopeError):
    """仅由尚未占位/未开始业务的协调器容量拒绝产生。"""


@dataclass
class _Entry:
    fingerprint: str
    state: str = "running"
    result: Any = None
    error: ScopeError | None = None
    timing: TimingBudget | None = None
    expires_at: float = float("inf")


class IdempotencyStore:
    def __init__(self, *, max_entries: int = 1024, retention_seconds: float = 300,
                 wait_timeout_seconds: float = 30, clock: Callable[[], float] = time.monotonic) -> None:
        if max_entries < 1 or retention_seconds <= 0 or wait_timeout_seconds <= 0:
            raise ValueError("Idempotency limits must be positive.")
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self.wait_timeout_seconds = wait_timeout_seconds
        self.clock = clock
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._condition = threading.Condition(threading.RLock())

    def clear(self) -> None:
        with self._condition:
            self._entries.clear()
            self._condition.notify_all()

    def execute(self, key: Hashable, payload: Any, operation: Callable[[], Any], *,
                validate: Callable[[], Any] | None = None, timing: TimingBudget | None = None,
                request_id=None, conflict_code: str = "REQUEST_ID_CONFLICT",
                propagate_not_started: bool = False,
                on_failure: Callable[[Exception], Exception] | None = None) -> Any:
        if validate is not None:
            validate()
        fp = fingerprint(payload)
        started_wait = time.monotonic()
        owner = False
        with self._condition:
            now = self.clock()
            expired = [k for k, v in self._entries.items()
                       if v.state != "running" and v.expires_at <= now]
            for k in expired:
                del self._entries[k]
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self.max_entries:
                    raise NotStartedError(503, "IDEMPOTENCY_CAPACITY", "No completed retention slots are available.", request_id)
                entry = _Entry(fp, timing=timing)
                self._entries[key] = entry
                owner = True
            elif entry.fingerprint != fp:
                raise ScopeError(409, conflict_code, "The logical ID is already bound to another payload.", request_id)
            if not owner and entry.timing is not None and timing is not None:
                try:
                    entry.timing.retry(timing.input)
                except ScopeError as error:
                    if error.code == "REQUEST_ID_CONFLICT" and conflict_code != error.code:
                        raise ScopeError(error.status_code, conflict_code, error.message, request_id) from error
                    raise
            while not owner and entry.state == "running":
                if entry.timing is not None:
                    entry.timing.check()
                remaining = self.wait_timeout_seconds - (time.monotonic() - started_wait)
                if remaining <= 0:
                    raise ScopeError(409, "REQUEST_IN_PROGRESS", "The original request is still processing.", request_id)
                self._condition.wait(timeout=min(remaining, 0.05))
        if not owner:
            if validate is not None:
                validate()
            if entry.timing is not None:
                entry.timing.check()
            if entry.state == "unknown":
                raise ScopeError(503, "REQUEST_OUTCOME_UNKNOWN", "Do not automatically execute this operation again.", request_id)
            if entry.error is not None:
                raise ScopeError(entry.error.status_code, entry.error.code, entry.error.message, request_id)
            return deepcopy(entry.result)
        try:
            if entry.timing is not None:
                entry.timing.check()
            with use_budget(entry.timing):
                result = operation()
            if validate is not None:
                validate()
            if entry.timing is not None:
                entry.timing.check()
            cached_result = deepcopy(result)
        except Exception as error:
            # An inner coordinator may already have committed irreversible facts
            # before these outer validation/copy checks fail. Consult it outside
            # the store lock so the lock order remains runtime/NPC -> token.
            if on_failure is not None:
                try:
                    error = on_failure(error)
                except Exception as callback_error:
                    error = callback_error
            with self._condition:
                entry.expires_at = self.clock() + self.retention_seconds
                if propagate_not_started and isinstance(error, NotStartedError):
                    # 纯协调包装器在调用下层前无副作用；放开本层占位。
                    # 已等待的调用方仍读取同一entry的确定容量拒绝。
                    entry.state, entry.error = "failed", error
                    if self._entries.get(key) is entry:
                        del self._entries[key]
                elif isinstance(error, ScopeError) and error.status_code < 500:
                    entry.state = "failed"
                    entry.error = error
                else:
                    entry.state = "unknown"
                self._condition.notify_all()
            if entry.state == "unknown":
                raise ScopeError(503, "REQUEST_OUTCOME_UNKNOWN", "Operation outcome is uncertain; do not automatically retry.", request_id) from error
            raise
        with self._condition:
            entry.result = cached_result
            entry.state = "complete"
            entry.expires_at = self.clock() + self.retention_seconds
            self._condition.notify_all()
        return deepcopy(result)


_request_store = IdempotencyStore()
_event_store = IdempotencyStore()


def get_request_store() -> IdempotencyStore:
    return _request_store


def get_event_store() -> IdempotencyStore:
    return _event_store


def reset_idempotency_stores() -> None:
    _request_store.clear()
    _event_store.clear()
