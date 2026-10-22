"""FIFO, bounded concurrency and cancellation are observable request guarantees."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Lock
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.scoped.context import NpcScope, RequestScope
from app.scoped.errors import ScopeError
from app.scoped.requests import (RequestCoordinator, check_current, final_commit,
                                 get_coordinator, reset_coordinator,
                                 timeout_for_upstream, upstream_attempt)
from app.scoped.timing import TimingBudget, current_budget


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def scope():
    return RequestScope(NpcScope("aesir", uuid4(), uuid4(), "companion.alice"),
                        uuid4(), uuid4(), uuid4(), uuid4(), uuid4())


def budget(clock, duration=3000):
    return TimingBudget(dict(capture_age_ms=0, request_age_ms=0,
                             max_snapshot_age_ms=duration, max_request_age_ms=duration),
                        clock=clock, has_snapshot=False)


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, "Concurrent request did not reach the expected state"
        time.sleep(0.005)


def state(coordinator, scope, operation, request_id):
    try:
        return coordinator.status(scope, operation, request_id)["state"]
    except ScopeError as error:
        if error.code == "REQUEST_UNKNOWN":
            return None
        raise


def assert_error(future, code):
    with pytest.raises(ScopeError) as error:
        future.result(3)
    assert error.value.code == code


def test_chat_and_agent_text_share_fifo_but_other_sessions_progress(scope):
    coordinator = RequestCoordinator(max_generation_concurrency=2)
    entered, release, other_entered = Event(), Event(), Event()
    ids = [uuid4() for _ in range(4)]
    order = []

    def first():
        order.append("first")
        entered.set()
        assert release.wait(3)
        return 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        first_result = pool.submit(coordinator.execute, scope, "chat", ids[0], first)
        assert entered.wait(2)
        second = pool.submit(coordinator.execute, scope, "agent-step", ids[1], lambda: order.append("second"))
        wait_for(lambda: state(coordinator, scope, "agent-step", ids[1]) == "queued")
        third = pool.submit(coordinator.execute, scope, "chat", ids[2], lambda: order.append("third"))
        wait_for(lambda: state(coordinator, scope, "chat", ids[2]) == "queued")
        other = replace(scope, session_id=uuid4())
        independent = pool.submit(coordinator.execute, other, "chat", ids[3], lambda: other_entered.set())
        assert other_entered.wait(2)
        assert order == ["first"]
        release.set()
        assert first_result.result(2) == 1
        second.result(2)
        third.result(2)
        independent.result(2)
    assert order == ["first", "second", "third"]


def test_global_generation_limit_and_rule_heartbeat_bypass(scope):
    coordinator = RequestCoordinator(max_generation_concurrency=2)
    release = Event()
    mutex = Lock()
    entered = [Event(), Event(), Event()]
    counts = {"active": 0, "maximum": 0}
    sessions = [replace(scope, session_id=uuid4()) for _ in range(3)]
    ids = [uuid4() for _ in range(3)]

    def action(index):
        with mutex:
            counts["active"] += 1
            counts["maximum"] = max(counts["maximum"], counts["active"])
        entered[index].set()
        assert release.wait(3)
        with mutex:
            counts["active"] -= 1
        return index

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(coordinator.execute, sessions[i], "chat", ids[i], lambda i=i: action(i))
                   for i in range(2)]
        assert all(event.wait(2) for event in entered[:2])
        futures.append(pool.submit(coordinator.execute, sessions[2], "chat", ids[2], lambda: action(2)))
        wait_for(lambda: state(coordinator, sessions[2], "chat", ids[2]) == "queued")
        heartbeat = pool.submit(coordinator.execute, sessions[0], "agent-step", uuid4(), lambda: "rule", serial=False)
        assert heartbeat.result(2) == "rule"
        assert not entered[2].is_set()
        release.set()
        assert [future.result(2) for future in futures] == [0, 1, 2]
    assert counts["maximum"] == 2


@pytest.mark.parametrize("same_session,queue_limit,session_limit", [(True, 4, 1), (False, 1, 4)])
def test_waiting_limits_reject_without_starting_or_reserving_state(scope, same_session, queue_limit, session_limit):
    coordinator = RequestCoordinator(max_generation_concurrency=1, queue_limit=queue_limit,
                                     session_queue_limit=session_limit)
    entered, release = Event(), Event()
    queued_id, rejected_id = uuid4(), uuid4()
    waiting_scope = scope if same_session else replace(scope, session_id=uuid4())

    def block():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(coordinator.execute, scope, "chat", uuid4(), block)
        assert entered.wait(2)
        queued = pool.submit(coordinator.execute, waiting_scope, "chat", queued_id, lambda: "queued")
        wait_for(lambda: state(coordinator, waiting_scope, "chat", queued_id) == "queued")
        with pytest.raises(ScopeError) as error:
            coordinator.execute(waiting_scope, "chat", rejected_id, lambda: pytest.fail("Queue overflow executed"))
        assert (error.value.status_code, error.value.code) == (503, "REQUEST_QUEUE_FULL")
        assert state(coordinator, waiting_scope, "chat", rejected_id) is None
        release.set()
        running.result(2)
        assert queued.result(2) == "queued"


def test_cancel_queued_frees_waiting_capacity_and_never_runs_action(scope):
    coordinator = RequestCoordinator(max_generation_concurrency=1, queue_limit=1)
    entered, release = Event(), Event()
    first_id, queued_id = uuid4(), uuid4()

    def block():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(coordinator.execute, scope, "chat", first_id, block)
        assert entered.wait(2)
        queued = pool.submit(coordinator.execute, scope, "chat", queued_id,
                             lambda: pytest.fail("Cancelled action executed"))
        wait_for(lambda: state(coordinator, scope, "chat", queued_id) == "queued")
        record = coordinator.cancel(scope, "chat", queued_id)
        assert record["state"] == "cancelled" and record["cancel_requested"]
        assert_error(queued, "REQUEST_CANCELLED")
        assert coordinator.execute(scope, "agent-step", uuid4(), lambda: "rule", serial=False) == "rule"
        release.set()
        running.result(2)


def test_running_cancel_is_checked_after_upstream_and_no_final_effect_occurs(scope):
    coordinator = RequestCoordinator()
    entered, release = Event(), Event()
    request_id, effects = uuid4(), []

    def action():
        with upstream_attempt():
            entered.set()
            assert release.wait(3)
        with final_commit():
            effects.append("committed")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(coordinator.execute, scope, "chat", request_id, action)
        assert entered.wait(2)
        assert coordinator.cancel(scope, "chat", request_id)["cancel_requested"]
        release.set()
        assert_error(future, "REQUEST_CANCELLED")
    record = coordinator.status(scope, "chat", request_id)
    assert record["state"] == "cancelled"
    assert record["reason_code"] == "USER_CANCELLED" and record["upstream_attempts"] == 1
    assert effects == []


def test_prearrival_cancellation_tombstone_blocks_text_and_heartbeat(scope):
    coordinator = RequestCoordinator()
    for serial in (True, False):
        request_id = uuid4()
        record = coordinator.cancel(scope, "agent-step", request_id)
        assert record["state"] == "cancelled"
        with pytest.raises(ScopeError) as error:
            coordinator.execute(scope, "agent-step", request_id, lambda: pytest.fail("Tombstone ignored"), serial=serial)
        assert error.value.code == "REQUEST_CANCELLED"


def test_final_commit_linearizes_cancellation_and_keeps_committed_result(scope):
    coordinator = RequestCoordinator()
    committing, release, cancel_started = Event(), Event(), Event()
    request_id, effects = uuid4(), []

    def action():
        with final_commit():
            committing.set()
            assert release.wait(3)
            effects.append("fact")
        return "confirmed"

    def cancel():
        cancel_started.set()
        return coordinator.cancel(scope, "chat", request_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(coordinator.execute, scope, "chat", request_id, action)
        assert committing.wait(2)
        cancellation = pool.submit(cancel)
        assert cancel_started.wait(2)
        assert not cancellation.done()
        release.set()
        assert future.result(2) == "confirmed"
        assert cancellation.result(2)["cancel_requested"] is False
    assert effects == ["fact"]
    assert coordinator.cancel(scope, "chat", request_id)["state"] == "completed"


def test_partial_commit_failure_is_unknown_and_never_reexecuted(scope):
    coordinator = RequestCoordinator()
    request_id, effects = uuid4(), []

    def action():
        with final_commit():
            effects.append("first fact")
            raise OSError("sensitive provider detail")

    for _ in range(2):
        with pytest.raises(ScopeError) as error:
            coordinator.execute(scope, "chat", request_id, action)
        assert error.value.code == "REQUEST_OUTCOME_UNKNOWN"
    assert effects == ["first fact"]
    record = coordinator.status(scope, "chat", request_id)
    assert record["state"] == "unknown" and "sensitive" not in repr(record)
    assert not coordinator.cancel(scope, "chat", request_id)["cancel_requested"]


def test_before_commit_failure_is_failed_and_does_not_repeat(scope):
    coordinator = RequestCoordinator()
    request_id, calls = uuid4(), []

    def action():
        calls.append(1)
        raise ScopeError(409, "RUN_BINDING_STALE", "Binding changed")

    for _ in range(2):
        with pytest.raises(ScopeError) as error:
            coordinator.execute(scope, "chat", request_id, action)
        assert error.value.code == "RUN_BINDING_STALE"
    assert calls == [1]
    assert coordinator.status(scope, "chat", request_id)["state"] == "failed"


def test_duplicate_coordinator_calls_are_single_flight_and_copy_cached_results(scope):
    coordinator = RequestCoordinator()
    entered, release = Event(), Event()
    request_id, calls = uuid4(), []

    def action():
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return {"items": [1]}

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(coordinator.execute, scope, "chat", request_id, action)
        assert entered.wait(2)
        duplicate = pool.submit(coordinator.execute, scope, "chat", request_id, action)
        release.set()
        one, two = first.result(2), duplicate.result(2)
    assert calls == [1] and one == two
    one["items"].append(2)
    assert coordinator.execute(scope, "chat", request_id, action) == {"items": [1]}


@pytest.mark.parametrize("field", ["session_id", "service_instance_id", "run_binding_id", "memory_epoch", "encounter_id"])
def test_original_scope_cannot_be_changed_to_bypass_same_id(scope, field):
    coordinator = RequestCoordinator()
    request_id = uuid4()
    coordinator.cancel(scope, "chat", request_id)
    changed = replace(scope, **{field: uuid4()})
    for operation in (coordinator.status, coordinator.cancel):
        with pytest.raises(ScopeError) as error:
            operation(changed, "chat", request_id)
        assert error.value.code == "REQUEST_ID_CONFLICT"
    with pytest.raises(ScopeError) as error:
        coordinator.execute(changed, "chat", request_id, lambda: pytest.fail("Scope conflict executed"))
    assert error.value.code == "REQUEST_ID_CONFLICT"


def test_queued_budget_expiry_is_recorded_before_action(scope):
    clock = Clock()
    coordinator = RequestCoordinator(max_generation_concurrency=1, clock=clock)
    entered, release = Event(), Event()
    request_id = uuid4()
    queued_budget = budget(clock, 1000)

    def block():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(coordinator.execute, scope, "chat", uuid4(), block)
        assert entered.wait(2)
        queued = pool.submit(coordinator.execute, scope, "agent-step", request_id,
                             lambda: pytest.fail("Expired request executed"), budget=queued_budget)
        wait_for(lambda: state(coordinator, scope, "agent-step", request_id) == "queued")
        clock.advance(1)
        assert_error(queued, "REQUEST_EXPIRED")
        assert coordinator.status(scope, "agent-step", request_id)["state"] == "expired"
        release.set()
        running.result(2)


def test_waiting_validation_runs_outside_scheduler_lock_and_detects_stale_epoch(scope):
    coordinator = RequestCoordinator(max_generation_concurrency=1)
    entered, release, stale = Event(), Event(), Event()
    request_id = uuid4()
    validations = []

    def validate():
        # Another thread must be able to take the coordinator lock while this
        # callback is active, preventing a condition->runtime lock inversion.
        done = Event()
        with ThreadPoolExecutor(max_workers=1) as checker:
            checker.submit(lambda: (state(coordinator, scope, "agent-step", request_id), done.set()))
            assert done.wait(1)
        validations.append(1)
        if stale.is_set():
            raise ScopeError(409, "MEMORY_EPOCH_STALE", "Memory was reset")

    def block():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(coordinator.execute, scope, "chat", uuid4(), block)
        assert entered.wait(2)
        queued = pool.submit(coordinator.execute, scope, "agent-step", request_id,
                             lambda: pytest.fail("Stale epoch executed"), validate=validate)
        wait_for(lambda: state(coordinator, scope, "agent-step", request_id) == "queued")
        stale.set()
        assert_error(queued, "MEMORY_EPOCH_STALE")
        release.set()
        running.result(2)
    assert len(validations) >= 2


def test_retention_never_evicts_unexpired_states_or_tombstones(scope):
    clock = Clock()
    coordinator = RequestCoordinator(max_entries=2, retention_seconds=2, clock=clock)
    first, cancelled = uuid4(), uuid4()
    assert coordinator.execute(scope, "chat", first, lambda: 1) == 1
    coordinator.cancel(scope, "chat", cancelled)
    for operation in (lambda: coordinator.execute(scope, "chat", uuid4(), lambda: 2),
                      lambda: coordinator.cancel(scope, "chat", uuid4())):
        with pytest.raises(ScopeError) as error:
            operation()
        assert error.value.code == "REQUEST_QUEUE_FULL"
    assert coordinator.execute(scope, "chat", first, lambda: 9) == 1
    clock.advance(2)
    assert coordinator.execute(scope, "chat", uuid4(), lambda: 2) == 2
    assert state(coordinator, scope, "chat", first) is None


def test_cancelled_upstream_owner_remains_retained_until_it_exits(scope):
    clock = Clock()
    coordinator = RequestCoordinator(max_entries=1, retention_seconds=1, clock=clock)
    entered, release = Event(), Event()
    request_id = uuid4()

    def action():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(coordinator.execute, scope, "chat", request_id, action)
        assert entered.wait(2)
        coordinator.cancel(scope, "chat", request_id)
        clock.advance(2)
        with pytest.raises(ScopeError) as error:
            coordinator.execute(scope, "chat", uuid4(), lambda: None)
        assert error.value.code == "REQUEST_QUEUE_FULL"
        release.set()
        assert_error(future, "REQUEST_CANCELLED")


def test_upstream_attempt_ids_count_and_timeout_share_request_budget(scope):
    clock = Clock()
    coordinator = RequestCoordinator(clock=clock)
    request_id = uuid4()
    timing = budget(clock, 3000)
    attempts = []

    def action():
        assert current_budget() is timing
        for _ in range(2):
            with upstream_attempt() as attempt:
                attempts.append(UUID(attempt))
                clock.advance(0.5)
        assert 1.99 <= timeout_for_upstream(15) <= 2
        assert timeout_for_upstream(0.5) == 0.5
        return "done"

    assert coordinator.execute(scope, "chat", request_id, action, budget=timing) == "done"
    record = coordinator.status(scope, "chat", request_id)
    assert len(set(attempts)) == record["upstream_attempts"] == 2
    assert record["processing_ms"] == record["total_ms"] == 1000


def test_upstream_completion_revalidates_even_when_provider_raises(scope):
    coordinator = RequestCoordinator()
    stale = Event()
    request_id = uuid4()

    def validate():
        if stale.is_set():
            raise ScopeError(409, "RUN_BINDING_STALE", "Run replaced")

    def action():
        with upstream_attempt():
            stale.set()
            raise TimeoutError("provider error")

    with pytest.raises(ScopeError) as error:
        coordinator.execute(scope, "chat", request_id, action, validate=validate)
    assert error.value.code == "RUN_BINDING_STALE"
    assert coordinator.status(scope, "chat", request_id)["upstream_attempts"] == 1


def test_status_has_only_fixed_safe_fields_and_unknown_is_404(scope):
    coordinator = RequestCoordinator()
    request_id = uuid4()
    with pytest.raises(ScopeError) as error:
        coordinator.status(scope, "chat", request_id)
    assert (error.value.status_code, error.value.code) == (404, "REQUEST_UNKNOWN")
    coordinator.execute(scope, "chat", request_id, lambda: {"text": "private conversation"})
    record = coordinator.status(scope, "chat", request_id)
    assert set(record) == {"target_request_id", "operation", "state", "reason_code", "queue_ms",
                           "processing_ms", "total_ms", "upstream_attempts", "cancel_requested"}
    assert record["reason_code"] is None and "private" not in repr(record)
    coordinator.clear()
    assert state(coordinator, scope, "chat", request_id) is None


def test_helpers_without_active_token_keep_legacy_behavior():
    check_current()
    with final_commit(), upstream_attempt() as attempt:
        assert UUID(attempt)
        assert timeout_for_upstream(15) == 15


def test_singleton_reads_config_with_safe_defaults(monkeypatch):
    import app.scoped.requests as requests
    monkeypatch.setattr(requests, "get_settings", lambda: SimpleNamespace(
        scope_max_generation_concurrency=3, scope_request_queue_limit=8,
        scope_session_queue_limit=2, scope_request_state_limit=64))
    coordinator = reset_coordinator()
    assert get_coordinator() is coordinator
    assert (coordinator.max_generation_concurrency, coordinator.queue_limit,
            coordinator.session_queue_limit, coordinator.max_entries) == (3, 8, 2, 64)
    monkeypatch.setattr(requests, "get_settings", lambda: SimpleNamespace())
    assert reset_coordinator().max_generation_concurrency == 2

def test_unknown_outcome_survives_retention_and_holds_capacity_until_clear(scope):
    clock = Clock()
    coordinator = RequestCoordinator(max_entries=1, retention_seconds=1, clock=clock)
    request_id, effects = uuid4(), []

    def action():
        with final_commit():
            effects.append("first fact")
            raise OSError("uncertain second fact")

    with pytest.raises(ScopeError, match="uncertain"):
        coordinator.execute(scope, "chat", request_id, action)
    clock.advance(301)
    assert coordinator.status(scope, "chat", request_id)["state"] == "unknown"
    with pytest.raises(ScopeError) as retry:
        coordinator.execute(scope, "chat", request_id, action)
    assert retry.value.code == "REQUEST_OUTCOME_UNKNOWN" and effects == ["first fact"]
    with pytest.raises(ScopeError) as capacity:
        coordinator.cancel(scope, "chat", uuid4())
    assert capacity.value.code == "REQUEST_QUEUE_FULL"
    coordinator.clear()
    assert coordinator.execute(scope, "chat", uuid4(), lambda: "after-clear") == "after-clear"


def test_prearrival_tombstone_is_complete_before_cancel_returns(scope, monkeypatch):
    from threading import current_thread
    coordinator = RequestCoordinator()
    request_id = uuid4()
    inserted, release = Event(), Event()
    original = coordinator._same_scope

    def pause_cancel(entry, candidate):
        if current_thread().name.startswith("tombstone-cancel"):
            inserted.set()
            assert release.wait(3)
        return original(entry, candidate)

    monkeypatch.setattr(coordinator, "_same_scope", pause_cancel)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tombstone-cancel") as pool:
        cancellation = pool.submit(coordinator.cancel, scope, "agent-step", request_id)
        assert inserted.wait(2)
        try:
            with pytest.raises(ScopeError) as error:
                coordinator.execute(scope, "agent-step", request_id,
                                    lambda: pytest.fail("Published tombstone ignored"), serial=False)
            assert error.value.code == "REQUEST_CANCELLED"
        finally:
            release.set()
        assert cancellation.result(2)["state"] == "cancelled"


def test_cancelled_running_duration_tracks_actual_owner_exit(scope):
    clock = Clock()
    coordinator = RequestCoordinator(clock=clock)
    entered, release = Event(), Event()
    request_id = uuid4()

    def action():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(coordinator.execute, scope, "chat", request_id, action)
        assert entered.wait(2)
        clock.advance(1)
        coordinator.cancel(scope, "chat", request_id)
        clock.advance(1)
        record = coordinator.status(scope, "chat", request_id)
        assert record["processing_ms"] == record["total_ms"] == 2000
        release.set()
        assert_error(future, "REQUEST_CANCELLED")
    clock.advance(1)
    assert coordinator.status(scope, "chat", request_id)["total_ms"] == 2000


def test_active_request_helper_does_not_leak_into_legacy_calls(scope):
    from app.scoped.requests import has_active_request
    coordinator = RequestCoordinator()
    assert not has_active_request()
    assert coordinator.execute(scope, "chat", uuid4(), has_active_request)
    assert not has_active_request()

def test_old_tombstone_cancel_cannot_remove_same_id_new_queue_entry(scope, monkeypatch):
    from threading import current_thread
    clock = Clock()
    coordinator = RequestCoordinator(max_generation_concurrency=1, retention_seconds=1, clock=clock)
    request_id = uuid4()
    coordinator.cancel(scope, "chat", request_id)
    entered, release, old_cancel_read, finish_old_cancel = Event(), Event(), Event(), Event()
    original = coordinator._same_scope

    def pause_old_cancel(entry, candidate):
        if current_thread().name.startswith("expired-cancel"):
            old_cancel_read.set()
            assert finish_old_cancel.wait(3)
        return original(entry, candidate)

    def block():
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(coordinator, "_same_scope", pause_old_cancel)
    with ThreadPoolExecutor(max_workers=2) as workers, ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="expired-cancel") as canceller:
        running = workers.submit(coordinator.execute, scope, "chat", uuid4(), block)
        assert entered.wait(2)
        old_cancel = canceller.submit(coordinator.cancel, scope, "chat", request_id)
        assert old_cancel_read.wait(2)
        clock.advance(2)
        queued = workers.submit(coordinator.execute, scope, "chat", request_id, lambda: "new-generation")
        wait_for(lambda: state(coordinator, scope, "chat", request_id) == "queued")
        finish_old_cancel.set()
        old_cancel.result(2)
        release.set()
        try:
            assert queued.result(2) == "new-generation"
        finally:
            if not queued.done():
                coordinator.cancel(scope, "chat", request_id)
        running.result(2)