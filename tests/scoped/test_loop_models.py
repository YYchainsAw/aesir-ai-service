"""Execution-loop models preserve scoped identity and read-only boundaries."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.loop import (
    ScopedCancelRequest,
    ScopedCancelResponse,
    ScopedDirectiveStateResponse,
    ScopedRequestStatusResponse,
)

GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden" / "loop"
MODELS = [
    ("cancel_request.json", ScopedCancelRequest),
    ("cancel_response.json", ScopedCancelResponse),
    ("request_status_running.json", ScopedRequestStatusResponse),
    ("directive_issued.json", ScopedDirectiveStateResponse),
]
GOLDENS = [
    *MODELS[:2],
    *[
        (f"request_status_{state}.json", ScopedRequestStatusResponse)
        for state in ("queued", "running", "completed", "cancelled")
    ],
    *[
        (f"directive_{state}.json", ScopedDirectiveStateResponse)
        for state in ("issued", "accepted", "executed", "unknown")
    ],
]


def load(filename):
    return json.loads((GOLDEN / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename,model", GOLDENS)
def test_golden_payloads_validate_and_roundtrip_without_losing_fields(filename, model):
    payload = load(filename)
    parsed = model.model_validate(payload)
    assert parsed.model_dump(mode="json") == payload
    assert model.model_validate_json(parsed.model_dump_json()) == parsed


def test_cancel_defaults_reason_and_session_to_existing_scoped_rules():
    payload = load("cancel_request.json")
    payload.pop("reason_code")
    payload.pop("session_id")
    parsed = ScopedCancelRequest.model_validate(payload)
    assert parsed.reason_code == "USER_CANCELLED"
    assert str(parsed.session_id) == payload["run_id"]
    payload["reason_code"] = "SUPERSEDED"
    assert ScopedCancelRequest.model_validate(payload).reason_code == "SUPERSEDED"


@pytest.mark.parametrize("filename,model", MODELS[1:3])
@pytest.mark.parametrize(
    "state", ["queued", "running", "completed", "cancelled", "expired", "failed", "unknown"],
)
def test_request_views_accept_declared_lifecycle_states(filename, model, state):
    payload = load(filename)
    payload["state"] = state
    assert model.model_validate(payload).state == state


@pytest.mark.parametrize("filename,model", MODELS[1:])
@pytest.mark.parametrize("state", ["started", "hit", "pending", "success"])
def test_views_reject_unversioned_lifecycle_states(filename, model, state):
    payload = load(filename)
    payload["state"] = state
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS[:3])
@pytest.mark.parametrize("operation", ["tactical", "agent_step", "world-event"])
def test_operations_cannot_address_unrelated_endpoints(filename, model, operation):
    payload = load(filename)
    payload["operation"] = operation
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS)
@pytest.mark.parametrize("version", ["0.1", "0.3", "0.5"])
def test_every_loop_model_requires_v04(filename, model, version):
    payload = load(filename)
    payload["protocol_version"] = version
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS)
@pytest.mark.parametrize(
    "field", ["service_instance_id", "run_id", "run_binding_id", "memory_epoch", "session_id"],
)
def test_common_scoped_ids_remain_uuids(filename, model, field):
    payload = load(filename)
    payload[field] = "unscoped-id"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS[:3])
def test_target_request_id_is_a_uuid(filename, model):
    payload = load(filename)
    payload["target_request_id"] = "arbitrary-request"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("field", ["directive_id", "origin_request_id"])
@pytest.mark.parametrize("value", ["arbitrary-directive", None])
def test_directive_view_requires_known_uuid_associations(field, value):
    payload = load("directive_unknown.json")
    payload[field] = value
    with pytest.raises(ValidationError):
        ScopedDirectiveStateResponse.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS)
def test_extra_fields_and_client_auth_overrides_are_rejected(filename, model):
    payload = load(filename)
    payload["player_id"] = "77777777-7777-4777-8777-777777777777"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS[1:])
@pytest.mark.parametrize("field", ["player_id", "save_id"])
def test_nested_scope_requires_uuid_ownership(filename, model, field):
    payload = load(filename)
    payload["scope"][field] = "another-player"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS[1:])
def test_nested_scope_rejects_unrecognized_fields(filename, model):
    payload = load(filename)
    payload["scope"]["access_token"] = "client-assertion"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "filename,model,field",
    [
        *[
            ("request_status_running.json", ScopedRequestStatusResponse, field)
            for field in ("queue_ms", "processing_ms", "total_ms", "upstream_attempts")
        ],
        *[
            ("directive_issued.json", ScopedDirectiveStateResponse, field)
            for field in ("sequence", "receipt_count")
        ],
    ],
)
@pytest.mark.parametrize("value", [-1, 1.5, float("inf"), float("nan"), True, "1"])
def test_metrics_and_sequences_are_strict_nonnegative_finite_integers(
    filename, model, field, value,
):
    payload = load(filename)
    payload[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS[2:])
def test_read_only_responses_do_not_accept_a_new_request_id(filename, model):
    payload = load(filename)
    payload["request_id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("filename,model", MODELS[2:])
@pytest.mark.parametrize(
    "field,value",
    [
        ("directive", {"action": "follow"}),
        ("timing", {"valid_for_ms": 3000}),
        ("reply_text", "Run this result again."),
    ],
)
def test_status_reads_cannot_reissue_payloads_or_fresh_validity(filename, model, field, value):
    payload = load(filename)
    payload[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("last_result", ["started", "hit", "completed"])
def test_directive_state_preserves_the_existing_receipt_result_enum(last_result):
    payload = load("directive_accepted.json")
    payload["last_result"] = last_result
    with pytest.raises(ValidationError):
        ScopedDirectiveStateResponse.model_validate(payload)


def test_unknown_directive_state_keeps_the_known_published_origin():
    payload = load("directive_unknown.json")
    parsed = ScopedDirectiveStateResponse.model_validate(payload)
    assert parsed.state == "unknown"
    assert parsed.origin_request_id == ScopedDirectiveStateResponse.model_validate(
        load("directive_issued.json"),
    ).origin_request_id
    assert parsed.last_result is None
    assert parsed.terminal is False
