"""Opt-in actual MySQL checks; default runs never contact an external database."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.persistence.database import get_database, read_document, reset_database, write_document, state_version
from app.persistence.uow import use_unit_of_work
from app.scoped.runtime import reset_runtime
from app.scoped.requests import reset_coordinator
from app.scoped.errors import ScopeError

MYSQL_URL_FILE = os.environ.get("AESIR_TEST_MYSQL_URL_FILE")
pytestmark = pytest.mark.skipif(not MYSQL_URL_FILE, reason="Dedicated MySQL runtime URL file was not provided")


@pytest.fixture
def mysql(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    monkeypatch.setenv("AESIR_SCOPE_DATABASE_URL_FILE", MYSQL_URL_FILE or "")
    monkeypatch.setenv("AESIR_SCOPE_IDENTITY_BACKEND", "bearer")
    monkeypatch.setenv("AESIR_SCOPE_LEGACY_ENABLED", "false")
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "rule")
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "rule")
    monkeypatch.setenv("AESIR_REQUEST_QUOTA_PER_MINUTE", "500")
    for key in ("DIALOGUE_SIGNALS_DIR", "AGENT_STEPS_DIR", "EVENT_SIGNALS_DIR", "REQUEST_TRACES_DIR"):
        monkeypatch.setenv("AESIR_" + key, str(tmp_path / key.lower()))
    reset_database()
    reset_runtime()
    reset_coordinator()
    database = get_database()
    database.check_schema()
    yield database
    reset_database()
    reset_runtime()
    reset_coordinator()


def authorized_client():
    from app.persistence.auth import register_player, grant_save, issue_token
    player, save = uuid4(), uuid4()
    register_player("aesir", player)
    grant_save("aesir", player, save)
    token = issue_token("aesir", player, permissions=("npc:use", "console:read", "memory:reset"))
    return TestClient(app, headers={"Authorization": "Bearer " + token}), save


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def context(client, save):
    return ok(client.get("/v1/scoped/context", params={"save_id": str(save), "companion_id": "companion.alice"}))


def bind(client, save, run=None):
    current = context(client, save)
    ok(client.post("/v1/scoped/runs/bind", json={
        "protocol_version": "0.4", "request_id": str(uuid4()), "save_id": str(save),
        "service_instance_id": current["service_instance_id"],
        "expected_control_revision": current["control_revision"], "expected_run_id": current["run_id"],
        "run_id": str(run or uuid4()),
    }))
    return context(client, save)


def envelope(current):
    return dict(protocol_version="0.4", request_id=str(uuid4()),
                save_id=current["scope"]["save_id"], companion_id="companion.alice",
                **{key: current[key] for key in ("run_id", "run_binding_id", "memory_epoch", "service_instance_id")})


def event_payload(current):
    source = Path(__file__).resolve().parents[2] / "data/golden/scoped/world_event_request.json"
    payload = json.loads(source.read_text())
    payload.update(envelope(current))
    payload["event"]["event_id"] = str(uuid4())
    return payload


def recover(client, save):
    return ok(client.get("/v1/scoped/recovery/state", params={"save_id": str(save), "companion_id": "companion.alice"}))


def test_mysql_84_runtime_has_dml_but_no_ddl_or_cross_database_privilege(mysql):
    with mysql.engine.connect() as connection:
        version = str(connection.scalar(text("SELECT VERSION()")))
        assert tuple(int(part) for part in version.split(".")[:2]) >= (8, 4)
        failed = False
        try:
            connection.execute(text("CREATE TABLE step4_runtime_must_not_create (id INT PRIMARY KEY)"))
        except SQLAlchemyError:
            failed = True
        assert failed, "The runtime account unexpectedly has schema privileges"
        failed = False
        try:
            connection.execute(text("SELECT User FROM mysql.user LIMIT 1"))
        except SQLAlchemyError:
            failed = True
        assert failed, "The runtime account unexpectedly reads the server privilege database"


def test_mysql_uow_failure_rolls_back_both_documents_and_authoritative_version(mysql):
    scope = ("aesir", str(uuid4()), str(uuid4()), "companion.alice")
    with use_unit_of_work(scope) as unit:
        write_document("memory", scope, {"value": "before"}, scope_parts=scope)
        write_document("relationship", scope, {"value": 25}, scope_parts=scope)
        unit.commit()
    version = state_version(scope)
    with pytest.raises(RuntimeError, match="injected transaction failure"):
        with use_unit_of_work(scope) as unit:
            write_document("memory", scope, {"value": "uncommitted"}, scope_parts=scope)
            write_document("relationship", scope, {"value": 99}, scope_parts=scope)
            unit.add_mutation(lambda connection: (_ for _ in ()).throw(RuntimeError("injected transaction failure")))
            unit.commit()
    assert read_document("memory", scope) == {"value": "before"}
    assert read_document("relationship", scope) == {"value": 25}
    assert state_version(scope) == version


def test_mysql_committed_document_is_visible_to_a_fresh_python_process(mysql):
    scope = ("aesir", str(uuid4()), str(uuid4()), "companion.alice")
    write_document("process-proof", scope, {"committed": True}, scope_parts=scope)
    source = "from app.persistence.database import read_document; import json,sys; assert read_document('process-proof',tuple(json.loads(sys.argv[1]))) == {'committed':True}; print('fresh-process-confirmed')"
    child = subprocess.run([sys.executable, "-c", source, json.dumps(scope)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, "Fresh SQL process could not verify the committed state"
    assert child.stdout.strip() == "fresh-process-confirmed"


def test_mysql_http_event_restart_rebind_and_recovery_never_reapply(mysql):
    client, save = authorized_client()
    with client:
        current = bind(client, save)
        event = event_payload(current)
        first = ok(client.post("/v1/scoped/world/events", json=event))
        before = recover(client, save)
        assert before["relationship"] is not None
        old_run = current["run_id"]
        reset_runtime()
        reset_coordinator()
        stale = client.post("/v1/scoped/world/events", json=event)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "SERVER_INSTANCE_CHANGED"
        history = ok(client.get("/v1/scoped/recovery/operations/" + event["request_id"], params={
            "save_id": str(save), "companion_id": "companion.alice", "run_id": old_run, "operation": "event",
        }))
        assert history["state"] == "complete"
        assert not {"directive", "payload", "reply_text", "timing", "result"} & history.keys()
        fresh = bind(client, save, old_run)
        event.update({key: fresh[key] for key in ("service_instance_id", "run_binding_id", "memory_epoch")})
        rejected = client.post("/v1/scoped/world/events", json=event)
        assert rejected.status_code == 409
        after = recover(client, save)
        assert after["relationship"] == before["relationship"]
        assert after["memory"] == before["memory"]


def test_mysql_actual_state_version_conflict_preserves_the_winner(mysql):
    from app.persistence.uow import UnitOfWork
    scope = ("aesir", str(uuid4()), str(uuid4()), "companion.alice")
    write_document("cas-proof", scope, {"winner": 0}, scope_parts=scope)
    first, second = UnitOfWork(scope), UnitOfWork(scope)
    assert first.read_document("cas-proof", scope) == second.read_document("cas-proof", scope)
    first.write_document("cas-proof", scope, {"winner": 1}, scope_parts=scope)
    second.write_document("cas-proof", scope, {"winner": 2}, scope_parts=scope)
    first.commit()
    with pytest.raises(ScopeError) as error:
        second.commit()
    assert error.value.code == "STATE_VERSION_CONFLICT"
    assert read_document("cas-proof", scope) == {"winner": 1}
