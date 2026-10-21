"""Monotonic budgets anchored to a logical request's first client send."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Callable, Iterator

from app.scoped.errors import ScopeError


def _values(value) -> dict[str, int]:
    data = value.model_dump() if hasattr(value, "model_dump") else dict(value)
    required = ("capture_age_ms", "request_age_ms", "max_snapshot_age_ms", "max_request_age_ms")
    if any(type(data.get(k)) is not int or data[k] < 0 for k in required):
        raise ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Timing values must be non-negative integers.")
    if data["capture_age_ms"] < data["request_age_ms"]:
        raise ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Snapshot capture cannot follow the original request.")
    return {k: data[k] for k in required}


class TimingBudget:
    def __init__(self, timing, *, clock: Callable[[], float] = time.monotonic,
                 has_snapshot: bool = True, max_budget_ms: int = 120_000) -> None:
        self._lock = threading.RLock()
        self.input = _values(timing)
        if max(self.input["max_snapshot_age_ms"], self.input["max_request_age_ms"]) > max_budget_ms:
            raise ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Timing budget exceeds the configured limit.")
        self.clock = clock
        self.has_snapshot = has_snapshot
        self.received_at = clock()
        self.initial_age_ms = self.input["request_age_ms"]
        self.snapshot_initial_age_ms = self.input["capture_age_ms"] - self.initial_age_ms
        self.last_attempt_age_ms = self.initial_age_ms
        self._observed_age_ms = self.initial_age_ms
        self._observed_at = self.received_at
        self._valid_for_ms = self.input["max_request_age_ms"]
        if has_snapshot:
            self._valid_for_ms = min(self._valid_for_ms,
                                     self.input["max_snapshot_age_ms"] - self.snapshot_initial_age_ms)
        self.deadline = self.received_at + (self._valid_for_ms - self.initial_age_ms) / 1000
        self.check()

    @property
    def elapsed_ms(self) -> float:
        with self._lock:
            now = self.clock()
            return max(self.initial_age_ms + max(0.0, now - self.received_at) * 1000,
                       self._observed_age_ms + max(0.0, now - self._observed_at) * 1000)

    @property
    def remaining_ms(self) -> int:
        with self._lock:
            return max(0, int((self.deadline - self.clock()) * 1000))

    @property
    def valid_for_ms(self) -> int:
        with self._lock:
            return max(0, int(self._valid_for_ms))

    def check(self) -> None:
        with self._lock:
            age = self.elapsed_ms
            if self.has_snapshot and self.snapshot_initial_age_ms + age >= self.input["max_snapshot_age_ms"]:
                raise ScopeError(409, "SNAPSHOT_EXPIRED", "The source snapshot is no longer current.")
            if age >= self._valid_for_ms or self.clock() >= self.deadline:
                raise ScopeError(409, "REQUEST_EXPIRED", "The logical request has expired.")

    def retry(self, timing) -> None:
        with self._lock:
            data = _values(timing)
            if (data["max_request_age_ms"] != self.input["max_request_age_ms"]
                    or data["max_snapshot_age_ms"] != self.input["max_snapshot_age_ms"]
                    or data["capture_age_ms"] - data["request_age_ms"] != self.snapshot_initial_age_ms
                    or data["request_age_ms"] < self.last_attempt_age_ms):
                raise ScopeError(409, "REQUEST_ID_CONFLICT", "Retry timing changed the original capture or budget.")
            self.last_attempt_age_ms = data["request_age_ms"]
            now = self.clock()
            self._observed_age_ms = max(self.elapsed_ms, data["request_age_ms"])
            self._observed_at = now
            # New attempts may tighten, never move, the original deadline forward.
            self.deadline = min(self.deadline, now + (self._valid_for_ms - data["request_age_ms"]) / 1000)
            self.check()

    def limit_validity(self, duration_ms: int) -> None:
        with self._lock:
            if type(duration_ms) is not int or duration_ms < 0:
                raise ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Action duration must be a non-negative integer.")
            self._valid_for_ms = min(self._valid_for_ms, int(self.elapsed_ms) + duration_ms)
            self.deadline = min(self.deadline, self.clock() + duration_ms / 1000)
            self.check()


_budget: ContextVar[TimingBudget | None] = ContextVar("scoped_timing_budget", default=None)


def current_budget() -> TimingBudget | None:
    return _budget.get()


@contextmanager
def use_budget(budget: TimingBudget | None) -> Iterator[None]:
    token = _budget.set(budget)
    try:
        yield
    finally:
        _budget.reset(token)
