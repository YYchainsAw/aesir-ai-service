"""世界事件入口（SDD T014 / FR-032~FR-034，协议 v0.3）。

战斗与生活两类事件统一处理；幂等键为 ``companion_id + event_id``：
同一事件重复上报（网络重试）回放首次结果并标记 ``duplicate: true``，
不产生新行为（FR-033）。

Phase 2 为骨架实现：反应回退到角色默认对话表现。战斗类事件并入既有
``event_policy`` 决策表在 T061 完成；关系事件联动（T062）、非战斗事件
反应配置（T060）随后接入。
"""

from collections import OrderedDict
from threading import Lock

from fastapi import APIRouter, HTTPException

from app.schemas.world_event import (
    WorldEventReaction,
    WorldEventRequest,
    WorldEventResponse,
    WorldEventObservability,
)
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
)

router = APIRouter(prefix="/v1/world", tags=["world"])

POLICY_REVISION = "world-skeleton-001"

_MAX_CACHE = 1024
_seen_world_events: "OrderedDict[tuple[str, str], WorldEventResponse]" = OrderedDict()
_seen_lock = Lock()


def _reset_seen_world_events() -> None:
    """清空幂等缓存（仅测试用）。"""
    with _seen_lock:
        _seen_world_events.clear()


def _default_reaction(request: WorldEventRequest) -> WorldEventResponse:
    profile = get_registered_profile(request.companion_id)
    default = profile.default_dialogue_response
    return WorldEventResponse(
        request_id=request.request_id,
        companion_id=request.companion_id,
        event_id=request.event.event_id,
        reaction=WorldEventReaction(
            reply_text=default.reply_text,
            emotion_id=default.emotion_id,
            gesture_id=default.gesture_id,
            facial_expression_id=default.facial_expression_id,
        ),
        observability=WorldEventObservability(
            source="rule",
            policy_revision=POLICY_REVISION,
            used_snapshot_id=request.world_context.snapshot_id,
            reason_codes=["EVENT_REACTION_DEFAULT"],
        ),
    )


@router.post("/events", response_model=WorldEventResponse)
def report_world_event(request: WorldEventRequest) -> WorldEventResponse:
    try:
        response = _default_reaction(request)
    except UnknownCompanionError as error:
        # FR-044：未登记角色明确拒绝。
        raise HTTPException(status_code=404, detail=str(error)) from error

    key = (request.companion_id, request.event.event_id)
    with _seen_lock:
        cached = _seen_world_events.get(key)
        if cached is not None:
            return cached.model_copy(
                update={"request_id": request.request_id, "duplicate": True}
            )
        _seen_world_events[key] = response
        if len(_seen_world_events) > _MAX_CACHE:
            _seen_world_events.popitem(last=False)
    return response
