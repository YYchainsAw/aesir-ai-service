"""v0.4 身份格式、黄金请求和上下文隔离，不改旧协议语义。"""

import asyncio
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.scoped.context import NpcScope, RequestScope, current_scope, use_scope
from app.schemas.agent_step import AgentStepRequest
from app.schemas.scoped import (
    BindRunRequest, EncounterControlRequest, EndRunRequest, ScopedAgentRequest,
    ScopedChatRequest, ScopedExecutionRequest, ScopedResetRequest,
    ScopedWorldEventRequest, TimingInput,
)

GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden" / "scoped"


def load(name="agent_step_request.json"):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename,model", [
    ("run_bind_request.json", BindRunRequest),
    ("run_end_request.json", EndRunRequest),
    ("encounter_begin_request.json", EncounterControlRequest),
    ("agent_step_request.json", ScopedAgentRequest),
    ("chat_request.json", ScopedChatRequest),
    ("world_event_request.json", ScopedWorldEventRequest),
    ("executions_request.json", ScopedExecutionRequest),
    ("memory_reset_request.json", ScopedResetRequest),
])
def test_golden_requests_validate_and_roundtrip(filename, model):
    request = model.model_validate(load(filename))
    assert model.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("field,value", [
    ("protocol_version", "0.3"), ("request_id", "free-text"),
    ("save_id", "../../someone"), ("run_id", "run.default"),
    ("session_id", "a" * 128), ("encounter_id", "boss"),
    ("companion_id", "../../companion.alice"), ("player_id", str(uuid4())),
    ("game_id", "another-game"),
])
def test_new_identity_rejects_untrusted_or_invalid_fields(field, value):
    payload = load()
    payload[field] = value
    with pytest.raises(ValidationError):
        ScopedAgentRequest.model_validate(payload)


def test_session_defaults_to_exact_run_uuid_and_keeps_explicit_uuid():
    payload = load()
    assert str(ScopedAgentRequest.model_validate(payload).session_id) == payload["run_id"]
    payload["session_id"] = str(uuid4())
    assert str(ScopedAgentRequest.model_validate(payload).session_id) == payload["session_id"]


@pytest.mark.parametrize("value", [-1, 1.5, float("inf"), float("nan"), True, "100"])
@pytest.mark.parametrize("field", ["capture_age_ms", "request_age_ms", "max_snapshot_age_ms", "max_request_age_ms"])
def test_timing_rejects_nonfinite_negative_and_coerced_numbers(field, value):
    payload = load()["timing"]
    payload[field] = value
    with pytest.raises(ValidationError):
        TimingInput.model_validate(payload)


@pytest.mark.parametrize("field,value", [
    ("snapshot_id", "snapshot-free-text"),
    ("captured_at", "2026-10-21T12:00:00"),
    ("captured_at", "2026-10-21T12:00:00+08:00"),
])
def test_scoped_snapshot_requires_uuid_and_utc_timezone(field, value):
    payload = load()
    payload["world_context"][field] = value
    with pytest.raises(ValidationError):
        ScopedAgentRequest.model_validate(payload)


def test_scoped_validation_does_not_strengthen_legacy_snapshot():
    payload = load()
    legacy = {key: payload[key] for key in ("request_id", "companion_id", "world_context", "text")}
    legacy["protocol_version"] = "0.3"
    legacy["world_context"]["snapshot_id"] = "old-snapshot"
    legacy["world_context"]["captured_at"] = "2026-10-21T12:00:00"
    assert AgentStepRequest.model_validate(legacy).world_context.snapshot_id == "old-snapshot"


def test_snapshot_companion_and_request_age_must_match():
    payload = load()
    payload["world_context"]["companion"]["id"] = "companion.other"
    with pytest.raises(ValidationError):
        ScopedAgentRequest.model_validate(payload)
    payload = load()
    payload["timing"]["request_age_ms"] = 21
    with pytest.raises(ValidationError):
        ScopedAgentRequest.model_validate(payload)


def test_battle_event_requires_combat_context_and_encounter():
    payload = load("world_event_request.json")
    payload["event"]["event_type"] = "boss_defeated"
    with pytest.raises(ValidationError):
        ScopedWorldEventRequest.model_validate(payload)


def test_encounter_end_requires_current_encounter_without_replacement():
    payload = load("encounter_begin_request.json")
    payload["op"] = "end"
    with pytest.raises(ValidationError):
        EncounterControlRequest.model_validate(payload)
    payload["expected_encounter_id"] = payload.pop("encounter_id")
    assert EncounterControlRequest.model_validate(payload).op == "end"


def test_control_cas_requires_explicit_expected_null():
    payload = load("run_bind_request.json")
    payload.pop("expected_run_id")
    with pytest.raises(ValidationError):
        BindRunRequest.model_validate(payload)


def test_receipt_requires_same_companion_encounter_and_explicit_v04():
    payload = load("executions_request.json")
    payload["receipt"]["agent_id"] = "companion.other"
    with pytest.raises(ValidationError):
        ScopedExecutionRequest.model_validate(payload)
    payload = load("executions_request.json")
    payload["receipt"]["protocol_version"] = "0.2"
    with pytest.raises(ValidationError):
        ScopedExecutionRequest.model_validate(payload)
    payload = load("executions_request.json")
    payload["encounter_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        ScopedExecutionRequest.model_validate(payload)


def test_receipt_single_or_nonempty_batch_are_exclusive():
    payload = load("executions_request.json")
    request = ScopedExecutionRequest.model_validate(payload)
    assert len(request.all_receipts) == 1
    payload["receipts"] = [deepcopy(payload["receipt"])]
    with pytest.raises(ValidationError):
        ScopedExecutionRequest.model_validate(payload)
    payload.pop("receipt")
    assert len(ScopedExecutionRequest.model_validate(payload).all_receipts) == 1
    payload["receipts"] = []
    with pytest.raises(ValidationError):
        ScopedExecutionRequest.model_validate(payload)


def make_scope(player_id=None):
    npc = NpcScope("aesir", player_id or uuid4(), uuid4(), "companion.alice")
    return RequestScope(npc, uuid4(), uuid4(), uuid4(), uuid4(), uuid4())


def test_scope_is_immutable_canonical_and_restored_after_exception():
    scope = make_scope()
    assert scope.npc.path_parts == scope.npc.key
    assert scope.npc.key[1] == str(scope.npc.player_id)
    assert scope.key == (*scope.npc.key, str(scope.run_id))
    assert current_scope() is None
    with pytest.raises(FrozenInstanceError):
        scope.run_id = uuid4()
    with use_scope(scope):
        assert current_scope() is scope
        with pytest.raises(ValueError), use_scope(make_scope()):
            raise ValueError("test")
        assert current_scope() is scope
    assert current_scope() is None


def test_async_tasks_do_not_share_their_request_scope():
    scopes = [make_scope(), make_scope()]

    async def observe(scope):
        with use_scope(scope):
            await asyncio.sleep(0)
            return current_scope()

    async def run():
        return await asyncio.gather(*(observe(scope) for scope in scopes))

    assert asyncio.run(run()) == scopes
    assert current_scope() is None


@pytest.mark.parametrize("filename,model_name", [
    ("agent_step_none_response.json", "ScopedAgentResponse"),
    ("agent_step_directive_response.json", "ScopedAgentResponse"),
    ("chat_response.json", "ScopedChatResponse"),
    ("world_event_response.json", "ScopedWorldEventResponse"),
    ("executions_response.json", "ScopedExecutionResponse"),
    ("memory_reset_response.json", "ScopedResetResponse"),
    ("context_bound_response.json", "ScopedContextResponse"),
    ("console_memory_response.json", "ScopedMemoryViewResponse"),
    ("console_state_response.json", "ScopedConsoleStateResponse"),
    ("context_unbound_response.json", "ScopedContextResponse"),
    ("run_bind_response.json", "ScopedControlResponse"),
    ("run_end_response.json", "ScopedControlResponse"),
    ("encounter_begin_response.json", "ScopedControlResponse"),
])
def test_golden_responses_validate_and_roundtrip(filename, model_name):
    from app.schemas import scoped

    model = getattr(scoped, model_name)
    response = model.model_validate(load(filename))
    assert model.model_validate_json(response.model_dump_json()) == response


def test_new_response_rejects_legacy_directive_and_mismatched_action():
    from app.schemas.scoped import ScopedAgentResponse

    payload = load("agent_step_directive_response.json")
    payload["directive"]["protocol_version"] = "0.3"
    with pytest.raises(ValidationError):
        ScopedAgentResponse.model_validate(payload)
    payload = load("agent_step_none_response.json")
    payload["action"] = "directive"
    with pytest.raises(ValidationError):
        ScopedAgentResponse.model_validate(payload)


def test_new_response_requires_scope_association_and_fixed_version():
    from app.schemas.scoped import ScopedChatResponse

    payload = load("chat_response.json")
    payload["protocol_version"] = "0.1"
    with pytest.raises(ValidationError):
        ScopedChatResponse.model_validate(payload)
    payload = load("chat_response.json")
    del payload["run_binding_id"]
    with pytest.raises(ValidationError):
        ScopedChatResponse.model_validate(payload)
