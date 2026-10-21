"""开发主体只使用服务端登记；归属/目录错误必须在状态访问前拒绝。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.scoped import identity
from app.scoped.errors import ScopeError
from app.scoped.identity import Principal, get_principal, resolve_npc_scope
from app.services.companion.profile_repository import CompanionProfileError, UnknownCompanionError


def settings(monkeypatch, **kwargs):
    values = {"game_id": "aesir", "scope_identity_backend": "disabled",
              "scope_dev_player_id": None, "scope_dev_save_ids": []}
    values.update(kwargs)
    monkeypatch.setattr(identity, "get_settings", lambda: SimpleNamespace(**values))


def test_default_identity_is_disabled(monkeypatch):
    settings(monkeypatch)
    with pytest.raises(ScopeError) as raised:
        get_principal()
    assert (raised.value.status_code, raised.value.code) == (401, "IDENTITY_REQUIRED")


@pytest.mark.parametrize("player,saves", [(None, []), (None, [uuid4()]), (uuid4(), [])])
def test_development_requires_complete_preregistration(monkeypatch, player, saves):
    settings(monkeypatch, scope_identity_backend="development", scope_dev_player_id=player, scope_dev_save_ids=saves)
    with pytest.raises(ScopeError) as raised:
        get_principal()
    assert raised.value.status_code == 401


def test_development_identity_comes_only_from_server_configuration(monkeypatch):
    player, save = uuid4(), uuid4()
    settings(monkeypatch, scope_identity_backend="development", scope_dev_player_id=player, scope_dev_save_ids=[save])
    assert get_principal() == Principal(player, frozenset({save}))
    with pytest.raises(TypeError):
        get_principal(player_id=str(uuid4()))


def test_owned_save_and_registered_game_create_canonical_scope(monkeypatch):
    player, save = uuid4(), uuid4()
    settings(monkeypatch)
    monkeypatch.setattr(identity, "get_registered_profile", lambda companion: SimpleNamespace(game_name="Aesir"))
    scope = resolve_npc_scope(Principal(player, frozenset({save})), save, "companion.alice")
    assert scope.key == ("aesir", str(player), str(save), "companion.alice")


def test_unowned_save_is_rejected_before_profile_or_state_access(monkeypatch):
    settings(monkeypatch)
    monkeypatch.setattr(identity, "get_registered_profile", lambda companion: pytest.fail("profile must not be read"))
    with pytest.raises(ScopeError) as raised:
        resolve_npc_scope(Principal(uuid4(), frozenset()), uuid4(), "companion.alice")
    assert (raised.value.status_code, raised.value.code) == (403, "SCOPE_FORBIDDEN")


@pytest.mark.parametrize("companion", ["../alice", "/etc/passwd", "alice/bob", "alice\\bob", ".", "a" * 101])
def test_unsafe_character_id_does_not_reach_profile_lookup(monkeypatch, companion):
    save = uuid4()
    settings(monkeypatch)
    monkeypatch.setattr(identity, "get_registered_profile", lambda companion: pytest.fail("profile must not be read"))
    with pytest.raises(ScopeError) as raised:
        resolve_npc_scope(Principal(uuid4(), frozenset({save})), save, companion)
    assert (raised.value.status_code, raised.value.code) == (422, "INVALID_SCOPE_OR_TIMING")


@pytest.mark.parametrize("error,expected", [
    (UnknownCompanionError("unregistered"), (404, "COMPANION_UNKNOWN")),
    (CompanionProfileError("broken private path"), (503, "STATE_UNAVAILABLE")),
])
def test_profile_failures_are_stable_without_private_error_details(monkeypatch, error, expected):
    save = uuid4()
    settings(monkeypatch)

    def fail(companion):
        raise error

    monkeypatch.setattr(identity, "get_registered_profile", fail)
    with pytest.raises(ScopeError) as raised:
        resolve_npc_scope(Principal(uuid4(), frozenset({save})), save, "companion.alice")
    assert (raised.value.status_code, raised.value.code) == expected
    assert "private" not in raised.value.message


def test_other_game_profile_cannot_be_selected(monkeypatch):
    save = uuid4()
    settings(monkeypatch)
    monkeypatch.setattr(identity, "get_registered_profile", lambda companion: SimpleNamespace(game_name="other"))
    with pytest.raises(ScopeError) as raised:
        resolve_npc_scope(Principal(uuid4(), frozenset({save})), save, "companion.alice")
    assert raised.value.code == "COMPANION_UNKNOWN"


def test_error_detail_carries_request_correlation_without_leaking_exception():
    request_id = uuid4()
    assert ScopeError(409, "MEMORY_EPOCH_STALE", "Refresh context.", request_id).as_detail() == {
        "code": "MEMORY_EPOCH_STALE", "message": "Refresh context.", "request_id": str(request_id),
    }
