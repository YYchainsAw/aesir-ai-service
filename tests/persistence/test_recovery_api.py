"""Bearer-authenticated SQL state, receipt and recovery HTTP regressions."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.persistence import auth
from app.persistence.database import Database, list_documents, reset_database, state_version
from app.persistence.journal import get_durable_event_store, get_durable_request_store
from app.persistence.uow import UnitOfWork
from app.scoped.directives import registry
from app.scoped.requests import reset_coordinator
from app.scoped.runtime import reset_runtime
from app.schemas.recovery import RecoveryStateResponse, RecoveryOperationResponse, RecoveryDirectiveResponse

GOLDEN = Path(__file__).resolve().parents[2] / "data/golden/scoped"


class API:
    def __init__(self):
        self.player_id, self.save_id = uuid4(), uuid4()
        auth.register_player("aesir", self.player_id)
        auth.grant_save("aesir", self.player_id, self.save_id)
        self.token = auth.issue_token("aesir", self.player_id, permissions=("npc:use", "console:read", "memory:reset"))
        self.client = TestClient(app)
        self.client.headers["Authorization"] = "Bearer " + self.token

    def context(self):
        response = self.client.get("/v1/scoped/context", params={"save_id": str(self.save_id), "companion_id": "companion.alice"})
        assert response.status_code == 200, response.text
        return response.json()

    def bind(self, run_id=None):
        context = self.context()
        response = self.client.post("/v1/scoped/runs/bind", json=dict(
            protocol_version="0.4", request_id=str(uuid4()), save_id=str(self.save_id),
            service_instance_id=context["service_instance_id"], expected_control_revision=context["control_revision"],
            expected_run_id=context["run_id"], run_id=str(run_id or uuid4())))
        assert response.status_code == 200, response.text
        return self.context()

    def payload(self, context, **changes):
        body = {name: context[name] for name in ("service_instance_id", "run_id", "run_binding_id", "memory_epoch")}
        body.update(protocol_version="0.4", request_id=str(uuid4()), save_id=str(self.save_id), companion_id="companion.alice")
        body.update(changes)
        return body

    def agent(self, context):
        world = json.loads((GOLDEN / "agent_step_request.json").read_text())["world_context"]
        world["scene"] = "exploration"
        world["combat"] = None
        world["interactables"] = [{"object_id": "object.test", "kind": "prop", "distance_m": 1, "notable": True}]
        return self.payload(context, text="alice inspect", world_context=world, timing=self.timing())

    def chat(self, context):
        return self.payload(context, text="请记住，我喜欢在雨天钓鱼", timing=self.timing())

    @staticmethod
    def timing():
        return dict(capture_age_ms=0, request_age_ms=0, max_snapshot_age_ms=30000, max_request_age_ms=30000)

    def recovery(self, path="state", **parameters):
        return self.client.get("/v1/scoped/recovery/" + path,
                               params={"save_id": str(self.save_id), "companion_id": "companion.alice", **parameters})


@pytest.fixture
def persistent(tmp_path, monkeypatch):
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    monkeypatch.setenv("AESIR_SCOPE_IDENTITY_BACKEND", "bearer")
    monkeypatch.setenv("AESIR_SCOPE_LEGACY_ENABLED", "false")
    monkeypatch.setenv("AESIR_SCOPE_REQUEST_QUOTA_PER_MINUTE", "1000")
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "rule")
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "rule")
    database = Database.from_url("sqlite:///" + str(tmp_path / "api.sqlite"))
    database.initialize_schema()
    reset_database(database)
    reset_runtime()
    reset_coordinator()
    get_durable_request_store().clear()
    get_durable_event_store().clear()
    app.dependency_overrides.clear()
    api = API()
    yield SimpleNamespace(api=api, database=database)
    api.client.close()
    reset_database()
    reset_runtime()
    reset_coordinator()
    app.dependency_overrides.clear()


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code, response.text


def issue(api, context):
    payload = api.agent(context)
    response = api.client.post("/v1/scoped/agent/step", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()["directive"]["directive_id"]


def feedback(api, context, origin, directive_id, result="accepted", sequence=0):
    receipt = dict(protocol_version="0.4", order_id=directive_id, request_id=origin["request_id"],
                   agent_id="companion.alice", result=result, sequence=sequence)
    return api.client.post("/v1/scoped/tactical/executions", json=api.payload(context, receipt=receipt))


def test_sql_request_recovery_survives_runtime_restart_without_replay(persistent):
    api = persistent.api
    context = api.bind()
    payload = api.chat(context)
    first = api.client.post("/v1/scoped/companion/chat", json=payload)
    assert first.status_code == 200, first.text
    assert api.client.post("/v1/scoped/companion/chat", json=payload).json() == first.json()
    query = dict(run_id=context["run_id"], operation="chat")
    old = api.recovery("operations/" + payload["request_id"], **query)
    assert old.status_code == 200, old.text
    before = api.recovery().json()
    RecoveryStateResponse.model_validate(before)
    RecoveryOperationResponse.model_validate(old.json())
    reset_runtime()
    reset_coordinator()
    after = api.recovery()
    assert after.status_code == 200, after.text
    assert after.json()["service_instance_id"] != before["service_instance_id"]
    for name in ("memory_epoch", "memory", "relationship", "save_generation", "state_version"):
        assert after.json()[name] == before[name]
    recovered = api.recovery("operations/" + payload["request_id"], **query)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["state"] == "complete"
    assert recovered.json()["confirmed_version"] == old.json()["confirmed_version"]
    assert not {"result", "reply_text", "directive", "payload", "timing"} & recovered.json().keys()
    error(api.client.post("/v1/scoped/companion/chat", json=payload), 409, "SERVER_INSTANCE_CHANGED")
    fresh_context = api.bind(run_id=context["run_id"])
    reused = api.payload(fresh_context, request_id=payload["request_id"], text=payload["text"], timing=api.timing())
    error(api.client.post("/v1/scoped/companion/chat", json=reused), 409, "REQUEST_ID_CONFLICT")


def test_sql_receipts_dedup_protect_terminal_and_recover_after_restart(persistent):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    accepted = feedback(api, context, origin, directive_id)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["stored"] == 1
    assert feedback(api, context, origin, directive_id).json()["stored"] == 0
    assert feedback(api, context, origin, directive_id, "executed", 1).json()["stored"] == 1
    assert feedback(api, context, origin, directive_id, "accepted", 2).json()["stored"] == 0
    error(feedback(api, context, origin, directive_id, "rejected", 3), 409, "RECEIPT_STATE_CONFLICT")
    view = api.recovery("directives/" + directive_id, run_id=context["run_id"])
    assert view.status_code == 200, view.text
    RecoveryDirectiveResponse.model_validate(view.json())
    assert (view.json()["state"], view.json()["receipt_count"]) == ("executed", 2)
    assert "payload" not in view.json()
    reset_runtime()
    repeated = api.recovery("directives/" + directive_id, run_id=context["run_id"])
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["state"] == "executed"
    assert repeated.json()["origin_request_id"] == origin["request_id"]


def test_receipt_transaction_failure_does_not_change_ledger_or_append_partial_records(persistent, monkeypatch):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    before = api.recovery().json()["state_version"]
    original_commit = UnitOfWork.commit

    def broken_commit(unit):
        unit.add_mutation(lambda connection: (_ for _ in ()).throw(RuntimeError("injected after staged journal")))
        return original_commit(unit)

    monkeypatch.setattr(UnitOfWork, "commit", broken_commit)
    response = feedback(api, context, origin, directive_id)
    error(response, 503, "REQUEST_OUTCOME_UNKNOWN")
    monkeypatch.setattr(UnitOfWork, "commit", original_commit)
    view = api.recovery("directives/" + directive_id, run_id=context["run_id"])
    assert view.status_code == 200, view.text
    assert (view.json()["state"], view.json()["receipt_count"]) == ("issued", 0)
    assert view.json()["state_version"] == before
    assert persistent.database.list_documents("receipt") == []


def test_recovery_is_read_only_and_rejects_other_player_scope(persistent):
    api = persistent.api
    context = api.bind()
    payload, directive_id = issue(api, context)
    before = {name: persistent.database.list_documents(name) for name in ("memory", "relationship", "directive", "run-history")}
    version = api.recovery().json()["state_version"]
    for _ in range(2):
        assert api.recovery().status_code == 200
        assert api.recovery("operations/" + payload["request_id"], run_id=context["run_id"], operation="agent-step").status_code == 200
        assert api.recovery("directives/" + directive_id, run_id=context["run_id"]).status_code == 200
    assert api.recovery().json()["state_version"] == version
    assert {name: persistent.database.list_documents(name) for name in before} == before
    other = API()
    response = other.client.get("/v1/scoped/recovery/state", params={"save_id": str(api.save_id), "companion_id": "companion.alice"})
    error(response, 403, "SCOPE_FORBIDDEN")
    other.client.close()


def test_reset_is_atomic_and_recoverable_but_does_not_reset_relationship(persistent):
    api = persistent.api
    context = api.bind()
    assert api.client.post("/v1/scoped/companion/chat", json=api.chat(context)).status_code == 200
    before = api.recovery().json()
    request = api.payload(context)
    response = api.client.post("/v1/scoped/console/memory/reset", json=request)
    assert response.status_code == 200, response.text
    after = api.recovery().json()
    assert after["memory_epoch"] != before["memory_epoch"]
    assert all(not after["memory"][name] for name in ("short_term", "summaries", "archive", "impressions"))
    assert after["relationship"] == before["relationship"]
    assert api.client.post("/v1/scoped/console/memory/reset", json=request).json() == response.json()
    reset_runtime()
    assert api.recovery().json()["memory_epoch"] == after["memory_epoch"]


def test_cancellation_before_target_arrival_is_a_persistent_barrier(persistent):
    api = persistent.api
    context = api.bind()
    target = api.chat(context)
    cancelled = api.client.post("/v1/scoped/requests/cancel", json=api.payload(
        context, target_request_id=target["request_id"], operation="chat", reason_code="SUPERSEDED"))
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancel_requested"] is True
    reset_runtime()
    reset_coordinator()
    fresh = api.bind(run_id=context["run_id"])
    late = api.payload(fresh, text=target["text"], timing=api.timing(), request_id=target["request_id"])
    error(api.client.post("/v1/scoped/companion/chat", json=late), 409, "REQUEST_CANCELLED")
    recovered = api.recovery("operations/" + target["request_id"], operation="chat", run_id=context["run_id"])
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["state"] == "cancelled"


def test_recovery_unknown_ids_are_404_and_never_initialize_state(persistent):
    api = persistent.api
    error(api.recovery(), 404, "STATE_UNKNOWN")
    assert persistent.database.list_documents("memory") == []
    error(api.recovery("operations/" + str(uuid4()), operation="chat", run_id=str(uuid4())), 404, "REQUEST_UNKNOWN")
    error(api.recovery("directives/" + str(uuid4()), run_id=str(uuid4())), 404, "DIRECTIVE_UNKNOWN")


@pytest.mark.parametrize("filename,model", [
    ("state.json", RecoveryStateResponse),
    ("operation.json", RecoveryOperationResponse),
    ("directive.json", RecoveryDirectiveResponse),
])
def test_recovery_golden_roundtrip_and_strict_envelope(filename, model):
    from pydantic import ValidationError
    sample = json.loads((GOLDEN.parent / "recovery" / filename).read_text())
    assert model.model_validate(sample).model_dump(mode="json") == sample
    for changes in ({"protocol_version": "0.3"}, {"payload": {"action": "replay"}},
                    {"state_version": -1}, {"state_version": True}):
        with pytest.raises(ValidationError):
            model.model_validate({**sample, **changes})



def archive_payload(api, context, origin, directive_id, *, result="executed", sequence=1, **changes):
    snapshot = api.recovery().json()
    body = dict(protocol_version="0.4", request_id=str(uuid4()), save_id=str(api.save_id),
                companion_id="companion.alice", origin_run_id=context["run_id"],
                origin_memory_epoch=context["memory_epoch"], save_generation=snapshot["save_generation"],
                expected_state_version=snapshot["state_version"],
                receipts=[dict(protocol_version="0.4", order_id=directive_id,
                               request_id=origin["request_id"], agent_id="companion.alice",
                               ability_id=None, result=result, sequence=sequence)])
    body.update(changes)
    return body


def archive(api, body):
    return api.client.post("/v1/scoped/recovery/receipts", json=body)


def test_historical_receipt_after_reset_restart_and_expiry_never_restores_memory(persistent, monkeypatch):
    from app.persistence.directives import sql_registry
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    assert api.client.post("/v1/scoped/companion/chat", json=api.chat(context)).status_code == 200
    cleared = api.client.post("/v1/scoped/console/memory/reset", json=api.payload(context))
    assert cleared.status_code == 200, cleared.text
    before = api.recovery().json()
    reset_runtime()
    reset_coordinator()
    original_clock = sql_registry.clock
    monkeypatch.setattr(sql_registry, "clock", lambda: original_clock() + 1000)
    request = archive_payload(api, context, origin, directive_id)
    response = archive(api, request)
    assert response.status_code == 200, response.text
    assert response.json()["stored"] == 1 and response.json()["duplicate"] is False
    after = api.recovery().json()
    for name in ("memory", "memory_epoch", "relationship", "save_generation"):
        assert after[name] == before[name]
    assert after["memory_epoch"] != context["memory_epoch"]
    assert response.json()["state_version"] == after["state_version"]
    history = api.recovery("directives/" + directive_id, run_id=context["run_id"])
    assert history.status_code == 200, history.text
    assert history.json()["state"] == "executed"
    assert history.json()["origin_memory_epoch"] == context["memory_epoch"]
    assert not {"payload", "directive", "reply_text", "timing"} & response.json().keys()
    # The acknowledgement itself is a safe fact and can be replayed after restart.
    reset_runtime()
    replay = archive(api, request)
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    assert api.recovery("directives/" + directive_id, run_id=context["run_id"]).json()["receipt_count"] == 1


def test_realtime_receipt_and_archive_share_identity_even_with_stale_expected_version(persistent):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    assert feedback(api, context, origin, directive_id).json()["stored"] == 1
    request = archive_payload(api, context, origin, directive_id, result="accepted", sequence=0, expected_state_version=0)
    response = archive(api, request)
    assert response.status_code == 200, response.text
    assert response.json()["stored"] == 0 and response.json()["duplicate"] is True
    assert len(persistent.database.list_documents("receipt")) == 1
    assert feedback(api, context, origin, directive_id).json()["stored"] == 0


def test_historical_receipt_new_identity_requires_current_version_and_new_batch_id(persistent):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    request = archive_payload(api, context, origin, directive_id, expected_state_version=0)
    error(archive(api, request), 409, "STATE_VERSION_CONFLICT")
    request["expected_state_version"] = api.recovery().json()["state_version"]
    error(archive(api, request), 409, "REQUEST_ID_CONFLICT")
    request["request_id"] = str(uuid4())
    response = archive(api, request)
    assert response.status_code == 200, response.text
    assert response.json()["stored"] == 1
    assert len(persistent.database.list_documents("receipt")) == 1


def test_historical_receipt_batch_conflict_has_no_partial_write(persistent):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    second_origin, second_directive = issue(api, context)
    request = archive_payload(api, context, origin, directive_id)
    request["receipts"].append(dict(protocol_version="0.4", order_id=second_directive,
                                    request_id=str(uuid4()), agent_id="companion.alice", result="executed", sequence=1))
    version = api.recovery().json()["state_version"]
    error(archive(api, request), 409, "DIRECTIVE_MISMATCH")
    for order in (directive_id, second_directive):
        view = api.recovery("directives/" + order, run_id=context["run_id"])
        assert (view.json()["state"], view.json()["receipt_count"]) == ("issued", 0)
    assert persistent.database.list_documents("receipt") == []
    assert api.recovery().json()["state_version"] == version


@pytest.mark.parametrize("change,expected", [
    ("epoch", "MEMORY_EPOCH_STALE"), ("generation", "SAVE_GENERATION_STALE"),
    ("run", "ORIGIN_RUN_UNKNOWN"), ("ability", "DIRECTIVE_MISMATCH"),
    ("encounter", "DIRECTIVE_MISMATCH"),
])
def test_historical_receipt_checks_original_associations(persistent, change, expected):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    request = archive_payload(api, context, origin, directive_id)
    if change == "epoch": request["origin_memory_epoch"] = str(uuid4())
    if change == "generation": request["save_generation"] = str(uuid4())
    if change == "run": request["origin_run_id"] = str(uuid4())
    if change == "ability": request["receipts"][0]["ability_id"] = "ability.unrelated"
    if change == "encounter": request["receipts"][0]["encounter_id"] = str(uuid4())
    error(archive(api, request), 409, expected)
    assert persistent.database.list_documents("receipt") == []


def test_historical_receipts_cannot_be_archived_by_another_player(persistent):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    body = archive_payload(api, context, origin, directive_id)
    other = API()
    error(archive(other, body), 403, "SCOPE_FORBIDDEN")
    other.client.close()
    assert persistent.database.list_documents("receipt") == []


@pytest.mark.parametrize("filename,model_name,version_field", [
    ("receipts_request.json", "RecoveryReceiptsRequest", "expected_state_version"),
    ("receipts_response.json", "RecoveryReceiptsResponse", "state_version"),
])
def test_historical_receipt_golden_is_complete_strict_and_nonexecutable(filename, model_name, version_field):
    from app.schemas import recovery
    from pydantic import ValidationError
    model = getattr(recovery, model_name)
    sample = json.loads((GOLDEN.parent / "recovery" / filename).read_text())
    assert model.model_validate(sample).model_dump(mode="json") == sample
    for changes in ({"protocol_version": "0.3"}, {"payload": {"action": "replay"}},
                    {version_field: -1}, {version_field: True}):
        with pytest.raises(ValidationError):
            model.model_validate({**sample, **changes})


def test_historical_receipt_commit_failure_rolls_back_facts_and_keeps_unknown_identity(persistent, monkeypatch):
    api = persistent.api
    context = api.bind()
    origin, directive_id = issue(api, context)
    request = archive_payload(api, context, origin, directive_id)
    original_version = api.recovery().json()["state_version"]
    original_commit = UnitOfWork.commit

    def broken_commit(unit):
        unit.add_mutation(lambda connection: (_ for _ in ()).throw(RuntimeError("archive final transaction failed")))
        return original_commit(unit)

    monkeypatch.setattr(UnitOfWork, "commit", broken_commit)
    error(archive(api, request), 503, "REQUEST_OUTCOME_UNKNOWN")
    monkeypatch.setattr(UnitOfWork, "commit", original_commit)
    view = api.recovery("directives/" + directive_id, run_id=context["run_id"]).json()
    assert (view["state"], view["receipt_count"], view["state_version"]) == ("issued", 0, original_version)
    assert persistent.database.list_documents("receipt") == []
    reset_runtime()
    outcome = api.recovery("operations/" + request["request_id"], run_id=context["run_id"], operation="receipt-archive")
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["state"] == "unknown"
    error(archive(api, request), 503, "REQUEST_OUTCOME_UNKNOWN")
    assert persistent.database.list_documents("receipt") == []
    assert api.recovery().json()["state_version"] == original_version
