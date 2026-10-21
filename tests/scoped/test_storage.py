"""状态归属、持久 epoch 与延迟完成的重置屏障。"""
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4
import json

import pytest

from app.scoped.context import NpcScope, RequestScope, use_scope
from app.scoped.errors import ScopeError
from app.scoped.runtime import reset_runtime
from app.scoped import storage
from app.schemas.memory import MemoryEntry
from app.services.memory.store import get_memory_store, reset_memory_stores
from app.services.relationship.state import get_relationship_store
from app.services.companion.session_memory import get_session_memory
from app.services.console.runtime_state import record_observation, get_observation
from app.services.companion.dialogue_signals import record_turn_signal


@pytest.fixture
def scopes():
    runtime = reset_runtime()
    def make(npc=None, session_id=None, replace_run=False):
        npc = npc or NpcScope("aesir", uuid4(), uuid4(), "companion.alice")
        control = runtime.context(npc)
        if control["run_id"] is None or replace_run:
            control = runtime.bind_run(
                npc, request_id=uuid4(), service_instance_id=runtime.service_instance_id,
                expected_control_revision=control["control_revision"],
                expected_run_id=control["run_id"], run_id=uuid4())
        return RequestScope(npc, control["run_id"], session_id or uuid4(),
                            runtime.service_instance_id, control["run_binding_id"],
                            storage.memory_epoch(npc))
    return make


def test_long_term_partition_and_reload(scopes):
    first, other = scopes(), scopes()
    assert first.npc.companion_id == other.npc.companion_id
    with use_scope(first):
        store = get_memory_store(first.npc.companion_id)
        store.record_fact(MemoryEntry(content="Only the first player knows this"))
        first_path = store._path
    with use_scope(other):
        store = get_memory_store(other.npc.companion_id)
        assert not store.snapshot().archive
        assert store._path != first_path
    reset_memory_stores()
    with use_scope(first):
        assert len(get_memory_store(first.npc.companion_id).snapshot().archive) == 1
    assert storage.memory_epoch(first.npc) == first.memory_epoch


def test_run_and_full_uuid_session_partition(scopes):
    first = scopes()
    store = get_session_memory(10)
    with use_scope(first):
        store.record(str(first.session_id), "question", "answer", first.npc.companion_id)
        record_observation(first.npc.companion_id, scene="fishing")
    second_session = replace(first, session_id=uuid4())
    with use_scope(second_session):
        assert not store.history(str(second_session.session_id), second_session.npc.companion_id)
    next_run = scopes(first.npc, first.session_id, replace_run=True)
    with use_scope(next_run):
        assert not store.history(str(next_run.session_id), next_run.npc.companion_id)
        assert not get_observation(next_run.npc.companion_id).scene


def test_reset_preserves_relationship_and_other_player(scopes):
    first, other = scopes(), scopes()
    sessions = get_session_memory(10)
    with use_scope(first):
        get_memory_store(first.npc.companion_id).record_fact(MemoryEntry(content="forget me"))
        relation = get_relationship_store(first.npc.companion_id)
        relation.reset()
        relation_before = relation._path.read_bytes()
        sessions.record(str(first.session_id), "one", "reply", first.npc.companion_id)
    with use_scope(other):
        get_memory_store(other.npc.companion_id).record_fact(MemoryEntry(content="keep me"))
        sessions.record(str(other.session_id), "two", "reply", other.npc.companion_id)
    result = storage.reset_memory(first.npc, first.memory_epoch)
    assert result["cleared_sessions"] == 1
    assert result["memory_epoch"] != first.memory_epoch
    assert relation._path.read_bytes() == relation_before
    fresh = replace(first, memory_epoch=result["memory_epoch"])
    with use_scope(fresh):
        assert not get_memory_store(fresh.npc.companion_id).snapshot().archive
        assert not sessions.history(str(fresh.session_id), fresh.npc.companion_id)
    with use_scope(other):
        assert len(get_memory_store(other.npc.companion_id).snapshot().archive) == 1
        assert len(sessions.history(str(other.session_id), other.npc.companion_id)) == 1


def test_delayed_completion_cannot_write_after_reset(scopes):
    first = scopes()
    started, finish = Event(), Event()
    outcome = []
    with use_scope(first):
        store = get_memory_store(first.npc.companion_id)
    def delayed():
        with use_scope(first):
            started.set()
            assert finish.wait(5)
            try:
                store.record_fact(MemoryEntry(content="stale completion"))
            except ScopeError as error:
                outcome.append(error.code)
    worker = Thread(target=delayed)
    worker.start()
    assert started.wait(5)
    result = storage.reset_memory(first.npc, first.memory_epoch)
    finish.set()
    worker.join(5)
    assert not worker.is_alive()
    assert outcome == ["MEMORY_EPOCH_STALE"]
    with use_scope(replace(first, memory_epoch=result["memory_epoch"])):
        assert not get_memory_store(first.npc.companion_id).snapshot().archive


def test_corrupt_or_missing_epoch_never_recovers_backup(scopes):
    first = scopes()
    path = storage.memory_path(first.npc)
    backup = path.with_suffix(".json.bak")
    backup.write_bytes(path.read_bytes())
    storage.reset_memory(first.npc, first.memory_epoch)
    path.unlink()
    with pytest.raises(ScopeError, match="unavailable") as error:
        storage.memory_epoch(first.npc)
    assert error.value.code == "STATE_UNAVAILABLE"
    path.write_text('{"memory_epoch":"broken"}', encoding="utf-8")
    with pytest.raises(ScopeError):
        storage.memory_epoch(first.npc)


def test_failed_reset_does_not_clear_sessions_or_advance_epoch(scopes, monkeypatch):
    first = scopes()
    sessions = get_session_memory(10)
    with use_scope(first):
        sessions.record(str(first.session_id), "keep", "reply", first.npc.companion_id)
    def fail(*args, **kwargs):
        raise storage.unavailable()
    monkeypatch.setattr(storage, "write_memory_document", fail)
    with pytest.raises(ScopeError):
        storage.reset_memory(first.npc, first.memory_epoch)
    assert storage.memory_epoch(first.npc) == first.memory_epoch
    with use_scope(first):
        assert len(sessions.history(str(first.session_id), first.npc.companion_id)) == 1


def test_expired_generation_cannot_commit(scopes):
    from app.scoped.timing import TimingBudget, use_budget
    first = scopes()
    now = [0.0]
    budget = TimingBudget(dict(capture_age_ms=0, request_age_ms=0,
                              max_snapshot_age_ms=100, max_request_age_ms=100),
                          clock=lambda: now[0])
    with use_scope(first), use_budget(budget):
        store = get_memory_store(first.npc.companion_id)
        now[0] = 0.2
        with pytest.raises(ScopeError) as error:
            store.record_fact(MemoryEntry(content="too late"))
        assert error.value.code == "SNAPSHOT_EXPIRED"
        assert not store.snapshot().archive


def test_legacy_directory_is_not_claimed(scopes, monkeypatch, tmp_path):
    root = tmp_path / "new-memory"
    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(root))
    legacy = root / "aesir" / "companion.alice" / "memory.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"archive": [MemoryEntry(content="unowned legacy").model_dump(mode="json")]}))
    first = scopes()
    with use_scope(first):
        assert not get_memory_store(first.npc.companion_id).snapshot().archive
    assert "unowned legacy" in legacy.read_text()


def test_final_turn_after_reset_commits_no_side_effect(scopes):
    from app.schemas.companion_dialogue import CompanionDialogueRequest, CompanionDialogueResponse
    from app.services.companion.dialogue_service import _record_turn
    first = scopes()
    result = storage.reset_memory(first.npc, first.memory_epoch)
    request = CompanionDialogueRequest(text="I really care about fishing", companion_id=first.npc.companion_id,
                                       session_id=str(first.session_id))
    response = CompanionDialogueResponse(companion_id=first.npc.companion_id,
                                         reply_text="fishing", emotion_id="emotion.calm",
                                         gesture_id="gesture.none", facial_expression_id="face.neutral")
    with use_scope(first), pytest.raises(ScopeError) as error:
        _record_turn(request, response, topics=["fishing"], relationship_signal="care", game_id="aesir")
    assert error.value.code == "MEMORY_EPOCH_STALE"
    fresh = replace(first, memory_epoch=result["memory_epoch"])
    with use_scope(fresh):
        assert not get_session_memory(10).history(str(fresh.session_id), fresh.npc.companion_id)
        assert not get_memory_store(fresh.npc.companion_id).snapshot().impressions
        assert not get_observation(fresh.npc.companion_id).emotion_id


def test_replaced_run_cannot_commit(scopes):
    first = scopes()
    with use_scope(first):
        store = get_memory_store(first.npc.companion_id)
    scopes(first.npc, replace_run=True)
    with use_scope(first), pytest.raises(ScopeError) as error:
        store.record_fact(MemoryEntry(content="old run"))
    assert error.value.code == "RUN_BINDING_STALE"


def test_logs_partition_preserved_on_reset_and_scoped_failures_propagate(scopes, monkeypatch, tmp_path):
    from app.services.companion.agent_step_signals import record_agent_step
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path / "steps"))
    first, other = scopes(), scopes()
    for scope in (first, other):
        with use_scope(scope):
            record_agent_step(scope.npc.companion_id, scene="exploration")
    logs = list((tmp_path / "steps").rglob("*.jsonl"))
    assert len(logs) == 2
    before = {path: path.read_bytes() for path in logs}
    for path in logs:
        record = json.loads(path.read_text())
        assert str(record["player_id"]) in str(path)
        assert str(record["run_id"]) in str(path)
    result = storage.reset_memory(first.npc, first.memory_epoch)
    assert {path: path.read_bytes() for path in logs} == before
    original = Path.open
    def fail_log(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise OSError("test disk failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_log)
    fresh = replace(first, memory_epoch=result["memory_epoch"])
    with use_scope(fresh), pytest.raises(ScopeError) as error:
        record_agent_step(fresh.npc.companion_id)
    assert error.value.code == "STATE_UNAVAILABLE"


@pytest.mark.parametrize("dimension", ["game_id", "player_id", "save_id", "companion_id"])
def test_each_long_term_scope_dimension_is_independent(scopes, dimension):
    first = scopes()
    value = "another-game" if dimension == "game_id" else (
        "companion.bruno" if dimension == "companion_id" else uuid4())
    other = scopes(replace(first.npc, **{dimension: value}))
    with use_scope(first):
        get_memory_store(first.npc.companion_id, game_id=first.npc.game_id).record_fact(MemoryEntry(content="first scope"))
    with use_scope(other):
        assert not get_memory_store(other.npc.companion_id, game_id=other.npc.game_id).snapshot().archive
