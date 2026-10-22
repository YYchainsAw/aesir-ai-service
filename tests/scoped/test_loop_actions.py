"""Scoped action mapping uses only the supplied snapshot and existing catalog."""
import pytest

from app.scoped.requests import reset_coordinator
from app.schemas.tactical_intent import TacticalIntent
from test_scoped_api import h


@pytest.fixture(autouse=True)
def coordinator():
    state = reset_coordinator()
    yield
    state.clear()
    reset_coordinator()


def submit(harness, payload):
    response = harness.client.post("/v1/scoped/agent/step", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def combat_payload(harness, context, text):
    event = harness.event(context, combat=True)
    payload = harness.agent(context, text=text)
    payload.update(encounter_id=event["encounter_id"], world_context=event["world_context"])
    return payload


def test_follow_target_comes_from_world_snapshot_and_receipt_can_be_associated(h):
    context = h.bind()
    payload = h.agent(context, text="alice follow")
    payload["world_context"]["player"]["id"] = "player.snapshot.42"
    response = submit(h, payload)
    directive = response["directive"]
    assert directive["action_type"] == "follow"
    assert directive["payload"] == {"target_id": "player.snapshot.42"}
    receipt = dict(protocol_version="0.4", order_id=directive["directive_id"],
                   request_id=payload["request_id"], agent_id="companion.alice", result="accepted")
    result = h.client.post("/v1/scoped/tactical/executions", json=h.payload(context, receipt=receipt))
    assert result.status_code == 202, result.text
    assert result.json()["stored"] == 1


@pytest.mark.parametrize("target", ["", "   "])
def test_follow_without_real_player_target_does_not_invent_one(h, target):
    context = h.bind()
    payload = h.agent(context, text="alice follow")
    payload["world_context"]["player"]["id"] = target
    response = submit(h, payload)
    assert response["action"] == "none"
    assert response["directive"] is None
    assert "NO_VALID_TARGET" in response["observability"]["reason_codes"]


def test_wait_has_no_invented_destination_or_completion(h):
    context = h.bind()
    response = submit(h, h.agent(context, text="alice wait"))
    assert response["directive"]["action_type"] == "wait"
    assert response["directive"]["payload"] == {}
    assert response["directive"]["expires"]["type"] == "immediate"
    assert "result" not in response


@pytest.mark.parametrize("text,ability,target", [
    ("alice heal", "ability.alice.major_heal", "party.player"),
    ("alice shield", "ability.alice.shield", "party.player"),
    ("alice burst", "ability.alice.explosion", "encounter.primary_hostile"),
])
def test_combat_directive_keeps_actual_ability_and_target_for_receipts(h, text, ability, target):
    context = h.bind()
    payload = combat_payload(h, context, text)
    response = submit(h, payload)
    directive = response["directive"]
    assert response["action"] == "directive"
    assert directive["payload"] == {"ability_id": ability, "target_id": target}
    receipt = dict(protocol_version="0.4", order_id=directive["directive_id"],
                   request_id=payload["request_id"], agent_id="companion.alice",
                   ability_id=ability, encounter_id=payload["encounter_id"], result="executed")
    result = h.client.post("/v1/scoped/tactical/executions", json=h.payload(
        context, encounter_id=payload["encounter_id"], receipt=receipt))
    assert result.status_code == 202, result.text


def test_pending_stun_command_never_becomes_immediate_burst(h):
    context = h.bind()
    payload = combat_payload(h, context, "alice stun burst")
    response = submit(h, payload)
    assert response["action"] == "none"
    assert response["directive"] is None
    assert "CONDITION_NOT_SUPPORTED" in response["observability"]["reason_codes"]


def test_current_stunned_snapshot_can_satisfy_the_known_condition(h):
    context = h.bind()
    payload = combat_payload(h, context, "alice stun burst")
    payload["world_context"]["combat"]["boss"]["state_tags"] = ["state.stunned"]
    payload["world_context"]["combat"]["boss"]["stunned_remaining_seconds"] = 2
    response = submit(h, payload)
    assert response["action"] == "directive"
    assert response["directive"]["action_type"] == "burst"
    assert response["directive"]["payload"]["ability_id"] == "ability.alice.explosion"
    assert response["directive"]["expires"]["type"] == "before_seconds"


@pytest.mark.parametrize("intent_id", ["follow_player", "support_heal_player"])
def test_unspecified_condition_from_parser_cannot_be_erased(h, monkeypatch, intent_id):
    import app.services.tactical.llm_intent as parser
    monkeypatch.setattr(parser, "parse_intent_with_source", lambda text: (
        TacticalIntent(intent_id=intent_id, timing="on_condition"), "llm"))
    context = h.bind()
    payload = combat_payload(h, context, "conditional command") if intent_id.startswith("support") else h.agent(context)
    response = submit(h, payload)
    assert response["action"] == "none"
    assert response["directive"] is None
    assert "CONDITION_NOT_SUPPORTED" in response["observability"]["reason_codes"]


@pytest.mark.parametrize("text,target_kind", [("alice heal", "player"), ("alice burst", "boss")])
def test_combat_without_target_does_not_issue_ability(h, text, target_kind):
    context = h.bind()
    payload = combat_payload(h, context, text)
    payload["world_context"]["combat"][target_kind]["id"] = ""
    if target_kind == "player":
        payload["world_context"]["player"]["id"] = ""
    response = submit(h, payload)
    assert response["action"] == "none"
    assert "NO_VALID_TARGET" in response["observability"]["reason_codes"]


def test_follow_does_not_expand_existing_combat_scene_catalog(h):
    context = h.bind()
    response = submit(h, combat_payload(h, context, "alice follow"))
    assert response["action"] == "none"
    assert "BEHAVIOR_NOT_IN_SCENE" in response["observability"]["reason_codes"]
