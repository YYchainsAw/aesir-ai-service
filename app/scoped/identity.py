"""可信主体边界；开发身份仅来自服务器配置，不能用请求体或header冒充。"""

from dataclasses import dataclass
from uuid import UUID

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_id", UUID(str(self.player_id)))
        object.__setattr__(self, "save_ids", frozenset(UUID(str(v)) for v in self.save_ids))


def get_principal() -> Principal:
    """FastAPI可override的可信依赖；生产凭据验证将在第四步实现。"""
    settings = get_settings()
    if getattr(settings, "scope_identity_backend", "disabled") != "development":
        raise ScopeError(401, "IDENTITY_REQUIRED", "A trusted player identity is required.")
    player_id = getattr(settings, "scope_dev_player_id", None)
    save_ids = getattr(settings, "scope_dev_save_ids", ())
    if player_id is None or not save_ids:
        raise ScopeError(401, "IDENTITY_REQUIRED", "No development identity is registered.")
    return Principal(player_id, frozenset(save_ids))


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
