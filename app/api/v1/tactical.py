"""v0.2 战术决策端点：语义意图 + 状态快照 → 上下文战术决策（草案 §5）。

首版为规则策略（source 固定 ``rule``）。v0.1 的 ``/v1/commands/parse`` 保持
不变，继续承担「文本到意图」的前半段；UE 可先 parse 再 resolve。
"""

from fastapi import APIRouter

from app.schemas.combat_context import CombatContext
from app.schemas.tactical_decision import (
    PROTOCOL_VERSION_V02,
    Observability,
    ResolveRequest,
    ResolveResponse,
    TacticalDecision,
)
from app.schemas.tactical_intent import TacticalIntent
from app.services.tactical.resolver import resolve_intent

router = APIRouter(prefix="/v1/tactical", tags=["tactical"])

# 与策略表配套的人设回复（emotion_id 来自 data/companions YAML 白名单）
_REPLIES = {
    "support_heal_player": "别硬撑，我这就把你拉回来。",
    "support_protect_player": "护盾来了，撑住！",
    "burst_boss": "交给我！这一击会送到位的。",
    "prepare_burst_on_stun": "好，等它露出破绽我放大招。",
    "focus_fire_boss": "明白，一起集火！",
    "retreat_and_survive": "知道了，先保命。别逞强。",
    "follow_player": "跟紧你就行，放心，我会留好施法距离。",
}


@router.post("/resolve", response_model=ResolveResponse)
def resolve_tactical(request: ResolveRequest) -> ResolveResponse:
    decision: TacticalDecision = resolve_intent(request.intent, request.combat_context)
    return ResolveResponse(
        protocol_version=PROTOCOL_VERSION_V02,
        request_id=request.request_id,
        recognized=decision is not None,
        source="rule",
        decision=decision,
        companion_reply={
            "reply_text": _REPLIES.get(request.intent.intent_id, "收到。"),
            "emotion_id": "emotion.serious" if decision.status == "actionable" else "emotion.thoughtful",
        },
        observability=Observability(
            normalized_text=request.intent.normalized_text,
            policy_revision="support-policy-001",
            used_snapshot_id=request.combat_context.snapshot_id,
        ),
    )
