"""Run/encounter lifecycle has one CAS owner per player save."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest

from app.scoped.context import NpcScope, RequestScope
from app.scoped.errors import ScopeError
from app.scoped.runtime import ScopedRuntime


@pytest.fixture
def npc():
    return NpcScope("aesir", uuid4(), uuid4(), "companion.alice")


def bind(runtime, npc, **changes):
    values = dict(request_id=uuid4(), service_instance_id=runtime.service_instance_id,
                  expected_control_revision=0, expected_run_id=None, run_id=uuid4())
    values.update(changes)
    return runtime.bind_run(npc, **values)


def scope(npc, binding, **changes):
    values = dict(npc=npc, run_id=binding["run_id"], session_id=uuid4(),
                  service_instance_id=binding["service_instance_id"],
                  run_binding_id=binding["run_binding_id"], memory_epoch=uuid4())
    values.update(changes)
    return RequestScope(**values)


def end(runtime, npc, binding, **changes):
    values = dict(request_id=uuid4(), service_instance_id=binding["service_instance_id"],
                  run_id=binding["run_id"], run_binding_id=binding["run_binding_id"],
                  expected_control_revision=binding["control_revision"])
    values.update(changes)
    return runtime.end_run(npc, **values)


def encounter(runtime, npc, binding, **changes):
    values = dict(request_id=uuid4(), service_instance_id=binding["service_instance_id"],
                  run_id=binding["run_id"], run_binding_id=binding["run_binding_id"],
                  op="begin", expected_encounter_revision=0, expected_encounter_id=None,
                  encounter_id=uuid4())
    values.update(changes)
    return runtime.control_encounter(npc, **values)


def test_lookup_and_ordinary_validation_never_activate_a_run(npc):
    runtime = ScopedRuntime()
    current = runtime.context(npc)
    assert current["run_id"] is None
    assert current["control_revision"] == 0
    unbound = dict(current, run_id=uuid4(), run_binding_id=uuid4())
    with pytest.raises(ScopeError) as error:
        runtime.validate_binding(scope(npc, unbound))
    assert error.value.code == "RUN_BINDING_STALE"
    assert runtime.context(npc) == current


def test_binding_can_be_reused_after_live_reconnect_and_is_shared_by_save(npc):
    runtime = ScopedRuntime()
    binding = bind(runtime, npc)
    another_npc = replace(npc, companion_id="companion.bob")
    assert runtime.context(another_npc) == binding
    runtime.validate_binding(scope(another_npc, binding))
    assert runtime.context(npc)["run_binding_id"] == binding["run_binding_id"]


def test_distinct_players_and_saves_have_independent_current_runs(npc):
    runtime = ScopedRuntime()
    first = bind(runtime, npc)
    other_player = replace(npc, player_id=uuid4())
    other_save = replace(npc, save_id=uuid4())
    assert bind(runtime, other_player)["control_revision"] == 1
    assert bind(runtime, other_save)["control_revision"] == 1
    runtime.validate_binding(scope(npc, first))


def test_concurrent_first_bind_has_exactly_one_cas_winner(npc):
    runtime = ScopedRuntime()

    def attempt():
        try:
            return bind(runtime, npc)
        except ScopeError as error:
            return error

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: attempt(), range(8)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert {result.code for result in results if isinstance(result, ScopeError)} == {"RUN_CAS_CONFLICT"}
    assert runtime.context(npc)["control_revision"] == 1


def test_control_retries_keep_binding_and_end_revision(npc):
    runtime = ScopedRuntime()
    request_id, run_id = uuid4(), uuid4()
    binding = bind(runtime, npc, request_id=request_id, run_id=run_id)
    assert bind(runtime, npc, request_id=request_id, run_id=run_id) == binding
    end_id = uuid4()
    ended = end(runtime, npc, binding, request_id=end_id)
    assert end(runtime, npc, binding, request_id=end_id) == ended
    assert ended["control_revision"] == 2
    assert ended["run_id"] is None


def test_empty_active_empty_does_not_allow_stale_cas_again(npc):
    runtime = ScopedRuntime()
    binding = bind(runtime, npc)
    end(runtime, npc, binding)
    with pytest.raises(ScopeError) as error:
        bind(runtime, npc)
    assert error.value.code == "RUN_CAS_CONFLICT"
    new = bind(runtime, npc, expected_control_revision=2)
    assert new["control_revision"] == 3
    with pytest.raises(ScopeError) as error:
        runtime.validate_binding(scope(npc, binding))
    assert error.value.code == "RUN_BINDING_STALE"


def test_replaced_binding_and_cached_original_bind_are_not_revived(npc):
    runtime = ScopedRuntime()
    first_id, first_run = uuid4(), uuid4()
    first = bind(runtime, npc, request_id=first_id, run_id=first_run)
    second = bind(runtime, npc, expected_control_revision=1, expected_run_id=first_run)
    assert second["run_binding_id"] != first["run_binding_id"]
    with pytest.raises(ScopeError) as error:
        bind(runtime, npc, request_id=first_id, run_id=first_run)
    assert error.value.code == "RUN_BINDING_STALE"
    with pytest.raises(ScopeError) as error:
        runtime.validate_binding(scope(npc, first))
    assert error.value.code == "RUN_BINDING_STALE"


def test_restart_rejects_old_controls_and_binding_and_requires_explicit_rebind(npc):
    previous, current = ScopedRuntime(), ScopedRuntime()
    binding = bind(previous, npc)
    assert previous.service_instance_id != current.service_instance_id
    with pytest.raises(ScopeError) as error:
        current.validate_binding(scope(npc, binding))
    assert error.value.code == "SERVER_INSTANCE_CHANGED"
    with pytest.raises(ScopeError) as error:
        bind(current, npc, service_instance_id=previous.service_instance_id)
    assert error.value.code == "SERVER_INSTANCE_CHANGED"
    rebound = bind(current, npc, run_id=binding["run_id"])
    assert rebound["run_binding_id"] != binding["run_binding_id"]
    current.validate_binding(scope(npc, rebound))


def test_explicit_encounter_cas_and_duplicate_end_do_not_end_a_new_encounter(npc):
    runtime = ScopedRuntime()
    binding = bind(runtime, npc)
    encounter_id, begin_id, end_id = uuid4(), uuid4(), uuid4()
    begun = encounter(runtime, npc, binding, request_id=begin_id, encounter_id=encounter_id)
    assert encounter(runtime, npc, binding, request_id=begin_id, encounter_id=encounter_id) == begun
    runtime.validate_binding(scope(npc, binding, encounter_id=encounter_id))
    ended = encounter(runtime, npc, binding, request_id=end_id, op="end",
                      expected_encounter_revision=1, expected_encounter_id=encounter_id,
                      encounter_id=None)
    assert ended["encounter_revision"] == 2
    assert encounter(runtime, npc, binding, request_id=end_id, op="end",
                     expected_encounter_revision=1, expected_encounter_id=encounter_id,
                     encounter_id=None) == ended
    next_encounter = encounter(runtime, npc, binding, expected_encounter_revision=2)
    with pytest.raises(ScopeError) as error:
        encounter(runtime, npc, binding, request_id=end_id, op="end",
                  expected_encounter_revision=1, expected_encounter_id=encounter_id,
                  encounter_id=None)
    assert error.value.code == "ENCOUNTER_CAS_CONFLICT"
    assert runtime.context(npc)["encounter_id"] == next_encounter["encounter_id"]


def test_ordinary_requests_never_create_encounters_and_ended_encounter_is_stale(npc):
    runtime = ScopedRuntime()
    binding = bind(runtime, npc)
    encounter_id = uuid4()
    with pytest.raises(ScopeError) as error:
        runtime.validate_binding(scope(npc, binding, encounter_id=encounter_id))
    assert error.value.code == "ENCOUNTER_INACTIVE"
    assert runtime.context(npc)["encounter_id"] is None
    begun = encounter(runtime, npc, binding, encounter_id=encounter_id)
    encounter(runtime, npc, binding, op="end", expected_encounter_revision=1,
              expected_encounter_id=encounter_id, encounter_id=None)
    with pytest.raises(ScopeError) as error:
        runtime.validate_binding(scope(npc, binding, encounter_id=encounter_id))
    assert error.value.code == "ENCOUNTER_INACTIVE"
    assert begun["encounter_revision"] == 1


def test_guard_serializes_final_write_with_run_control(npc):
    runtime = ScopedRuntime()
    binding = bind(runtime, npc)
    started, finished = Event(), Event()

    def control():
        started.set()
        result = end(runtime, npc, binding)
        finished.set()
        return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        with runtime.guard(scope(npc, binding)):
            future = executor.submit(control)
            assert started.wait(2)
            assert not finished.wait(0.03)
        assert future.result(2)["run_id"] is None
    with pytest.raises(ScopeError) as error:
        with runtime.guard(scope(npc, binding)):
            pytest.fail("stale generation reached commit body")
    assert error.value.code == "RUN_BINDING_STALE"


def test_state_capacity_is_bounded(npc):
    runtime = ScopedRuntime(max_scopes=1)
    runtime.context(npc)
    with pytest.raises(ScopeError) as error:
        runtime.context(replace(npc, save_id=uuid4()))
    assert error.value.code == "STATE_UNAVAILABLE"
