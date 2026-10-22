"""Opaque credentials, permissions and restart-safe player admission quotas."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.main import app
from app.persistence import auth
from app.persistence.database import Database, reset_database
from app.persistence.uow import use_unit_of_work
from app.scoped.context import NpcScope
from app.scoped.errors import ScopeError
from app.scoped.identity import Principal, check_permission
from scripts import manage_access


@pytest.fixture
def access(tmp_path, monkeypatch):
    monkeypatch.setenv("AESIR_GAME_ID", "aesir")
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    monkeypatch.setenv("AESIR_SCOPE_IDENTITY_BACKEND", "bearer")
    monkeypatch.setenv("AESIR_SCOPE_REQUEST_QUOTA_PER_MINUTE", "2")
    monkeypatch.setenv("AESIR_SCOPE_UPSTREAM_QUOTA_PER_DAY", "1")
    monkeypatch.setattr(auth, "_now", lambda: 1000.0)
    path = tmp_path / "access.sqlite3"
    database = Database.from_url(f"sqlite:///{path}")
    database.initialize_schema()
    reset_database(database)
    registered = []

    def player(permissions=("npc:use",), save=None):
        player_id, save_id = uuid4(), save or uuid4()
        auth.register_player("aesir", player_id)
        auth.grant_save("aesir", player_id, save_id)
        token = auth.issue_token("aesir", player_id, permissions=permissions)
        principal = auth.authenticate_token(token)
        registered.append(principal)
        return SimpleNamespace(player_id=player_id, save_id=save_id, token=token, principal=principal)

    yield SimpleNamespace(database=database, path=path, player=player)
    app.dependency_overrides.clear()
    reset_database()


def rejected(call, status, code):
    with pytest.raises(ScopeError) as result:
        call()
    assert (result.value.status_code, result.value.code) == (status, code)
    return result.value


def test_token_storage_has_only_hash_and_database_authorization(access):
    player = access.player()
    with access.database.engine.connect() as connection:
        row = connection.execute(select(auth.credentials)).mappings().one()
    assert player.token not in repr(dict(row))
    assert row["secret_hash"] not in player.token
    assert len(row["secret_hash"]) == 64
    assert row["permissions"] == "npc:use"
    assert player.principal.player_id == player.player_id
    assert player.principal.save_ids == frozenset({player.save_id})
    assert player.principal.permissions == frozenset({"npc:use"})
    assert str(player.principal.credential_id) == auth.token_id(player.token)


@pytest.mark.parametrize("token", [None, "", "aw1", "not-a-token", "aw1.x.y", "aw1." + "0" * 32 + "." + "x" * 43])
def test_invalid_credentials_are_uniform_401(access, token):
    error = rejected(lambda: auth.authenticate_token(token), 401, "IDENTITY_REQUIRED")
    assert "token" not in error.message.lower()


def test_expiry_at_exact_boundary_and_revocation_survive_database_reload(access, monkeypatch):
    player = access.player()
    short = auth.issue_token("aesir", player.player_id, ttl_seconds=10)
    monkeypatch.setattr(auth, "_now", lambda: 1009.9)
    assert auth.authenticate_token(short).player_id == player.player_id
    monkeypatch.setattr(auth, "_now", lambda: 1010.0)
    rejected(lambda: auth.authenticate_token(short), 401, "IDENTITY_REQUIRED")
    auth.revoke_token(player.principal.credential_id)
    fresh = Database.from_url(f"sqlite:///{access.path}")
    reset_database(fresh)
    rejected(lambda: auth.authenticate_token(player.token), 401, "IDENTITY_REQUIRED")


def test_save_authorization_and_player_disable_have_no_identity_cache(access):
    player = access.player()
    second = uuid4()
    auth.grant_save("aesir", player.player_id, second)
    assert auth.authenticate_token(player.token).save_ids == frozenset({player.save_id, second})
    auth.grant_save("aesir", player.player_id, player.save_id, active=False)
    assert auth.authenticate_token(player.token).save_ids == frozenset({second})
    auth.set_player_active("aesir", player.player_id, False)
    rejected(lambda: auth.authenticate_token(player.token), 401, "IDENTITY_REQUIRED")


@pytest.mark.parametrize("control", ["revoke", "save", "disable"])
def test_final_scope_check_revalidates_long_running_identity(access, control):
    player = access.player()
    scope = NpcScope("aesir", player.player_id, player.save_id, "companion.alice")
    with auth.use_principal(player.principal):
        auth.validate_current_principal(scope)
        if control == "revoke":
            auth.revoke_token(player.principal.credential_id)
        elif control == "save":
            auth.grant_save("aesir", player.player_id, player.save_id, active=False)
        else:
            auth.set_player_active("aesir", player.player_id, False)
        rejected(lambda: auth.validate_current_principal(scope),
                 403 if control == "save" else 401,
                 "SCOPE_FORBIDDEN" if control == "save" else "IDENTITY_REQUIRED")
    assert auth.current_principal() is None


def test_scope_revalidation_does_not_accept_another_player_or_game(access):
    first, second = access.player(), access.player()
    with auth.use_principal(first.principal):
        rejected(lambda: auth.validate_current_principal(NpcScope(
            "aesir", second.player_id, second.save_id, "companion.alice")), 403, "SCOPE_FORBIDDEN")
    auth.register_player("another-game", first.player_id)
    token = auth.issue_token("another-game", first.player_id)
    rejected(lambda: auth.authenticate_token(token), 401, "IDENTITY_REQUIRED")


def test_permissions_are_explicit_and_trusted_development_principals_remain_compatible(access):
    principal = access.player().principal
    check_permission(principal, "npc:use")
    rejected(lambda: check_permission(principal, "console:read"), 403, "PERMISSION_DENIED")
    rejected(lambda: check_permission(principal, "memory:reset"), 403, "PERMISSION_DENIED")
    assert {"console:read", "memory:reset"} <= Principal(uuid4(), frozenset()).permissions


def test_bearer_mode_forces_legacy_closed_and_limits_documentation(access):
    player = access.player()
    docs = access.player(permissions=("docs:read",))
    console = access.player(permissions=("console:read",))
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": f"Bearer {player.token}"}).status_code == 403
        assert client.get(path, headers={"Authorization": f"Bearer {docs.token}"}).status_code == 200
        assert client.get(path, headers={"Authorization": f"Bearer {console.token}"}).status_code == 200
    # Global test defaults deliberately set legacy_enabled=true. Bearer wins.
    result = client.post("/v1/companion/chat", headers={"Authorization": f"Bearer {player.token}"})
    assert result.status_code == 403
    assert result.json()["detail"]["code"] == "LEGACY_DISABLED"


def test_database_authentication_failure_is_generic_503_without_development_fallback(access, monkeypatch):
    player = access.player(permissions=("docs:read",))
    def fail():
        raise OperationalError("SECRET_DSN_WITH_PASSWORD", {}, Exception("PRIVATE_PROVIDER_KEY"))
    monkeypatch.setattr(access.database.engine, "connect", fail)
    response = TestClient(app).get("/openapi.json", headers={"Authorization": f"Bearer {player.token}"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUTH_UNAVAILABLE"
    assert "SECRET" not in response.text and "PRIVATE" not in response.text


def test_request_quota_is_per_player_and_shared_by_their_credentials(access):
    first, second = access.player(), access.player()
    extra = auth.authenticate_token(auth.issue_token("aesir", first.player_id))
    assert auth.reserve_request_quota(first.principal)["used"] == 1
    assert auth.reserve_request_quota(extra)["used"] == 2
    rejected(lambda: auth.reserve_request_quota(first.principal), 429, "REQUEST_QUOTA_EXCEEDED")
    assert auth.reserve_request_quota(second.principal)["used"] == 1


def test_upstream_reservation_survives_business_rollback_and_database_reload(access):
    player = access.player()
    scope = NpcScope("aesir", player.player_id, player.save_id, "companion.alice")
    with pytest.raises(RuntimeError):
        with auth.use_principal(player.principal), use_unit_of_work(scope, database=access.database):
            assert auth.reserve_upstream_quota()["used"] == 1
            raise RuntimeError("Business failed after a provider call")
    fresh = Database.from_url(f"sqlite:///{access.path}")
    reset_database(fresh)
    with auth.use_principal(player.principal):
        rejected(auth.reserve_upstream_quota, 429, "UPSTREAM_QUOTA_EXCEEDED")


def test_atomic_concurrent_reservation_cannot_overspend(access):
    player = access.player()
    def reserve(_):
        try:
            auth._reserve("aesir", player.player_id, "request", 60, 3)
            return "accepted"
        except ScopeError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert results.count("accepted") == 3, results
    assert set(results) == {"accepted", "REQUEST_QUOTA_EXCEEDED"}
    with access.database.engine.connect() as connection:
        assert connection.execute(select(auth.quota_usage.c.used)).scalar_one() == 3


def test_quota_rollover_uses_server_window_not_client_data(access, monkeypatch):
    player = access.player()
    assert auth.reserve_request_quota(player.principal)["used"] == 1
    auth.reserve_request_quota(player.principal)
    monkeypatch.setattr(auth, "_now", lambda: 1060.0)
    assert auth.reserve_request_quota(player.principal)["used"] == 1


def test_cli_token_is_only_written_to_new_private_file(access, tmp_path, capsys):
    player = access.player()
    output = tmp_path / "private.token"
    args = ["token-issue", "--player-id", str(player.player_id), "--output", str(output)]
    assert manage_access.main(args) == 0
    token = output.read_text().strip()
    assert auth.authenticate_token(token).player_id == player.player_id
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600
    before = output.read_bytes()
    with access.database.engine.connect() as connection:
        count = connection.execute(select(func.count()).select_from(auth.credentials)).scalar_one()
    assert manage_access.main(args) == 1
    assert output.read_bytes() == before
    with access.database.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(auth.credentials)).scalar_one() == count


def test_cli_write_failure_revokes_unpublished_credential_and_removes_file(access, tmp_path, monkeypatch, capsys):
    player = access.player()
    output = tmp_path / "unpublished.token"
    def fail(_):
        raise OSError("Private output failed")
    monkeypatch.setattr(manage_access.os, "fsync", fail)
    assert manage_access.main(["token-issue", "--player-id", str(player.player_id), "--output", str(output)]) == 1
    assert not output.exists()
    with access.database.engine.connect() as connection:
        rows = connection.execute(select(auth.credentials.c.revoked)).scalars().all()
    assert rows.count(True) == 1 and rows.count(False) == 1
    assert "aw1." not in capsys.readouterr().err


def test_cli_rejects_symlink_without_overwriting_target(access, tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX secure output semantics")
    player = access.player()
    target = tmp_path / "untouched"
    target.write_text("original")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert manage_access.main(["token-issue", "--player-id", str(player.player_id), "--output", str(link)]) == 1
    assert target.read_text() == "original"


def test_real_bearer_http_identity_ignores_self_reported_player_and_protects_permissions(access):
    player, other = access.player(), access.player()
    docs = access.player(permissions=("docs:read",))
    client = TestClient(app)
    params = {"save_id": str(player.save_id), "companion_id": "companion.alice"}
    missing = client.get("/v1/scoped/context", params=params)
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    headers = {"Authorization": f"Bearer {player.token}", "X-Player-Id": str(other.player_id)}
    response = client.get("/v1/scoped/context", params=params, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["scope"]["player_id"] == str(player.player_id)
    params["save_id"] = str(other.save_id)
    response = client.get("/v1/scoped/context", params=params, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SCOPE_FORBIDDEN"
    assert client.get("/v1/scoped/console/memory", headers=headers).status_code == 403
    assert client.post("/v1/scoped/console/memory/reset", headers=headers, json={}).status_code == 403
    assert client.get("/v1/scoped/context", params=params,
                      headers={"Authorization": f"Bearer {docs.token}"}).status_code == 403
    auth.revoke_token(player.principal.credential_id)
    assert client.get("/v1/scoped/context", params=params, headers=headers).status_code == 401


def test_no_credential_context_cannot_create_provider_quota_in_bearer_mode(access):
    rejected(auth.reserve_upstream_quota, 401, "IDENTITY_REQUIRED")
    rejected(lambda: auth.validate_current_principal(NpcScope(
        "aesir", uuid4(), uuid4(), "companion.alice")), 401, "IDENTITY_REQUIRED")


def test_bearer_cannot_fall_back_to_development_identity_when_sql_backend_is_disabled(access, monkeypatch):
    player = access.player(permissions=("docs:read",))
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "json")
    monkeypatch.setenv("AESIR_SCOPE_DEV_PLAYER_ID", str(uuid4()))
    monkeypatch.setenv("AESIR_SCOPE_DEV_SAVE_IDS", "[\"" + str(uuid4()) + "\"]")
    response = TestClient(app).get("/openapi.json", headers={"Authorization": f"Bearer {player.token}"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUTH_UNAVAILABLE"


@pytest.mark.parametrize("location", ["relative", "checkout", "web-root"])
def test_cli_rejects_source_and_static_output_paths_without_minting_token(access, location, capsys):
    player = access.player()
    if location == "relative":
        output = Path("must-not-create-credential.token")
    elif location == "checkout":
        output = Path(manage_access.__file__).resolve().parents[1] / f"must-not-create-{uuid4()}.token"
    else:
        if os.name != "posix":
            pytest.skip("POSIX static web root policy")
        output = Path("/www/wwwroot") / f"must-not-create-{uuid4()}.token"
    with access.database.engine.connect() as connection:
        before = connection.execute(select(func.count()).select_from(auth.credentials)).scalar_one()
    assert manage_access.main(["token-issue", "--player-id", str(player.player_id), "--output", str(output)]) == 1
    assert not output.exists()
    with access.database.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(auth.credentials)).scalar_one() == before
    assert "aw1." not in capsys.readouterr().err


def test_cli_rejects_nonprivate_parent_directory(access, tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX directory access policy")
    player = access.player()
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    output = directory / "must-not-create.token"
    assert manage_access.main(["token-issue", "--player-id", str(player.player_id), "--output", str(output)]) == 1
    assert not output.exists()
