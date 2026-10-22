"""可信主体边界；开发身份仅来自服务器配置，不能用请求体或header冒充。"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request

from app.config import get_settings
from app.scoped.context import NpcScope, safe_segment
from app.scoped.errors import ScopeError
from app.services.companion.profile_repository import (
    CompanionProfileError, UnknownCompanionError, get_registered_profile,
)


@dataclass(frozen=True)
class Principal:
    player_id: UUID
    save_ids: frozenset[UUID]
    # Default compatibility is reserved for trusted development/test principals.
    # Database Bearer authentication always supplies the stored permissions.
    permissions: frozenset[str] = frozenset({"npc:use", "console:read", "memory:reset", "docs:read"})
    credential_id: UUID | None = None
    game_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_id", UUID(str(self.player_id)))
        object.__setattr__(self, "save_ids", frozenset(UUID(str(v)) for v in self.save_ids))
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        if self.credential_id is not None:
            object.__setattr__(self, "credential_id", UUID(str(self.credential_id)))
        if self.game_id is not None:
            safe_segment(self.game_id)


def get_principal(request: Request = None) -> Principal:
    """Trusted identity dependency; plaintext Bearer secrets are never logged."""
    settings = get_settings()
    backend = getattr(settings, "scope_identity_backend", "disabled")
    if backend == "bearer":
        from app.persistence.auth import authenticate_token

        authorization = request.headers.get("authorization", "") if request is not None else ""
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise ScopeError(401, "IDENTITY_REQUIRED", "A valid player credential is required.")
        return authenticate_token(parts[1])
    if backend != "development":
        raise ScopeError(401, "IDENTITY_REQUIRED", "A trusted player identity is required.")
    player_id = getattr(settings, "scope_dev_player_id", None)
    save_ids = getattr(settings, "scope_dev_save_ids", ())
    if player_id is None or not save_ids:
        raise ScopeError(401, "IDENTITY_REQUIRED", "No development identity is registered.")
    return Principal(player_id, frozenset(save_ids))


def check_permission(principal: Principal, permission: str) -> Principal:
    if permission not in principal.permissions:
        raise ScopeError(403, "PERMISSION_DENIED", "This credential cannot access the requested operation.")
    return principal


def require_permission(permission: str):
    """Use Depends(require_permission(...)) on the relevant scoped endpoint."""
    def authorized(principal: Principal = Depends(get_principal)) -> Principal:
        return check_permission(principal, permission)
    return authorized


def resolve_npc_scope(
    principal: Principal, save_id: UUID, companion_id: str
) -> NpcScope:
    save_id = UUID(str(save_id))
    if save_id not in principal.save_ids:
        raise ScopeError(403, "SCOPE_FORBIDDEN", "The requested save is not owned by this player.")
    try:
        safe_segment(companion_id)
        game_id = safe_segment(get_settings().game_id)
    except ValueError as error:
        raise ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Invalid scope identifier.") from error
    try:
        profile = get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise ScopeError(404, "COMPANION_UNKNOWN", "The companion is not registered for this game.") from error
    except CompanionProfileError as error:
        raise ScopeError(503, "STATE_UNAVAILABLE", "The companion profile is unavailable.") from error
    if profile.game_name.lower() != game_id.lower():
        raise ScopeError(404, "COMPANION_UNKNOWN", "The companion is not registered for this game.")
    return NpcScope(game_id, principal.player_id, save_id, companion_id)
