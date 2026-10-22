"""SQL transactions and migration proofs use separate file SQLite databases."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from app.persistence.database import Database, parts_hash
from app.persistence.schema import documents, schema_versions
from app.persistence.uow import UnitOfWork, current_uow, use_unit_of_work
from app.scoped.errors import ScopeError
from app.schemas.memory import MemorySnapshot
from app.schemas.relationship import RelationshipState
from scripts.persistence_data import backup_database, import_json, restore_database, scan_sources


@pytest.fixture
def database(tmp_path):
    db = Database.from_url("sqlite:///" + str(tmp_path / "test.sqlite"))
    db.initialize_schema()
    yield db
    db.engine.dispose()


@pytest.fixture
def scope():
    return ("aesir", str(uuid4()), str(uuid4()), "companion.alice")


def assert_error(function, code):
    with pytest.raises(ScopeError) as error:
        function()
    assert error.value.code == code


def test_schema_is_explicit_and_wrong_version_is_rejected(tmp_path):
    db = Database.from_url("sqlite:///" + str(tmp_path / "empty.sqlite"))
    assert_error(db.check_schema, "STATE_UNAVAILABLE")
    db.initialize_schema()
    db.check_schema()
    with db.engine.begin() as connection:
        connection.execute(schema_versions.update().values(version=999))
    assert_error(db.check_schema, "STATE_UNAVAILABLE")
    db.engine.dispose()


def test_memory_sqlite_cannot_share_underlying_connections():
    with pytest.raises(ValueError):
        Database.from_url("sqlite:///:memory:")


def test_document_roundtrip_and_copy_do_not_share_mutable_state(database, scope):
    database.write_document("memory", scope, {"items": [1]}, scope_parts=scope)
    result = database.read_document("memory", scope)
    result["items"].append(2)
    assert database.read_document("memory", scope) == {"items": [1]}
    assert database.read_document("memory", ("missing",), {"default": True}) == {"default": True}
    assert database.state_version(scope) == 1


def test_uow_reads_writes_and_deletes_its_own_overlay(database, scope):
    database.write_document("memory", scope, {"n": 1}, scope_parts=scope)
    with use_unit_of_work(scope, database=database) as unit:
        assert current_uow() is unit
        assert database.read_document("memory", scope) == {"n": 1}
        database.write_document("memory", scope, {"n": 2}, scope_parts=scope)
        assert database.read_document("memory", scope) == {"n": 2}
        assert database.list_documents("memory", scope) == [(scope, {"n": 2})]
        # A separate connection sees the old committed state during staging.
        assert database._read("memory", scope)["payload"] == {"n": 1}
        database.delete_document("memory", scope, scope_parts=scope)
        assert database.read_document("memory", scope) is None
        assert database.list_documents("memory", scope) == []
        unit.commit()
    assert database.read_document("memory", scope) is None
    assert database.state_version(scope) == 2
    assert current_uow() is None


def test_uncommitted_scope_rolls_back_overlay_and_hooks(database, scope):
    calls = []
    with use_unit_of_work(scope, database=database) as unit:
        database.write_document("memory", scope, {"n": 1}, scope_parts=scope)
        unit.after_rollback(lambda: calls.append("rollback"))
        unit.after_commit(lambda: calls.append("commit"))
    assert calls == ["rollback"]
    assert database.read_document("memory", scope) is None
    assert database.state_version(scope) == 0


def test_commit_hooks_run_after_db_commit_and_can_observe_new_state(database, scope):
    calls = []
    with use_unit_of_work(scope, database=database) as unit:
        unit.write_document("memory", scope, {"n": 1}, scope_parts=scope)
        unit.after_commit(lambda: calls.append(database.read_document("memory", scope)))
        unit.after_commit(lambda: calls.append(current_uow()))
        assert unit.commit() == 1
        assert unit.confirmed_version == 1
    assert calls == [{"n": 1}, None]


def test_mutation_and_multiple_documents_commit_in_one_transaction(database, scope):
    with use_unit_of_work(scope, database=database) as unit:
        unit.write_document("memory", scope, {"n": 1}, scope_parts=scope)
        unit.write_document("relationship", scope, {"score": 20}, scope_parts=scope)
        unit.add_mutation(lambda connection: connection.execute(insert(documents).values(
            namespace="confirmation", key_hash=parts_hash(scope), key_parts=list(scope),
            scope_parts=list(scope), payload={"version": unit.confirmed_version}, version=1)))
        unit.commit()
    assert database.state_version(scope) == 1
    assert database.read_document("confirmation", scope) == {"version": 1}


def test_failure_in_final_mutation_rolls_back_every_document_and_version(database, scope):
    calls = []
    def broken(connection):
        raise RuntimeError("injected finalization failure")
    with use_unit_of_work(scope, database=database) as unit:
        unit.write_document("memory", scope, {"n": 1}, scope_parts=scope)
        unit.write_document("relationship", scope, {"score": 20}, scope_parts=scope)
        unit.after_rollback(lambda: calls.append("rollback"))
        unit.add_mutation(broken)
        with pytest.raises(RuntimeError):
            unit.commit()
    assert database.read_document("memory", scope) is None
    assert database.read_document("relationship", scope) is None
    assert database.state_version(scope) == 0
    assert calls == ["rollback"]


def test_cas_rejects_stale_change_without_overwriting_new_state(database, scope):
    database.write_document("memory", scope, {"n": 1}, scope_parts=scope)
    old = UnitOfWork(scope, database=database)
    assert old.read_document("memory", scope) == {"n": 1}
    old.write_document("memory", scope, {"n": 2}, scope_parts=scope)
    database.write_document("memory", scope, {"n": 3}, scope_parts=scope)
    assert_error(old.commit, "STATE_VERSION_CONFLICT")
    assert database.read_document("memory", scope) == {"n": 3}
    assert database.state_version(scope) == 2


def test_cas_missing_row_race_rejects_second_creator(database, scope):
    old = UnitOfWork(scope, database=database)
    assert old.read_document("memory", scope) is None
    old.write_document("memory", scope, {"owner": "old"}, scope_parts=scope)
    database.write_document("memory", scope, {"owner": "new"}, scope_parts=scope)
    assert_error(old.commit, "STATE_VERSION_CONFLICT")
    assert database.read_document("memory", scope) == {"owner": "new"}


def test_nested_uow_shares_staging_and_rejects_other_scope(database, scope):
    with use_unit_of_work(scope, database=database) as outer:
        with use_unit_of_work(scope, database=database) as inner:
            assert inner is outer
            inner.write_document("memory", scope, {"n": 1}, scope_parts=scope)
        with pytest.raises(ScopeError) as error:
            with use_unit_of_work(("other",), database=database):
                pass
        assert error.value.code == "SCOPE_MISMATCH"
        outer.commit()
    assert database.read_document("memory", scope) == {"n": 1}


def test_write_cannot_change_scope_inside_current_uow(database, scope):
    with use_unit_of_work(scope, database=database) as unit:
        assert_error(lambda: unit.write_document("memory", ("other",), {}, scope_parts=("other",)), "SCOPE_MISMATCH")


def test_post_commit_hook_failure_is_unknown_but_database_stays_committed(database, scope):
    def broken():
        raise RuntimeError("injected cache failure")
    with use_unit_of_work(scope, database=database) as unit:
        unit.write_document("memory", scope, {"n": 1}, scope_parts=scope)
        unit.after_commit(broken)
        assert_error(unit.commit, "REQUEST_OUTCOME_UNKNOWN")
    assert database.read_document("memory", scope) == {"n": 1}
    assert database.state_version(scope) == 1


def test_new_engine_recovers_persisted_documents_and_epoch(tmp_path, scope):
    url = "sqlite:///" + str(tmp_path / "restart.sqlite")
    first = Database.from_url(url)
    first.initialize_schema()
    epoch = str(uuid4())
    first.write_document("memory", scope, {"memory_epoch": epoch}, scope_parts=scope)
    first.engine.dispose()
    second = Database.from_url(url)
    second.check_schema()
    assert second.read_document("memory", scope) == {"memory_epoch": epoch}
    assert second.state_version(scope) == 1
    second.engine.dispose()


def test_scope_prefix_listing_keeps_other_players_separate(database, scope):
    other = (scope[0], str(uuid4()), scope[2], scope[3])
    database.write_document("memory", scope, {"owner": 1}, scope_parts=scope)
    database.write_document("memory", other, {"owner": 2}, scope_parts=other)
    assert database.list_documents("memory", scope[:2]) == [(scope, {"owner": 1})]


def source_files(tmp_path, scope):
    memory, relationship = tmp_path / "memory", tmp_path / "relationship"
    folder = memory.joinpath(*scope)
    folder.mkdir(parents=True)
    memory_doc = {"memory_epoch": str(uuid4()), **MemorySnapshot().model_dump(mode="json")}
    (folder / "memory.json").write_text(json.dumps(memory_doc))
    folder = relationship.joinpath(*scope)
    folder.mkdir(parents=True)
    (folder / "relationship.json").write_text(RelationshipState().model_dump_json())
    return memory, relationship, memory_doc


def test_import_dry_run_excludes_unowned_legacy_and_preserves_sources(database, tmp_path, scope):
    memory, relationship, payload = source_files(tmp_path, scope)
    legacy = memory / "aesir" / "companion.alice" / "memory.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    report = import_json(None, memory, relationship)
    assert report["mode"] == "dry-run"
    assert len(report["sources"]) == 2
    assert report["excluded_unowned"] == ["aesir/companion.alice/memory.json"]
    assert database.read_document("memory", scope) is None
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.json")} == before


def test_import_apply_is_idempotent_and_keeps_original_epoch(database, tmp_path, scope):
    memory, relationship, payload = source_files(tmp_path, scope)
    first = import_json(database, memory, relationship, apply=True)
    assert first["imported"] == 2
    assert database.read_document("memory", scope) == payload
    assert database.state_version(scope) == 1
    second = import_json(database, memory, relationship, apply=True)
    assert (second["imported"], second["unchanged"]) == (0, 2)
    assert database.state_version(scope) == 1


def test_import_conflict_rolls_back_earlier_staged_documents(database, tmp_path, scope):
    memory, relationship, _ = source_files(tmp_path, scope)
    database.write_document("relationship", scope, {"value": 88}, scope_parts=scope)
    assert_error(lambda: import_json(database, memory, relationship, apply=True), "MIGRATION_CONFLICT")
    assert database.read_document("memory", scope) is None
    assert database.read_document("relationship", scope) == {"value": 88}


def test_invalid_source_prevents_any_import(database, tmp_path, scope):
    memory, relationship, _ = source_files(tmp_path, scope)
    (relationship.joinpath(*scope) / "relationship.json").write_text('{"value": 200}')
    with pytest.raises(ValueError):
        import_json(database, memory, relationship, apply=True)
    assert database.read_document("memory", scope) is None


def test_backup_restore_checks_hash_and_requires_empty_target(database, tmp_path, scope):
    database.write_document("memory", scope, {"memory_epoch": str(uuid4())}, scope_parts=scope)
    database.write_document("confirmation", (*scope, "event-id"), {"applied": True}, scope_parts=scope)
    output = tmp_path / "backup.json"
    backup = backup_database(database, output)
    assert backup["table_counts"]["documents"] == 2
    if os.name == "posix":
        assert output.stat().st_mode & 0o077 == 0
    target = Database.from_url("sqlite:///" + str(tmp_path / "restored.sqlite"))
    target.initialize_schema()
    dryrun = restore_database(target, output)
    assert dryrun["mode"] == "dry-run"
    assert target.read_document("memory", scope) is None
    restore_database(target, output, apply=True)
    assert target.read_document("memory", scope) == database.read_document("memory", scope)
    assert target.read_document("confirmation", (*scope, "event-id")) == {"applied": True}
    assert target.state_version(scope) == database.state_version(scope)
    assert_error(lambda: restore_database(target, output, apply=True), "RESTORE_TARGET_NOT_EMPTY")
    target.engine.dispose()


def test_corrupt_backup_never_writes_target(database, tmp_path, scope):
    output = tmp_path / "backup.json"
    backup_database(database, output)
    data = json.loads(output.read_text())
    data["payload"]["schema_version"] = 999
    output.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        restore_database(database, output, apply=True)


def test_backup_cannot_replace_existing_file(database, tmp_path):
    output = tmp_path / "backup.json"
    output.write_text("preserve")
    with pytest.raises(FileExistsError):
        backup_database(database, output)
    assert output.read_text() == "preserve"


def test_backup_rejects_other_web_roots_without_creating_any_file(database):
    if os.name != "posix":
        pytest.skip("Linux deployment web root boundary")
    with pytest.raises(ValueError, match="outside"):
        backup_database(database, Path("/www/wwwroot/another-site/private-backup.json"))


def test_backup_rejects_nonprivate_parent(database, tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX private directory permissions")
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        backup_database(database, shared / "backup.json")
    assert not (shared / "backup.json").exists()


def test_configured_sqlite_url_requires_explicit_test_mode(tmp_path, monkeypatch):
    from app.persistence.database import get_database, reset_database
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    monkeypatch.setenv("AESIR_SCOPE_SQLITE_TEST_MODE", "false")
    monkeypatch.setenv("AESIR_SCOPE_DATABASE_URL_FILE", "")
    monkeypatch.setenv("AESIR_SCOPE_DATABASE_URL", "sqlite:///" + str(tmp_path / "must-not-open.sqlite"))
    reset_database()
    try:
        assert_error(get_database, "STATE_UNAVAILABLE")
        assert not (tmp_path / "must-not-open.sqlite").exists()
    finally:
        reset_database()


def test_mysql_schema_gate_rejects_single_precision_timestamp_columns(database, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy import Float
    import app.persistence.database as persistence
    from app.persistence.schema import metadata
    monkeypatch.setattr(database, "_check_server_version", lambda: None)
    monkeypatch.setattr(database.engine.dialect, "name", "mysql")
    def columns(name):
        return [{"name": column.name, "type": Float()} for column in metadata.tables[name].c]
    monkeypatch.setattr(persistence, "inspect", lambda connection: SimpleNamespace(get_columns=columns))
    assert_error(database.check_schema, "DATABASE_SCHEMA_MISMATCH")


def test_restore_never_reactivates_credentials_revoked_after_the_backup(database, tmp_path, monkeypatch):
    from app.persistence import auth
    monkeypatch.setattr(auth, "_engine", lambda: database.engine)
    player, save = uuid4(), uuid4()
    auth.register_player("aesir", player)
    auth.grant_save("aesir", player, save)
    token = auth.issue_token("aesir", player, ttl_seconds=3600)
    assert auth.authenticate_token(token).player_id == player
    output = tmp_path / "before-revocation.json"
    backup_database(database, output)
    original_bytes = output.read_bytes()
    assert json.loads(original_bytes)["payload"]["tables"]["access_credentials"][0]["revoked"] is False
    auth.revoke_token(auth.token_id(token))
    assert_error(lambda: auth.authenticate_token(token), "IDENTITY_REQUIRED")
    target = Database.from_url("sqlite:///" + str(tmp_path / "restored-access.sqlite"))
    target.initialize_schema()
    dryrun = restore_database(target, output)
    assert dryrun["credentials_to_revoke"] == 1
    assert dryrun["credentials_revoked"] == 0
    result = restore_database(target, output, apply=True)
    assert result["credential_policy"] == "revoke_all_restored"
    assert result["credentials_revoked"] == 1
    monkeypatch.setattr(auth, "_engine", lambda: target.engine)
    assert_error(lambda: auth.authenticate_token(token), "IDENTITY_REQUIRED")
    fresh = auth.issue_token("aesir", player, ttl_seconds=3600)
    assert auth.authenticate_token(fresh).save_ids == frozenset({save})
    assert output.read_bytes() == original_bytes
    target.engine.dispose()
