"""世界事件入口（SDD T057 / FR-032~FR-034，协议 v0.3）。

战斗与生活两类事件统一处理，是**事件驱动关系数值的唯一上报入口**：
UE 上报"玩家刚替艾莉挡了一刀"这类事实事件，服务端返回人设反应，
并按 ``data/policy/relationship_policy.yaml`` 调整关系数值。

幂等键为 ``companion_id + encounter_id + event_id``（战斗类带遭遇维度，
生活类以空串占位），与 v0.2 战斗通道共享同一张表：同一事件无论经哪个
通道上报（含网络重试）都只处理一次，关系数值不重复计分（FR-033 / SC-007）。

策略实现见 ``app.services.tactical.event_policy``；本模块只负责
HTTP 边界（未登记角色 404）。
"""

from fastapi import APIRouter, HTTPException

from app.schemas.world_event import WorldEventRequest, WorldEventResponse
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
)
from app.services.tactical.event_policy import handle_world_event

router = APIRouter(prefix="/v1/world", tags=["world"])


@router.post("/events", response_model=WorldEventResponse)
def report_world_event(request: WorldEventRequest) -> WorldEventResponse:
    try:
        # FR-044：未登记角色明确拒绝，不静默回退到主队友人设。
        get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return handle_world_event(request)
