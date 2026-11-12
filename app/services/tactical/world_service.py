"""Shared world-event entry, including capability and companion checks."""
from fastapi import HTTPException

from app.schemas.world_event import WorldEventRequest, WorldEventResponse
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
)
from app.services.games.capability_gate import FEATURE_WORLD_EVENTS, require_event_declared
from app.services.tactical.event_policy import handle_world_event


def report_world_event(request: WorldEventRequest) -> WorldEventResponse:
    try:
        # FR-044：未登记角色明确拒绝，不静默回退到主队友人设。
        get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    # S4/T029：事件必须落在当前游戏档案声明内（L0 游戏只声明了少量生活事件）。
    require_event_declared(request.event.event_type, FEATURE_WORLD_EVENTS)
    return handle_world_event(request)
