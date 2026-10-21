"""Logical IDs provide bounded single-flight, not a durable transaction."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app.scoped.errors import ScopeError
from app.scoped.idempotency import IdempotencyStore
from app.scoped.timing import TimingBudget, current_budget


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds / 1000


def timing(request_age=0):
    return dict(capture_age_ms=100 + request_age, request_age_ms=request_age,
                max_snapshot_age_ms=2000, max_request_age_ms=3000)


def test_concurrent_duplicates_share_one_result_and_directive_id():
    store = IdempotencyStore()
    started, release, duplicate_started = Event(), Event(), Event()
    calls = []
    directive_id = str(uuid4())

    def operation():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {"directive_id": directive_id, "values": [1]}

    def duplicate():
        duplicate_started.set()
        return store.execute("key", {"message": "hello"}, operation)

    with ThreadPoolExecutor(max_workers=2) as executor:
        original = executor.submit(store.execute, "key", {"message": "hello"}, operation)
        assert started.wait(2)
        retry = executor.submit(duplicate)
        assert duplicate_started.wait(2)
        release.set()
        first, second = original.result(2), retry.result(2)
    assert len(calls) == 1
    assert first == second == {"directive_id": directive_id, "values": [1]}
    first["values"].append(2)
    assert store.execute("key", {"message": "hello"}, operation)["values"] == [1]


def test_conflicting_payload_or_epoch_does_not_execute_again():
    store = IdempotencyStore()
    calls = []
    store.execute("key", {"memory_epoch": "a"}, lambda: calls.append(1))
    with pytest.raises(ScopeError) as error:
        store.execute("key", {"memory_epoch": "b"}, lambda: calls.append(2))
    assert error.value.code == "REQUEST_ID_CONFLICT"
    assert calls == [1]


def test_event_conflict_has_specific_code_and_scope_is_part_of_key():
    store = IdempotencyStore()
    assert store.execute(("alice", "event"), {"fact": 1}, lambda: "alice") == "alice"
    assert store.execute(("bob", "event"), {"fact": 1}, lambda: "bob") == "bob"
    with pytest.raises(ScopeError) as error:
        store.execute(("alice", "event"), {"fact": 2}, lambda: None,
                      conflict_code="EVENT_ID_CONFLICT")
    assert error.value.code == "EVENT_ID_CONFLICT"


def test_capacity_never_evicts_an_unexpired_result():
    clock = Clock()
    store = IdempotencyStore(max_entries=1, retention_seconds=2, clock=clock)
    store.execute("first", {}, lambda: 1)
    with pytest.raises(ScopeError) as error:
        store.execute("next", {}, lambda: 2)
    assert error.value.code == "IDEMPOTENCY_CAPACITY"
    assert store.execute("first", {}, lambda: 9) == 1
    clock.advance(2000)
    assert store.execute("next", {}, lambda: 2) == 2


def test_partial_failure_is_unknown_and_same_id_never_reexecutes():
    store = IdempotencyStore()
    effects = []

    def operation():
        effects.append(1)
        raise OSError("second durable write failed")

    for _ in range(2):
        with pytest.raises(ScopeError) as error:
            store.execute("key", {}, operation)
        assert error.value.code == "REQUEST_OUTCOME_UNKNOWN"
    assert effects == [1]


def test_storage_503_is_unknown_and_deterministic_409_is_retained():
    store = IdempotencyStore()
    calls = []

    def fail(code):
        calls.append(code)
        raise ScopeError(code, "STATE_UNAVAILABLE" if code == 503 else "RUN_BINDING_STALE", "rejected")

    for status in (503, 409):
        for _ in range(2):
            with pytest.raises(ScopeError) as error:
                store.execute(status, {}, lambda: fail(status))
            assert error.value.code == ("REQUEST_OUTCOME_UNKNOWN" if status == 503 else "RUN_BINDING_STALE")
    assert calls == [503, 409]


def test_binding_and_epoch_validation_precedes_cached_result_or_conflict():
    store = IdempotencyStore()
    store.execute("key", {"epoch": "a"}, lambda: "original")

    def stale():
        raise ScopeError(409, "MEMORY_EPOCH_STALE", "reset")

    for payload in ({"epoch": "a"}, {"epoch": "b"}):
        with pytest.raises(ScopeError) as error:
            store.execute("key", payload, lambda: "new", validate=stale)
        assert error.value.code == "MEMORY_EPOCH_STALE"


def test_cumulative_retry_age_preserves_original_valid_for_and_id():
    clock = Clock()
    store = IdempotencyStore(clock=clock)
    budget = TimingBudget(timing(), clock=clock)
    calls = []

    def operation():
        calls.append(1)
        assert current_budget() is budget
        return {"directive_id": "stable", "valid_for_ms": budget.valid_for_ms}

    first = store.execute("key", {"timing": timing()}, operation, timing=budget)
    clock.advance(500)
    replay = store.execute("key", {"timing": timing(500)}, operation,
                           timing=TimingBudget(timing(500), clock=clock))
    assert first == replay == {"directive_id": "stable", "valid_for_ms": 1900}
    clock.advance(1400)
    with pytest.raises(ScopeError) as error:
        store.execute("key", {"timing": timing()}, operation, timing=budget)
    assert error.value.code in {"SNAPSHOT_EXPIRED", "REQUEST_ID_CONFLICT"}
    assert calls == [1]


def test_cache_replay_cannot_refresh_snapshot_or_budget():
    clock = Clock()
    store = IdempotencyStore(clock=clock)
    original = timing()
    store.execute("key", {"timing": original}, lambda: "original",
                  timing=TimingBudget(original, clock=clock))
    different = dict(timing(100), capture_age_ms=201)
    with pytest.raises(ScopeError) as error:
        store.execute("key", {"timing": different}, lambda: "new",
                      timing=TimingBudget(different, clock=clock))
    assert error.value.code == "REQUEST_ID_CONFLICT"


def test_waiting_duplicate_has_bounded_wait_and_does_not_reexecute():
    store = IdempotencyStore(wait_timeout_seconds=0.03)
    started, release = Event(), Event()
    calls = []

    def operation():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return "done"

    with ThreadPoolExecutor(max_workers=1) as executor:
        original = executor.submit(store.execute, "key", {}, operation)
        assert started.wait(2)
        with pytest.raises(ScopeError) as error:
            store.execute("key", {}, operation)
        assert error.value.code == "REQUEST_IN_PROGRESS"
        release.set()
        assert original.result(2) == "done"
    assert calls == [1]


def test_process_restart_has_no_durable_idempotency_claim():
    effects = []
    IdempotencyStore().execute("key", {}, lambda: effects.append(1))
    IdempotencyStore().execute("key", {}, lambda: effects.append(2))
    assert effects == [1, 2]


def test_event_timing_conflict_uses_the_event_reason_code():
    clock = Clock()
    store = IdempotencyStore(clock=clock)
    original = timing()
    store.execute("event", {"timing": original}, lambda: "original",
                  timing=TimingBudget(original, clock=clock))
    different = dict(timing(100), capture_age_ms=201)
    with pytest.raises(ScopeError) as error:
        store.execute("event", {"timing": different}, lambda: "new",
                      timing=TimingBudget(different, clock=clock), conflict_code="EVENT_ID_CONFLICT")
    assert error.value.code == "EVENT_ID_CONFLICT"



def test_nested_capacity_is_retryable_only_for_explicit_pure_wrapper():
    from app.scoped.idempotency import NotStartedError
    inner = IdempotencyStore(max_entries=1)
    outer = IdempotencyStore()
    inner.execute("occupied", {}, lambda: None)
    calls = []
    def operation():
        return inner.execute("event", {}, lambda: calls.append("effect") or "done")
    with pytest.raises(NotStartedError) as error:
        outer.execute("request", {}, operation, propagate_not_started=True)
    assert error.value.code == "IDEMPOTENCY_CAPACITY"
    assert calls == []
    inner.clear()
    assert outer.execute("request", {}, operation, propagate_not_started=True) == "done"
    assert calls == ["effect"]


def test_nested_capacity_is_unknown_without_explicit_no_side_effect_guarantee():
    inner = IdempotencyStore(max_entries=1)
    outer = IdempotencyStore()
    inner.execute("occupied", {}, lambda: None)
    calls = []
    def operation():
        calls.append("already-written")
        return inner.execute("event", {}, lambda: None)
    with pytest.raises(ScopeError) as error:
        outer.execute("request", {}, operation)
    assert error.value.code == "REQUEST_OUTCOME_UNKNOWN"
    inner.clear()
    with pytest.raises(ScopeError) as error:
        outer.execute("request", {}, operation)
    assert error.value.code == "REQUEST_OUTCOME_UNKNOWN"
    assert calls == ["already-written"]
