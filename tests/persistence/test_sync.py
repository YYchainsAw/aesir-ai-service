"""Offline/real-time facts share durable identities and cannot produce actions."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.persistence.database import Database, read_document, reset_database
from app.persistence.sync import lookup_fact
from app.scoped.context import NpcScope
from app.scoped.runtime import reset_runtime
from app.schemas.scoped import ScopedWorldEvent
from app.schemas.sync import SyncFactsRequest, SyncFactsResponse, SyncStateResponse
from test_auth import access
from test_security_integration import security, document_snapshot, payload

GOLDEN = Path(__file__).resolve().parents[2] / "data/golden/sync"


def state(service):
    response = service.client.get("/v1/scoped/sync/state", params={
        "save_id": str(service.player.save_id), "companion_id": "companion.alice"})
    assert response.status_code == 200, response.text
    return response.json()


def fact(service, event_type="gift_given", **changes):
    data = {"origin_run_id": service.context["run_id"], "origin_encounter_id": None,
        "origin_memory_epoch": service.context["memory_epoch"], "source": "ue",
        "event": {"event_id": str(uuid4()), "event_type": event_type,
            "occurred_at": "2026-10-22T00:00:00Z", "sequence": 1,
            "details": {"item_name": "a supplied gift"}}}
    data.update(changes)
    return data


def batch(service, facts, **changes):
    current = state(service)
    data = {"protocol_version": "0.4", "request_id": str(uuid4()), "save_id": str(service.player.save_id),
        "companion_id": "companion.alice", "save_generation": current["save_generation"],
        "expected_state_version": current["state_version"], "facts": facts}
    data.update(changes)
    return data


def post(service, body, expected=200, reason=None):
    response = service.client.post("/v1/scoped/sync/facts", json=body)
    assert response.status_code == expected, response.text
    if reason:
        assert response.json()["detail"]["code"] == reason, response.text
    if expected == 200:
        SyncFactsResponse.model_validate(response.json())
    return response


def npc(service):
    return NpcScope("aesir", service.player.player_id, service.player.save_id, "companion.alice")


def relationship(service):
    return read_document("relationship", npc(service).key)


def memory(service):
    return read_document("memory", npc(service).key)


def realtime(service, item):
    world = json.loads((GOLDEN.parent / "scoped/world_event_request.json").read_text())["world_context"]
    body = payload(service, timing={"capture_age_ms": 0, "request_age_ms": 0,
        "max_snapshot_age_ms": 30000, "max_request_age_ms": 30000},
        event=item["event"], world_context=world)
    response = service.client.post("/v1/scoped/world/events", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_fresh_offline_fact_applies_declared_parts_without_any_action(security):
    item = fact(security)
    response = post(security, batch(security, [item])).json()
    acknowledgement = response["acknowledgements"][0]
    assert acknowledgement["relationship_delta"] > 0
    assert acknowledgement["relationship_status"] == "scored"
    assert acknowledgement["memory_status"] == "recorded"
    assert acknowledgement["confirmed_version"] == response["state_version"]
    assert memory(security)["summaries"]
    assert not {"directive", "action", "reply_text", "payload"} & response.keys()
    stored = lookup_fact(npc(security), item["origin_run_id"], None, ScopedWorldEvent.model_validate(item["event"]))
    assert stored["event"] == item["event"]
    assert stored["confirmed_version"] == response["state_version"]


def test_lost_ack_same_batch_and_new_batch_never_reapply_the_same_fact(security):
    item = fact(security)
    body = batch(security, [item])
    first = post(security, body).json()
    score, snapshot = deepcopy(relationship(security)), deepcopy(memory(security))
    second = post(security, body).json()
    assert second["acknowledgements"][0]["duplicate"] is True
    assert second["acknowledgements"][0]["confirmed_version"] == first["state_version"]
    assert second["state_version"] == first["state_version"]
    third = post(security, batch(security, [item], expected_state_version=0)).json()
    assert third["acknowledgements"][0]["duplicate"] is True
    assert relationship(security) == score
    assert memory(security) == snapshot


def test_sync_request_id_cannot_change_its_fact_batch(security):
    body = batch(security, [fact(security)])
    post(security, body)
    changed = deepcopy(body)
    changed["facts"] = [fact(security, "promise_kept")]
    post(security, changed, 409, "REQUEST_ID_CONFLICT")


def test_fresh_fact_requires_current_authoritative_version(security):
    old = state(security)["state_version"]
    post(security, batch(security, [fact(security)]))
    before = document_snapshot(security.access.database)
    post(security, batch(security, [fact(security, "promise_kept")], expected_state_version=old), 409, "STATE_VERSION_CONFLICT")
    assert document_snapshot(security.access.database) == before


def test_batch_checks_every_original_run_before_applying_any_fact(security):
    before = document_snapshot(security.access.database)
    post(security, batch(security, [fact(security), fact(security, origin_run_id=str(uuid4()))]), 409, "ORIGIN_RUN_UNKNOWN")
    assert document_snapshot(security.access.database) == before


def test_semantic_conflict_in_late_batch_item_prevents_earlier_fresh_fact(security):
    known = fact(security)
    post(security, batch(security, [known]))
    changed = deepcopy(known)
    changed["event"]["details"]["item_name"] = "different semantics"
    before = document_snapshot(security.access.database)
    post(security, batch(security, [fact(security, "promise_kept"), changed]), 409, "EVENT_ID_CONFLICT")
    assert document_snapshot(security.access.database) == before


def test_old_memory_epoch_does_not_restore_reset_memory_but_relation_has_own_confirmation(security):
    old = fact(security)
    reset = security.client.post("/v1/scoped/console/memory/reset", json=payload(security))
    assert reset.status_code == 200, reset.text
    response = post(security, batch(security, [old])).json()
    ack = response["acknowledgements"][0]
    assert ack["memory_status"] == "skipped_reset"
    assert ack["relationship_delta"] > 0
    assert response["memory_epoch"] == reset.json()["memory_epoch"]
    assert memory(security)["summaries"] == []
    assert memory(security)["archive"] == []
    score = deepcopy(relationship(security))
    # Relabeling the epoch cannot make the same stable event fresh.
    old["origin_memory_epoch"] = response["memory_epoch"]
    post(security, batch(security, [old]), 409, "EVENT_ID_CONFLICT")
    assert relationship(security) == score and memory(security)["summaries"] == []


def test_confirmed_old_fact_stays_confirmed_after_reset_without_recreating_memory(security):
    body = batch(security, [fact(security)])
    post(security, body)
    assert memory(security)["summaries"]
    reset = security.client.post("/v1/scoped/console/memory/reset", json=payload(security))
    assert reset.status_code == 200, reset.text
    repeated = post(security, body).json()
    assert repeated["acknowledgements"][0]["duplicate"] is True
    assert repeated["memory_epoch"] == reset.json()["memory_epoch"]
    assert memory(security)["summaries"] == []


def test_restart_requires_no_old_binding_to_confirm_known_run_fact(security):
    item = fact(security)
    reset_runtime()
    response = post(security, batch(security, [item])).json()
    assert response["acknowledgements"][0]["relationship_delta"] > 0
    assert response["acknowledgements"][0]["memory_status"] == "not_applied_missing_context"
    assert memory(security)["summaries"] == []


def test_engine_reload_and_process_incarnation_do_not_reapply_confirmed_facts(security):
    body = batch(security, [fact(security)])
    first = post(security, body).json()
    saved = deepcopy(relationship(security))
    fresh = Database.from_url("sqlite:///" + str(security.access.path))
    reset_database(fresh)
    reset_runtime()
    second = post(security, body).json()
    assert second["acknowledgements"][0]["duplicate"] is True
    assert second["acknowledgements"][0]["confirmed_version"] == first["state_version"]
    assert relationship(security) == saved


def test_real_time_then_offline_uses_the_same_stable_fact_confirmation(security):
    item = fact(security)
    live = realtime(security, item)
    saved, snapshot = deepcopy(relationship(security)), deepcopy(memory(security))
    offline = post(security, batch(security, [item])).json()
    assert offline["acknowledgements"][0]["duplicate"] is True
    assert live["duplicate"] is False
    assert relationship(security) == saved and memory(security) == snapshot


def test_offline_then_real_time_never_generates_a_new_action_or_scores_again(security):
    item = fact(security)
    post(security, batch(security, [item]))
    saved, snapshot = deepcopy(relationship(security)), deepcopy(memory(security))
    live = realtime(security, item)
    assert live["duplicate"] is True
    assert live["action"] == "none" and live["directive"] is None
    assert live["observability"]["relationship_delta"] == 0
    assert relationship(security) == saved and memory(security) == snapshot


def test_rollback_after_staging_one_fact_does_not_leave_partial_score_memory_or_ack(security, monkeypatch):
    import app.persistence.sync as synchronizer
    original = synchronizer.stage_fact_confirmation
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise ScopeError(503, "STATE_UNAVAILABLE", "injected sync staging failure")
        return original(*args, **kwargs)
    from app.scoped.errors import ScopeError
    monkeypatch.setattr(synchronizer, "stage_fact_confirmation", fail_second)
    before = document_snapshot(security.access.database)
    post(security, batch(security, [fact(security), fact(security, "promise_kept")]), 503, "STATE_UNAVAILABLE")
    assert len(calls) == 2
    assert document_snapshot(security.access.database) == before


def test_save_generation_conflict_is_rejected_before_application(security):
    before = document_snapshot(security.access.database)
    post(security, batch(security, [fact(security)], save_generation=str(uuid4())), 409, "SAVE_GENERATION_STALE")
    assert document_snapshot(security.access.database) == before


def test_combat_fact_requires_known_encounter_history(security):
    item = fact(security, "boss_stunned", origin_encounter_id=str(uuid4()))
    post(security, batch(security, [item]), 409, "ORIGIN_ENCOUNTER_UNKNOWN")
    context = security.context
    encounter = str(uuid4())
    response = security.client.post("/v1/scoped/encounters/control", json={
        "protocol_version": "0.4", "request_id": str(uuid4()), "save_id": str(security.player.save_id),
        "service_instance_id": context["service_instance_id"], "run_id": context["run_id"],
        "run_binding_id": context["run_binding_id"], "op": "begin", "expected_encounter_revision": 0,
        "expected_encounter_id": None, "encounter_id": encounter})
    assert response.status_code == 200, response.text
    item["origin_encounter_id"] = encounter
    acknowledgement = post(security, batch(security, [item])).json()["acknowledgements"][0]
    assert acknowledgement["memory_status"] == "not_applicable"
    assert acknowledgement["relationship_delta"] == 0


def test_old_reported_times_never_rewind_relationship_scoring_day(security, monkeypatch):
    import app.services.relationship.rules as rules
    monkeypatch.setattr(rules, "_now", lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))
    item = fact(security)
    item["event"]["occurred_at"] = "1900-01-01T00:00:00Z"
    first = post(security, batch(security, [item])).json()["acknowledgements"][0]
    assert first["relationship_delta"] > 0
    assert relationship(security)["day"] == "2026-10-22"
    future = fact(security)
    future["event"]["occurred_at"] = "2100-01-01T00:00:00Z"
    second = post(security, batch(security, [future])).json()["acknowledgements"][0]
    assert second["relationship_status"] == "cooldown_blocked"
    assert relationship(security)["day"] == "2026-10-22"


@pytest.mark.parametrize("mutation", [
    lambda body: body.update(expected_state_version=True),
    lambda body: body.update(facts=[]),
    lambda body: body.update(facts=body["facts"] * 51),
    lambda body: body.update(relationship_value=100),
    lambda body: body["facts"][0].update(source="audio"),
    lambda body: body["facts"][0]["event"].update(event_type="heartbeat"),
    lambda body: body["facts"][0].update(text="old chat"),
])
def test_sync_rejects_nonfacts_unbounded_or_noncanonical_envelopes_before_effects(security, mutation):
    body = batch(security, [fact(security)])
    mutation(body)
    before = document_snapshot(security.access.database)
    post(security, body, 422)
    assert document_snapshot(security.access.database) == before


def test_sync_endpoints_enforce_permission_and_owned_save(security):
    token = security.access.player(permissions=("docs:read",))
    headers = {"Authorization": f"Bearer {token.token}"}
    assert TestClient(app).get("/v1/scoped/sync/state", params={"save_id": str(token.save_id), "companion_id": "companion.alice"}, headers=headers).status_code == 403
    assert TestClient(app).post("/v1/scoped/sync/facts", json={}, headers=headers).status_code == 403
    other = security.access.player()
    response = security.client.get("/v1/scoped/sync/state", params={"save_id": str(other.save_id), "companion_id": "companion.alice"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "SCOPE_FORBIDDEN"


@pytest.mark.parametrize("filename,model", [
    ("state_response.json", SyncStateResponse), ("facts_request.json", SyncFactsRequest),
    ("facts_response.json", SyncFactsResponse), ("duplicate_response.json", SyncFactsResponse),
    ("reset_partial_response.json", SyncFactsResponse),
])
def test_complete_sync_golden_models(filename, model):
    original = json.loads((GOLDEN / filename).read_text())
    assert model.model_validate(original).model_dump(mode="json") == original


def test_sync_batch_cannot_bypass_l0_game_event_declarations(access, monkeypatch):
    from app.persistence import auth
    monkeypatch.setenv("AESIR_GAME_ID", "demo-vn")
    monkeypatch.setenv("AESIR_SCOPE_REQUEST_QUOTA_PER_MINUTE", "100")
    reset_runtime()
    player_id, save_id = uuid4(), uuid4()
    auth.register_player("demo-vn", player_id)
    auth.grant_save("demo-vn", player_id, save_id)
    token = auth.issue_token("demo-vn", player_id, permissions=("npc:use",))
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    params = {"save_id": str(save_id), "companion_id": "companion.narrator"}
    context = client.get("/v1/scoped/context", params=params)
    assert context.status_code == 200, context.text
    context = context.json()
    run_id = str(uuid4())
    bound = client.post("/v1/scoped/runs/bind", json={"protocol_version": "0.4", "request_id": str(uuid4()),
        "save_id": str(save_id), "service_instance_id": context["service_instance_id"],
        "expected_control_revision": context["control_revision"], "expected_run_id": context["run_id"], "run_id": run_id})
    assert bound.status_code == 200, bound.text
    authoritative = client.get("/v1/scoped/sync/state", params=params)
    assert authoritative.status_code == 200, authoritative.text
    current = authoritative.json()
    def item(kind):
        return {"origin_run_id": run_id, "origin_encounter_id": None, "origin_memory_epoch": current["memory_epoch"],
            "source": "ue", "event": {"event_id": str(uuid4()), "event_type": kind,
                "occurred_at": "2026-10-22T00:00:00Z", "sequence": 1, "details": {}}}
    body = {"protocol_version": "0.4", "request_id": str(uuid4()), "save_id": str(save_id),
        "companion_id": "companion.narrator", "save_generation": current["save_generation"],
        "expected_state_version": current["state_version"], "facts": [item("gift_given"), item("promise_kept")]}
    before = document_snapshot(access.database)
    rejected = client.post("/v1/scoped/sync/facts", json=body)
    assert rejected.status_code == 403, rejected.text
    assert rejected.json()["detail"]["code"] == "BUSINESS_REJECTED"
    assert document_snapshot(access.database) == before


def test_sync_batch_honors_the_configured_limit_before_any_write(security, monkeypatch):
    monkeypatch.setenv("AESIR_SCOPE_SYNC_BATCH_LIMIT", "3")
    body = batch(security, [fact(security) for _ in range(4)])
    before = document_snapshot(security.access.database)
    post(security, body, 422, "SYNC_BATCH_LIMIT")
    assert document_snapshot(security.access.database) == before
