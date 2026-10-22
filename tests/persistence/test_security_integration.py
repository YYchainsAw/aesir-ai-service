"""SQL/Bearer integration: revocation while generation waits and explicit roles."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.main import app
from app.persistence import auth
from app.persistence.schema import documents
from app.scoped.context import NpcScope, RequestScope, use_scope
from app.scoped.directives import registry
from app.scoped.idempotency import reset_idempotency_stores
from app.scoped.requests import reset_coordinator
from app.scoped.runtime import reset_runtime
from app.schemas.companion_dialogue import CompanionDialogueResponse
from app.services.companion.session_memory import SessionMemoryStore, get_session_memory
from test_auth import access


@pytest.fixture
def security(access, monkeypatch):
    import app.services.companion.session_memory as memory
    monkeypatch.setenv("AESIR_SCOPE_REQUEST_QUOTA_PER_MINUTE", "100")
    monkeypatch.setattr(memory, "_store", SessionMemoryStore(10))
    reset_runtime()
    reset_idempotency_stores()
    reset_coordinator()
    registry.clear()
    player = access.player(permissions=tuple(auth.PERMISSIONS))
    client = TestClient(app, headers={"Authorization": f"Bearer {player.token}"})
    params = {"save_id": str(player.save_id), "companion_id": "companion.alice"}
    context = client.get("/v1/scoped/context", params=params)
    assert context.status_code == 200, context.text
    context = context.json()
    bind = client.post("/v1/scoped/runs/bind", json={
        "protocol_version": "0.4", "request_id": str(uuid4()), "save_id": str(player.save_id),
        "service_instance_id": context["service_instance_id"],
        "expected_control_revision": context["control_revision"], "expected_run_id": context["run_id"],
        "run_id": str(uuid4()),
    })
    assert bind.status_code == 200, bind.text
    context = client.get("/v1/scoped/context", params=params).json()
    yield SimpleNamespace(access=access, player=player, client=client, context=context)
    registry.clear()
    reset_coordinator()
    reset_idempotency_stores()
    reset_runtime()


def payload(service, **changes):
    context = service.context
    data = {key: context[key] for key in ("service_instance_id", "run_id", "run_binding_id", "memory_epoch")}
    data.update(protocol_version="0.4", request_id=str(uuid4()), save_id=str(service.player.save_id),
                companion_id="companion.alice")
    data.update(changes)
    return data


def query(service):
    data = payload(service)
    data.pop("protocol_version")
    data.pop("request_id")
    return data


def document_snapshot(database):
    with database.engine.connect() as connection:
        rows = connection.execute(select(documents)).mappings().all()
    return sorted((row["namespace"], row["key_hash"], json.dumps(row["payload"], sort_keys=True)) for row in rows)


def session_history(service):
    context = service.context
    scope = RequestScope(NpcScope("aesir", service.player.player_id, service.player.save_id, "companion.alice"),
                         UUID(context["run_id"]), UUID(context["run_id"]), UUID(context["service_instance_id"]),
                         UUID(context["run_binding_id"]), UUID(context["memory_epoch"]))
    with use_scope(scope):
        return get_session_memory(10).history(context["run_id"], "companion.alice")


@pytest.fixture
def delayed_generation(monkeypatch):
    import app.services.companion.dialogue_service as dialogue
    entered, release = Event(), Event()
    calls = []
    class Generation:
        def __init__(self, *, profile):
            self.last_topics = ["fishing"]
            self.last_facts = []
            self.last_reply_topics = []
            self.last_relationship_signal = "warm"
            self.last_salient = False
            self.last_style_violations = []
            self.last_lookup = None
        def reply(self, request, **kwargs):
            calls.append(request.text)
            entered.set()
            assert release.wait(10), "test did not release generation"
            return CompanionDialogueResponse(
                companion_id=request.companion_id, session_id=request.session_id,
                reply_text="A controlled local reply.", emotion_id="emotion.neutral",
                gesture_id="", facial_expression_id="", source="llm",
            )
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")
    monkeypatch.setattr(dialogue, "LLMCompanionDialogueService", Generation)
    yield entered, release, calls
    release.set()


@pytest.mark.parametrize("revocation,expected_status,expected_code", [
    ("token", 401, "IDENTITY_REQUIRED"),
    ("save", 403, "SCOPE_FORBIDDEN"),
    ("player", 401, "IDENTITY_REQUIRED"),
])
def test_revocation_during_generation_prevents_all_business_commit(
        security, delayed_generation, revocation, expected_status, expected_code):
    entered, release, calls = delayed_generation
    before = document_snapshot(security.access.database)
    body = payload(security, text="A turn that must not be committed after revocation", timing={
        "capture_age_ms": 0, "request_age_ms": 0,
        "max_snapshot_age_ms": 30000, "max_request_age_ms": 30000,
    })
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(security.client.post, "/v1/scoped/companion/chat", json=body)
        try:
            assert entered.wait(3)
            if revocation == "token":
                auth.revoke_token(security.player.principal.credential_id)
            elif revocation == "save":
                auth.grant_save("aesir", security.player.player_id, security.player.save_id, active=False)
            else:
                auth.set_player_active("aesir", security.player.player_id, False)
        finally:
            release.set()
        response = future.result(timeout=4)
    assert response.status_code == expected_status, response.text
    assert response.json()["detail"]["code"] == expected_code
    assert document_snapshot(security.access.database) == before
    assert session_history(security) == ()
    assert len(calls) == 1


def test_database_loss_after_generation_does_not_fall_back_to_json_or_commit_history(
        security, delayed_generation, monkeypatch, tmp_path):
    entered, release, calls = delayed_generation
    before = document_snapshot(security.access.database)
    body = payload(security, text="Must not fall back to anonymous or JSON storage", timing={
        "capture_age_ms": 0, "request_age_ms": 0,
        "max_snapshot_age_ms": 30000, "max_request_age_ms": 30000,
    })
    engine = security.access.database.engine
    original_connect = engine.connect
    def fail(*args, **kwargs):
        raise OperationalError("SECRET_DATABASE_DSN", {}, Exception("PRIVATE_DATABASE_PASSWORD"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(security.client.post, "/v1/scoped/companion/chat", json=body)
        try:
            assert entered.wait(3)
            monkeypatch.setattr(engine, "connect", fail)
        finally:
            release.set()
        try:
            response = future.result(timeout=4)
        finally:
            monkeypatch.setattr(engine, "connect", original_connect)
    assert response.status_code == 503, response.text
    assert "SECRET" not in response.text and "PRIVATE" not in response.text
    assert document_snapshot(security.access.database) == before
    assert session_history(security) == ()
    assert not list((tmp_path / "memory").rglob("memory.json"))
    assert not list((tmp_path / "relationship").rglob("relationship.json"))
    assert len(calls) == 1


def test_console_reset_and_business_permissions_are_separate_and_scope_is_still_required(security):
    player = security.player
    tokens = {
        name: auth.issue_token("aesir", player.player_id, permissions=(permission,))
        for name, permission in [("npc", "npc:use"), ("console", "console:read"), ("reset", "memory:reset")]
    }
    client = TestClient(app)
    headers = lambda name: {"Authorization": f"Bearer {tokens[name]}"}
    for path in ("/v1/scoped/console/state", "/v1/scoped/console/memory"):
        assert client.get(path, params=query(security), headers=headers("npc")).status_code == 403
        allowed = client.get(path, params=query(security), headers=headers("console"))
        assert allowed.status_code == 200, allowed.text
    assert client.post("/v1/scoped/console/memory/reset", json=payload(security), headers=headers("npc")).status_code == 403
    assert client.post("/v1/scoped/console/memory/reset", json=payload(security), headers=headers("console")).status_code == 403
    other = security.access.player(permissions=("console:read", "memory:reset"))
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert client.get("/v1/scoped/console/memory", params=query(security), headers=other_headers).status_code == 403
    assert client.post("/v1/scoped/console/memory/reset", json=payload(security), headers=other_headers).status_code == 403
    allowed = client.post("/v1/scoped/console/memory/reset", json=payload(security), headers=headers("reset"))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["memory_epoch"] != security.context["memory_epoch"]
