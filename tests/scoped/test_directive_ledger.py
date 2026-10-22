"""执行反馈账本：作用域、状态单调性、有界去重与不确定提交。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from app.scoped import directives, storage
from app.scoped.context import NpcScope, RequestScope
from app.scoped.directives import DirectiveRegistry
from app.scoped.errors import ScopeError
from app.scoped.idempotency import IdempotencyStore
from app.scoped.runtime import reset_runtime
from app.schemas.scoped import ScopedExecutionReceipt


class Harness:
    def __init__(self, root):
        self.root = root
        self.now = [0.0]
        self.runtime = reset_runtime()
        self.registry = DirectiveRegistry(clock=lambda: self.now[0])
        self.scope = self.make_scope()

    def make_scope(self, npc=None, *, combat=False):
        npc = npc or NpcScope("aesir", uuid4(), uuid4(), "companion.alice")
        control = self.runtime.context(npc)
        control = self.runtime.bind_run(
            npc, request_id=uuid4(), service_instance_id=self.runtime.service_instance_id,
            expected_control_revision=control["control_revision"],
            expected_run_id=control["run_id"], run_id=uuid4())
        encounter_id = None
        if combat:
            encounter_id = uuid4()
            self.runtime.control_encounter(
                npc, request_id=uuid4(), service_instance_id=self.runtime.service_instance_id,
                run_id=control["run_id"], run_binding_id=control["run_binding_id"],
                op="begin", expected_encounter_revision=0,
                expected_encounter_id=None, encounter_id=encounter_id)
        return RequestScope(npc, control["run_id"], uuid4(), self.runtime.service_instance_id,
                            control["run_binding_id"], storage.memory_epoch(npc), encounter_id)

    def issue(self, *, scope=None, registry=None, request_id=None, directive=None):
        scope, registry = scope or self.scope, registry or self.registry
        request_id = request_id or uuid4()
        directive = directive or dict(
            protocol_version="0.4", directive_id=str(uuid4()), domain="combat",
            action_type="cast_skill", payload={"ability_id": "ability.guard"},
            expires={"type": "before_seconds", "remaining_seconds": 10})
        registry.register(scope, request_id, directive)
        return request_id, directive

    @staticmethod
    def receipt(directive, *, result="accepted", **changes):
        data = dict(protocol_version="0.4", order_id=directive["directive_id"], result=result)
        data.update(changes)
        return ScopedExecutionReceipt(**data)

    def records(self):
        return [json.loads(line) for path in sorted(self.root.rglob("*.jsonl"))
                for line in path.read_text(encoding="utf-8").splitlines()]


def assert_error(status, code, action):
    with pytest.raises(ScopeError) as error:
        action()
    assert (error.value.status_code, error.value.code) == (status, code)


@pytest.fixture
def h(monkeypatch, tmp_path):
    root = tmp_path / "receipts"
    monkeypatch.setenv("AESIR_RECEIPTS_DIR", str(root))
    return Harness(root)


def test_issue_accept_execute_tracks_only_ue_reported_phase(h):
    request_id, directive = h.issue()
    order_id = directive["directive_id"]
    assert h.registry.state(h.scope, order_id) == dict(
        directive_id=order_id, origin_request_id=str(request_id), state="issued",
        last_result=None, terminal=False, sequence=None, receipt_count=0)
    accepted = h.receipt(directive, request_id=request_id, sequence=10)
    assert h.registry.record(h.scope, [accepted]) == 1
    assert h.registry.state(h.scope, order_id)["state"] == "accepted"
    assert h.registry.state(h.scope, order_id)["terminal"] is False
    # Arrival order governs phase; neither client time nor sequence sorts facts.
    executed = h.receipt(directive, result="executed", sequence=2,
                         reported_at="2026-10-22T00:00:00Z")
    assert h.registry.record(h.scope, [executed]) == 1
    assert h.registry.state(h.scope, order_id) == dict(
        directive_id=order_id, origin_request_id=str(request_id), state="executed",
        last_result="executed", terminal=True, sequence=2, receipt_count=2)
    records = h.records()
    assert [r["result"] for r in records] == ["accepted", "executed"]
    assert records[0]["scope"]["player_id"] == str(h.scope.npc.player_id)
    assert records[0]["scope"]["run_binding_id"] == str(h.scope.run_binding_id)
    assert records[0]["scope"]["memory_epoch"] == str(h.scope.memory_epoch)
    assert not {"started", "hit", "completed"}.intersection(records[-1])


@pytest.mark.parametrize("terminal", ["executed", "rejected", "expired", "cancelled"])
def test_terminal_never_rolls_back_and_conflicting_terminal_is_rejected(h, terminal):
    _, directive = h.issue()
    assert h.registry.record(h.scope, [h.receipt(directive, result=terminal, sequence=1)]) == 1
    before = h.registry.state(h.scope, directive["directive_id"])
    late = h.receipt(directive, sequence=9, reason_code="late received confirmation")
    assert h.registry.record(h.scope, [late]) == 0
    assert h.registry.record(h.scope, [late]) == 0
    assert h.registry.state(h.scope, directive["directive_id"]) == before
    conflicting = "rejected" if terminal == "executed" else "executed"
    assert_error(409, "RECEIPT_STATE_CONFLICT", lambda: h.registry.record(
        h.scope, [h.receipt(directive, result=conflicting, sequence=10)]))
    assert h.registry.state(h.scope, directive["directive_id"]) == before
    assert len(h.records()) == 1
    assert_error(409, "RECEIPT_SEQUENCE_CONFLICT", lambda: h.registry.record(
        h.scope, [h.receipt(directive, sequence=9, reason_code="changed late receipt")]))


@pytest.mark.parametrize("sequence", [None, 0])
def test_received_at_is_ignored_for_semantic_deduplication(h, sequence):
    _, directive = h.issue()
    first = h.receipt(directive, sequence=sequence, received_at="2026-10-22T01:00:00Z")
    retry = first.model_copy(update={"received_at": "2026-10-22T02:00:00Z"})
    assert h.registry.record(h.scope, [first, retry]) == 1
    assert h.registry.record(h.scope, [retry]) == 0
    assert h.registry.state(h.scope, directive["directive_id"])["receipt_count"] == 1
    assert len(h.records()) == 1
    changed = first.model_copy(update={"reported_at": "2026-10-22T01:00:00Z"})
    if sequence is not None:
        assert_error(409, "RECEIPT_SEQUENCE_CONFLICT", lambda: h.registry.record(h.scope, [changed]))
    else:
        assert h.registry.record(h.scope, [changed]) == 1


@pytest.mark.parametrize("invalid", ["unknown", "sequence", "terminal"])
def test_whole_batch_is_validated_before_any_append_or_state_change(h, invalid):
    _, first = h.issue()
    _, second = h.issue()
    good = h.receipt(first, sequence=0)
    if invalid == "unknown":
        bad = h.receipt({"directive_id": str(uuid4())})
        expected = "DIRECTIVE_UNKNOWN"
    elif invalid == "sequence":
        bad = h.receipt(first, result="executed", sequence=0)
        expected = "RECEIPT_SEQUENCE_CONFLICT"
    else:
        good = h.receipt(first, result="executed", sequence=0)
        bad = h.receipt(first, result="rejected", sequence=1)
        expected = "RECEIPT_STATE_CONFLICT"
    assert_error(409, expected, lambda: h.registry.record(
        h.scope, [h.receipt(second), good, bad]))
    assert h.records() == []
    for directive in (first, second):
        state = h.registry.state(h.scope, directive["directive_id"])
        assert (state["state"], state["receipt_count"]) == ("issued", 0)


def test_batch_duplicate_receipts_are_not_appended_twice(h):
    _, directive = h.issue()
    accepted = h.receipt(directive, sequence=0)
    executed = h.receipt(directive, result="executed", sequence=1)
    assert h.registry.record(h.scope, [accepted, accepted, executed, executed]) == 2
    assert [r["result"] for r in h.records()] == ["accepted", "executed"]
    assert h.registry.state(h.scope, directive["directive_id"])["receipt_count"] == 2


def test_receipt_identity_history_is_bounded_without_evicting_duplicates(h):
    _, directive = h.issue()
    assert h.registry.max_receipts_per_order == 64
    receipts = [h.receipt(directive, sequence=i, reason_code=f"reason {i}") for i in range(64)]
    assert h.registry.record(h.scope, receipts) == 64
    assert h.registry.record(h.scope, [receipts[0]]) == 0
    assert_error(503, "STATE_UNAVAILABLE", lambda: h.registry.record(
        h.scope, [h.receipt(directive, sequence=64, reason_code="new reason")]))
    assert len(h.records()) == 64
    assert h.registry.state(h.scope, directive["directive_id"])["receipt_count"] == 64


def test_ignored_late_acceptances_also_have_a_bounded_identity_history(h):
    registry = DirectiveRegistry(max_receipts_per_order=2)
    _, directive = h.issue(registry=registry)
    assert registry.record(h.scope, [h.receipt(directive, result="executed", sequence=1)]) == 1
    late = h.receipt(directive, sequence=2)
    assert registry.record(h.scope, [late]) == 0
    assert registry.record(h.scope, [late]) == 0
    assert_error(503, "STATE_UNAVAILABLE", lambda: registry.record(
        h.scope, [h.receipt(directive, sequence=3)]))
    assert len(h.records()) == 1


def test_concurrent_duplicate_receipts_have_one_append(h):
    _, directive = h.issue()
    receipt, barrier = h.receipt(directive, sequence=0), Barrier(8)
    def record(_):
        barrier.wait(timeout=5)
        return h.registry.record(h.scope, [receipt])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(record, range(8)))
    assert sorted(results) == [0] * 7 + [1]
    assert len(h.records()) == 1


def test_concurrent_conflicting_terminals_have_one_winner(h):
    _, directive = h.issue()
    barrier = Barrier(2)
    def record(result):
        barrier.wait(timeout=5)
        try:
            return h.registry.record(h.scope, [h.receipt(directive, result=result)])
        except ScopeError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, ["executed", "cancelled"]))
    assert sorted(map(str, results)) == ["1", "RECEIPT_STATE_CONFLICT"]
    assert len(h.records()) == 1
    assert h.registry.state(h.scope, directive["directive_id"])["state"] == h.records()[0]["result"]


def test_register_conflict_and_identical_retry_does_not_extend_retention(h):
    request_id, directive = h.issue()
    changed = deepcopy(directive)
    changed["payload"]["ability_id"] = "ability.other"
    assert_error(409, "DIRECTIVE_ID_CONFLICT", lambda: h.registry.register(h.scope, request_id, changed))
    assert_error(409, "DIRECTIVE_ID_CONFLICT", lambda: h.registry.register(h.scope, uuid4(), directive))
    h.now[0] = 250
    h.registry.register(h.scope, request_id, directive)
    h.now[0] = 300
    assert_error(404, "DIRECTIVE_UNKNOWN", lambda: h.registry.state(h.scope, directive["directive_id"]))
    assert_error(409, "DIRECTIVE_UNKNOWN", lambda: h.registry.record(h.scope, [h.receipt(directive)]))


def test_capacity_rejects_without_evicting_unexpired_orders(h):
    assert h.registry.max_entries == 4096
    registry = DirectiveRegistry(max_entries=2, clock=lambda: h.now[0])
    _, first = h.issue(registry=registry)
    h.issue(registry=registry)
    assert_error(503, "STATE_UNAVAILABLE", lambda: h.issue(registry=registry))
    assert registry.state(h.scope, first["directive_id"])["state"] == "issued"
    h.now[0] = 300
    h.issue(registry=registry)
    assert len(registry.entries) == 1


def test_reset_rejects_original_scope_and_relabelled_receipt_or_registration(h):
    request_id, directive = h.issue()
    assert h.registry.record(h.scope, [h.receipt(directive)]) == 1
    result = storage.reset_memory(h.scope.npc, h.scope.memory_epoch)
    fresh = replace(h.scope, memory_epoch=result["memory_epoch"])
    for scope in (h.scope, fresh):
        assert_error(409, "MEMORY_EPOCH_STALE", lambda: h.registry.state(scope, directive["directive_id"]))
        assert_error(409, "MEMORY_EPOCH_STALE", lambda: h.registry.record(scope, [h.receipt(directive)]))
        assert_error(409, "MEMORY_EPOCH_STALE", lambda: h.registry.register(scope, request_id, directive))
    assert len(h.records()) == 1


def test_other_player_order_id_and_optional_receipt_associations_are_checked(h):
    request_id, directive = h.issue()
    other = h.make_scope()
    assert_error(404, "DIRECTIVE_UNKNOWN", lambda: h.registry.state(other, directive["directive_id"]))
    assert_error(409, "DIRECTIVE_UNKNOWN", lambda: h.registry.record(other, [h.receipt(directive)]))
    for changes in ({"request_id": uuid4()}, {"ability_id": "ability.other"},
                    {"encounter_id": uuid4()}, {"agent_id": "companion.bob"}):
        assert_error(409, "DIRECTIVE_MISMATCH", lambda: h.registry.record(
            h.scope, [h.receipt(directive, **changes)]))
    assert h.registry.record(h.scope, [h.receipt(directive, request_id=request_id,
                                             ability_id="ability.guard")]) == 1


def test_encounter_binding_and_service_restart_cannot_reuse_old_orders(h):
    combat = h.make_scope(combat=True)
    _, directive = h.issue(scope=combat)
    assert_error(409, "DIRECTIVE_MISMATCH", lambda: h.registry.state(
        replace(combat, encounter_id=None), directive["directive_id"]))
    assert h.registry.record(combat, [h.receipt(directive, encounter_id=combat.encounter_id)]) == 1
    h.make_scope(combat.npc)
    assert_error(409, "RUN_BINDING_STALE", lambda: h.registry.state(combat, directive["directive_id"]))
    reset_runtime()
    assert_error(409, "SERVER_INSTANCE_CHANGED", lambda: h.registry.state(combat, directive["directive_id"]))


@pytest.mark.parametrize("failure", ["open", "write", "flush", "fsync"])
def test_failed_batch_marks_every_written_order_unknown_and_blocks_new_request_ids(h, monkeypatch, failure):
    orders = [h.issue()[1], h.issue()[1]]
    receipts = [h.receipt(d, result="executed", sequence=0) for d in orders]
    original_open, original_fsync = Path.open, directives.os.fsync

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def write(self, payload):
            if failure == "write":
                self.stream.write(payload[:20])
                raise OSError("simulated partial receipt write")
            return self.stream.write(payload)
        def flush(self):
            raise OSError("simulated receipt flush failure")

    def broken_open(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            if failure == "open":
                raise OSError("simulated receipt open failure")
            if failure in {"write", "flush"}:
                return PartialWriter(original_open(path, *args, **kwargs))
        return original_open(path, *args, **kwargs)

    def broken_fsync(fd):
        raise OSError("simulated receipt fsync failure")

    monkeypatch.setattr(Path, "open", broken_open)
    if failure == "fsync":
        monkeypatch.setattr(directives.os, "fsync", broken_fsync)
    request_store = IdempotencyStore()
    operation = lambda: h.registry.record(h.scope, receipts)
    assert_error(503, "REQUEST_OUTCOME_UNKNOWN", lambda: request_store.execute("original request", {}, operation))
    monkeypatch.setattr(Path, "open", original_open)
    monkeypatch.setattr(directives.os, "fsync", original_fsync)
    before = {path: path.read_bytes() for path in h.root.rglob("*.jsonl")}
    for directive in orders:
        state = h.registry.state(h.scope, directive["directive_id"])
        assert state["state"] == "unknown"
        assert state["terminal"] is False
        assert state["last_result"] is None
        assert state["receipt_count"] == 0
    # New outer IDs cannot bypass the per-order UNKNOWN barrier.
    assert_error(503, "STATE_UNAVAILABLE", operation)
    assert_error(503, "REQUEST_OUTCOME_UNKNOWN", lambda: request_store.execute("fresh request", {}, operation))
    assert_error(503, "REQUEST_OUTCOME_UNKNOWN", lambda: request_store.execute("original request", {}, operation))
    assert {path: path.read_bytes() for path in h.root.rglob("*.jsonl")} == before
    if failure == "fsync":
        assert len(h.records()) == 2  # Disk may contain data; no automatic replay is safe.


def test_unknown_is_not_pruned_or_reissued_after_normal_retention(h, monkeypatch):
    registry = DirectiveRegistry(max_entries=1, clock=lambda: h.now[0])
    request_id, directive = h.issue(registry=registry)
    original_fsync = directives.os.fsync
    def fail(fd):
        raise OSError("simulated fsync failure")
    monkeypatch.setattr(directives.os, "fsync", fail)
    assert_error(503, "STATE_UNAVAILABLE", lambda: registry.record(h.scope, [h.receipt(directive)]))
    monkeypatch.setattr(directives.os, "fsync", original_fsync)
    h.now[0] = 301
    assert registry.state(h.scope, directive["directive_id"])["state"] == "unknown"
    assert_error(503, "STATE_UNAVAILABLE", lambda: registry.register(h.scope, request_id, directive))
    assert_error(503, "STATE_UNAVAILABLE", lambda: h.issue(registry=registry))

def test_partial_append_seals_run_before_other_orders_can_corrupt_the_jsonl_tail(h, monkeypatch):
    _, first = h.issue()
    _, second = h.issue()
    original_open = Path.open

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def write(self, payload):
            self.stream.write(payload[:20])
            raise OSError("simulated incomplete JSONL tail")

    def partial_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return PartialWriter(stream) if path.suffix == ".jsonl" else stream

    monkeypatch.setattr(Path, "open", partial_open)
    assert_error(503, "STATE_UNAVAILABLE", lambda: h.registry.record(h.scope, [h.receipt(first)]))
    monkeypatch.setattr(Path, "open", original_open)
    path = next(h.root.rglob("*.jsonl"))
    partial = path.read_bytes()
    assert len(partial) == 20 and not partial.endswith(b"\n")
    h.now[0] = 301
    assert_error(503, "STATE_UNAVAILABLE", lambda: h.registry.record(h.scope, [h.receipt(second)]))
    assert_error(503, "STATE_UNAVAILABLE", lambda: h.issue())
    assert path.read_bytes() == partial
    assert h.registry.state(h.scope, first["directive_id"])["state"] == "unknown"
    assert h.registry.poisoned_runs == {h.scope.key}
    assert len(h.registry.poisoned_runs) <= len(h.registry.entries) <= h.registry.max_entries
    # A separate run has a separate file and may still accept feedback.
    other = h.make_scope()
    _, third = h.issue(scope=other)
    assert h.registry.record(other, [h.receipt(third)]) == 1
    assert path.read_bytes() == partial
    h.registry.clear()
    assert h.registry.entries == {} and h.registry.poisoned_runs == set()
    # Explicitly clearing volatile state never truncates/reconciles disk bytes.
    assert path.read_bytes() == partial
