"""v0.2 战斗事件端点：UE 关键事件边沿 → 艾莉反应/建议/候选动作（草案 §6）。

首版为规则策略（source 固定 ``rule``）。反应台词从 data/personas 人格包读取，
路由不承载人设文案；动作候选仅在能力就绪且资源允许时返回。
"""

from fastapi import APIRouter

from app.schemas.combat_event import CombatEventRequest, CombatEventResponse
from app.services.games.capability_gate import FEATURE_COMBAT_EVENTS, require_l3
from app.services.tactical.event_policy import handle_combat_event

router = APIRouter(prefix="/v1/combat", tags=["combat"])


@router.post("/events", response_model=CombatEventResponse)
def report_combat_event(request: CombatEventRequest) -> CombatEventResponse:
    require_l3(FEATURE_COMBAT_EVENTS)
    return handle_combat_event(request)
