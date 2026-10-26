"""Durable request/event identity and atomic SQL result tests, no providers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from app.persistence.database import Database, read_document, reset_database, write_document
from app.persistence.journal import DurableIdempotencyStore, operations, stage_active_result, stage_cancel_target
from app.persistence.uow import use_unit_of_work
from app.scoped.context import NpcScope, RequestScope, use_scope
from app.scoped.errors import ScopeError
from app.scoped.idempotency import NotStartedError
from app.scoped.runtime import get_runtime, reset_runtime
from app.scoped.timing import TimingBudget


@pytest.fixture
def sql(tmp_path, monkeypatch):
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    monkeypatch.setenv("AESIR_SCOPE_IDENTITY_BACKEND", "disabled")
    database = Database.from_url("sqlite:///" + str(tmp_path / "journal.sqlite"))
    database.initialize_schema()
    reset_database(database)
    reset_runtime()
    npc = NpcScope("aesir", uuid4(), uuid4(), "companion.alice")
    scope = RequestScope(npc, uuid4(), uuid4(), get_runtime().service_instance_id, uuid4(), uuid4())
    yield database, scope
    reset_database()
    reset_runtime()


def logical(scope, request_id, operation="chat"):
    return (*scope.key, operation, str(request_id))


def rejected(call, code):
    with pytest.raises(ScopeError) as error:
        call()
    assert error.value.code == code
    return error.value


def transaction(scope, result, *, changes=None, failure=False):
    with use_unit_of_work(scope) as unit:
        for namespace, payload in (changes or {}).items():
            write_document(namespace, scope.npc.key, payload, scope_parts=scope.npc.key)
        stage_active_result(result)
        if failure:
            unit.add_mutation(lambda connection: (_ for _ in ()).throw(RuntimeError("injected commit failure")))
        unit.commit()
    return result


def rows(database):
    with database.engine.connect() as connection:
        return connection.execute(select(operations)).mappings().all()


def test_result_and_business_state_commit_once_with_same_confirmed_version(sql):
    database, scope = sql
    store, request_id, calls = DurableIdempotencyStore(), uuid4(), []

    def action():
        calls.append(1)
        return transaction(scope, {"reply": "one"}, changes={"memory": {"n": 1}, "relationship": {"value": 25}})

    with use_scope(scope):
        first = store.execute(logical(scope, request_id), {"text": "hello"}, action, request_id=request_id)
        second = store.execute(logical(scope, request_id), {"text": "hello"}, action, request_id=request_id)
    assert first == second == {"reply": "one"}
    assert calls == [1]
    assert database.read_document("memory", scope.npc.key) == {"n": 1}
    assert database.read_document("relationship", scope.npc.key) == {"value": 25}
    row = rows(database)[0]
    assert row["state"] == "complete"
    assert row["confirmed_version"] == database.state_version(scope.npc.key) == 1


def test_payload_or_binding_change_cannot_reuse_persistent_id(sql):
    _, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()
    with use_scope(scope):
        store.execute(logical(scope, request_id), {"binding": "old"}, lambda: transaction(scope, {}))
        rejected(lambda: store.execute(logical(scope, request_id), {"binding": "new"}, lambda: None), "REQUEST_ID_CONFLICT")


def test_uncommitted_business_documents_roll_back_but_unknown_claim_survives(sql):
    database, scope = sql
    store, request_id, calls = DurableIdempotencyStore(), uuid4(), []

    def broken():
        calls.append(1)
        return transaction(scope, {}, changes={"memory": {"n": 1}, "relationship": {"value": 50}}, failure=True)

    with use_scope(scope):
        rejected(lambda: store.execute(logical(scope, request_id), {}, broken), "REQUEST_OUTCOME_UNKNOWN")
        rejected(lambda: store.execute(logical(scope, request_id), {}, broken), "REQUEST_OUTCOME_UNKNOWN")
    assert calls == [1]
    assert database.read_document("memory", scope.npc.key) is None
    assert database.read_document("relationship", scope.npc.key) is None
    assert database.state_version(scope.npc.key) == 0
    assert rows(database)[0]["state"] == "unknown"


def test_restart_keeps_completed_fact_but_never_replays_executable_result(sql):
    database, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()
    with use_scope(scope):
        store.execute(logical(scope, request_id), {}, lambda: transaction(scope, {"directive": "expired-action"}))
    reset_runtime()
    fresh = DurableIdempotencyStore()
    with use_scope(scope):
        rejected(lambda: fresh.execute(logical(scope, request_id), {}, lambda: pytest.fail("reexecuted")), "SERVER_INSTANCE_CHANGED")
    recovered = fresh.recover(scope.npc, scope.run_id, "chat", request_id)
    assert recovered["state"] == "complete"
    assert recovered["confirmed_version"] == 1
    assert "result" not in recovered and "directive" not in recovered
    assert len(rows(database)) == 1


def test_abandoned_running_owner_becomes_unknown_without_regeneration(sql):
    database, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()
    from app.scoped.idempotency import fingerprint
    with use_scope(scope):
        store._claim(tuple(logical(scope, request_id)), fingerprint({}), request_id)
    reset_runtime()
    fresh = DurableIdempotencyStore()
    # Recovery itself is read-only, but reports the abandoned process correctly.
    assert fresh.recover(scope.npc, scope.run_id, "chat", request_id)["state"] == "unknown"
    assert rows(database)[0]["state"] == "running"
    with use_scope(scope):
        rejected(lambda: fresh.execute(logical(scope, request_id), {}, lambda: pytest.fail("reclaimed")), "REQUEST_OUTCOME_UNKNOWN")
    assert rows(database)[0]["state"] == "unknown"


def test_nested_event_and_http_result_share_one_business_transaction(sql):
    database, scope = sql
    requests, events = DurableIdempotencyStore(), DurableIdempotencyStore("event")
    request_id, event_id = uuid4(), uuid4()

    def action():
        with use_unit_of_work(scope) as unit:
            def event():
                write_document("relationship", scope.npc.key, {"value": 30}, scope_parts=scope.npc.key)
                return {"event": "confirmed"}
            result = events.execute((*scope.key, "", str(event_id)), {"event": str(event_id)}, event)
            output = {"event_result": result}
            stage_active_result(output)
            unit.commit()
            return output

    with use_scope(scope):
        response = requests.execute(logical(scope, request_id, "event"), {}, action)
    assert response == {"event_result": {"event": "confirmed"}}
    records = rows(database)
    assert len(records) == 2
    assert {row["state"] for row in records} == {"complete"}
    assert {row["confirmed_version"] for row in records} == {1}
    assert database.state_version(scope.npc.key) == 1


def test_nested_event_is_not_left_complete_if_outer_transaction_fails(sql):
    database, scope = sql
    requests, events = DurableIdempotencyStore(), DurableIdempotencyStore("event")
    request_id, event_id = uuid4(), uuid4()

    def action():
        with use_unit_of_work(scope):
            events.execute((*scope.key, "", str(event_id)), {}, lambda: {"ok": True})
            write_document("memory", scope.npc.key, {"n": 1}, scope_parts=scope.npc.key)
            raise RuntimeError("before final commit")

    with use_scope(scope):
        rejected(lambda: requests.execute(logical(scope, request_id, "event"), {}, action), "REQUEST_OUTCOME_UNKNOWN")
    assert {row["state"] for row in rows(database)} == {"unknown"}
    assert database.read_document("memory", scope.npc.key) is None


def test_not_started_capacity_rejection_releases_only_untouched_claim(sql):
    database, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()
    def reject():
        raise NotStartedError(503, "REQUEST_QUEUE_FULL", "not admitted")
    with use_scope(scope):
        rejected(lambda: store.execute(logical(scope, request_id), {}, reject, propagate_not_started=True), "REQUEST_QUEUE_FULL")
        assert rows(database) == []
        assert store.execute(logical(scope, request_id), {}, lambda: transaction(scope, {"ok": True})) == {"ok": True}


def test_prearrival_cancel_survives_restart_and_does_not_require_original_payload(sql):
    database, scope = sql
    target_id = uuid4()
    with use_unit_of_work(scope) as unit:
        stage_cancel_target(scope, "chat", target_id)
        unit.commit()
    reset_runtime()
    store = DurableIdempotencyStore()
    with use_scope(scope):
        rejected(lambda: store.execute(logical(scope, target_id), {"new": "binding"}, lambda: pytest.fail("resurrected")), "REQUEST_CANCELLED")
    assert store.recover(scope.npc, scope.run_id, "chat", target_id)["state"] == "cancelled"
    assert rows(database) == []


def test_duplicate_running_owner_single_flies_generation(sql):
    _, scope = sql
    store, request_id, calls = DurableIdempotencyStore(), uuid4(), []
    entered, release = Event(), Event()

    def action():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return transaction(scope, {"ok": True})

    def submit():
        with use_scope(scope):
            return store.execute(logical(scope, request_id), {}, action)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit)
        assert entered.wait(2)
        second = pool.submit(submit)
        release.set()
        assert first.result(timeout=3) == second.result(timeout=3) == {"ok": True}
    assert calls == [1]


def test_losing_replay_clock_rejects_instead_of_refreshing_old_result(sql):
    _, scope = sql
    request_id, clock = uuid4(), [10.0]
    timing = lambda: TimingBudget(dict(capture_age_ms=0, request_age_ms=0,
        max_snapshot_age_ms=1000, max_request_age_ms=1000), clock=lambda: clock[0])
    store = DurableIdempotencyStore()
    with use_scope(scope):
        store.execute(logical(scope, request_id), {}, lambda: transaction(scope, {}), timing=timing())
        store.clear()
        rejected(lambda: store.execute(logical(scope, request_id), {}, lambda: pytest.fail("reexecuted"), timing=timing()), "REQUEST_EXPIRED")


# ---------------------------------------------------------------------------
# 阶段 1：read_status —— coordinator.status() 内存 miss 时的跨进程 fallback
# ---------------------------------------------------------------------------


def test_read_status_returns_completed_record_from_journal(sql):
    """请求在本进程完成；read_status 应返回 completed 记录（含耗时字段）。"""
    _, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()
    with use_scope(scope):
        store.execute(logical(scope, request_id), {}, lambda: transaction(scope, {"ok": True}))

    record = store.read_status(scope, "chat", str(request_id))
    assert record is not None
    assert record["state"] == "completed"
    assert record["target_request_id"] == str(request_id)
    assert record["cancel_requested"] is False
    assert record["total_ms"] >= 0


def test_read_status_returns_none_for_unknown_request(sql):
    """journal 里没有该请求（也没有 cancel tombstone）→ 返回 None（调用方 404）。"""
    _, scope = sql
    store = DurableIdempotencyStore()
    assert store.read_status(scope, "chat", str(uuid4())) is None


def test_read_status_detects_cancel_tombstone(sql):
    """请求从未执行但有 cancel tombstone → 返回 cancelled 记录。"""
    _, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()
    with use_scope(scope):
        with use_unit_of_work(scope) as unit:
            stage_cancel_target(scope, "chat", str(request_id))
            unit.commit()
    record = store.read_status(scope, "chat", str(request_id))
    assert record is not None
    assert record["state"] == "cancelled"
    assert record["cancel_requested"] is True
    assert record["reason_code"] == "REQUEST_CANCELLED"


def test_read_status_reports_abandoned_running_as_unknown(sql):
    """running 请求的 owner 不是本实例 → 报 unknown（与 recover 同口径）。"""
    database, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()

    # 直接插一行 running 状态、owner 为别的实例（模拟 worker A 崩溃）。
    key = logical(scope, request_id)
    identity = store._identity(key)
    with database.engine.begin() as connection:
        connection.execute(insert(operations).values(
            identity_hash=identity, kind="request", key_parts=list(key),
            scope_parts=list(scope.npc.key), request_id=str(request_id),
            fingerprint="fp", owner_instance="worker-a-crashed",
            state="running", created_at=1000.0,
        ))

    # 本实例读：running 且 owner 不是本实例 → unknown。
    record = store.read_status(scope, "chat", str(request_id))
    assert record is not None
    assert record["state"] == "unknown"
    assert record["reason_code"] == "REQUEST_OUTCOME_UNKNOWN"


def test_read_status_mismatched_scope_parts_raises_conflict(sql):
    """row 存在但 scope_parts 与查询 npc 不一致 → 409（防御性检查）。"""
    database, scope = sql
    store, request_id = DurableIdempotencyStore(), uuid4()

    # 正常完成一行。
    with use_scope(scope):
        store.execute(logical(scope, request_id), {}, lambda: transaction(scope, {}))

    # 篡改 row 的 scope_parts（模拟跨 scope 碰撞）。
    with database.engine.begin() as connection:
        connection.execute(operations.update().where(
            operations.c.identity_hash == store._identity(logical(scope, request_id))
        ).values(scope_parts=["tampered", "scope"]))

    from app.scoped.errors import ScopeError
    with pytest.raises(ScopeError) as exc:
        store.read_status(scope, "chat", str(request_id))
    assert exc.value.status_code == 409
    assert exc.value.code == "REQUEST_ID_CONFLICT"
