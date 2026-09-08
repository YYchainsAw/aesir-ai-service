"""v0.2 `/v1/combat/events` 的规则版事件策略（草案 §6）。

与 resolver 同一原则：
- 只引用快照中 ``ready`` 的能力；不可用时绝不虚构动作（``companion_action``
  返回 ``null``，反应与建议照常返回）。
- 艾莉蓝量过低时倾向保守。
- 治疗阈值等常量复用 resolver，保证事件策略与命令策略同源。
- 人设反应从 data/companions YAML 的 ``combat_event_reactions`` 读取，
  ID 不在白名单或配置缺失时回退到默认对话表现。
"""

from typing import Any

from app.schemas.combat_context import CombatContext
from app.schemas.combat_event import (
    CombatEvent,
    CombatEventRequest,
    CombatEventResponse,
    EventReaction,
    EventRecommendation,
    EventObservability,
)
from app.schemas.tactical_decision import DecisionAction, Expires
from app.services.companion.profile_repository import DialoguePresentation, get_profile
from app.services.tactical.resolver import (
    ABIL_EXPLOSION,
    ABIL_MAJOR_HEAL,
    ABIL_QUICK_HEAL,
    ABIL_SHIELD,
    COMPANION_MP_LOW,
    is_ability_ready,
)

POLICY_REVISION = "event-policy-001"

_FALLBACK_REACTION = EventReaction(
    reply_text="收到，我看着呢。",
    emotion_id="emotion.serious",
    gesture_id="gesture.think",
    facial_expression_id="face.thoughtful",
)


def _load_reaction(event_type: str) -> EventReaction:
    """从主队友 YAML 读取事件反应；配置缺失/越界时回退安全默认。"""
    profile = get_profile()
    reactions = profile.raw.get("combat_event_reactions")
    if isinstance(reactions, dict):
        entry = reactions.get(event_type)
        if isinstance(entry, dict):
            defaults: DialoguePresentation = profile.default_dialogue_response
            emotion = entry.get("emotion_id")
            gesture = entry.get("gesture_id")
            face = entry.get("facial_expression_id")
            if (
                isinstance(emotion, str) and emotion in profile.allowed_emotion_ids
                and isinstance(gesture, str) and gesture in profile.allowed_gesture_ids
                and isinstance(face, str) and face in profile.allowed_facial_expression_ids
            ):
                return EventReaction(
                    reply_text=entry.get("reply_text") or defaults.reply_text,
                    emotion_id=emotion,
                    gesture_id=gesture,
                    facial_expression_id=face,
                    interruptible=entry.get("interruptible", True),
                )
    return _FALLBACK_REACTION


def _action(
    ctx: CombatContext,
    *,
    ability_id: str,
    target_id: str,
    priority: int,
    expires: Expires | None = None,
) -> DecisionAction:
    from uuid import uuid4

    return DecisionAction(
        order_id=str(uuid4()),
        agent_id=ctx.companion.id,
        type="cast_ability",
        ability_id=ability_id,
        target_id=target_id,
        priority=priority,
        expires=expires or Expires(type="immediate"),
        authority="event_policy",
    )


def _response(
    request: CombatEventRequest,
    *,
    reaction: EventReaction,
    recommendation: EventRecommendation | None,
    companion_action: DecisionAction | None,
) -> CombatEventResponse:
    return CombatEventResponse(
        protocol_version="0.2",
        request_id=request.request_id,
        event_id=request.event.event_id,
        source="rule",
        reaction=reaction,
        recommendation=recommendation,
        companion_action=companion_action,
        observability=EventObservability(
            policy_revision=POLICY_REVISION,
            used_snapshot_id=request.combat_context.snapshot_id,
        ),
    )


def _evt_player_hp_critical(request: CombatEventRequest, ctx: CombatContext) -> CombatEventResponse:
    action = None
    reasons = ["PLAYER_HP_CRITICAL"]
    if is_ability_ready(ctx, ABIL_MAJOR_HEAL):
        action = _action(ctx, ability_id=ABIL_MAJOR_HEAL, target_id=ctx.player.id, priority=90)
        reasons.append("MAJOR_HEAL_READY")
    elif is_ability_ready(ctx, ABIL_QUICK_HEAL):
        action = _action(ctx, ability_id=ABIL_QUICK_HEAL, target_id=ctx.player.id, priority=90)
        reasons.append("QUICK_HEAL_READY")
    else:
        reasons.append("HEAL_NOT_READY")
    return _response(
        request,
        reaction=_load_reaction("player_hp_critical"),
        recommendation=EventRecommendation(
            type="retreat_or_defend",
            target_id=ctx.player.id,
            reason_codes=reasons,
            display_text="你的血量危急，注意躲避伤害。",
        ),
        companion_action=action,
    )


def _evt_boss_stun_near(request: CombatEventRequest, ctx: CombatContext) -> CombatEventResponse:
    reasons = ["BOSS_STUN_NEAR"]
    if is_ability_ready(ctx, ABIL_EXPLOSION):
        reasons.append("EXPLOSION_READY")
    else:
        reasons.append("EXPLOSION_NOT_READY")
    return _response(
        request,
        reaction=_load_reaction("boss_stun_near"),
        recommendation=EventRecommendation(
            type="hold_burst",
            target_id=ctx.boss.id,
            reason_codes=reasons,
            display_text="Boss 快要被控住了，把爆发留到眩晕窗口。",
        ),
        # 等待窗口：不产出动作，等 boss_stunned 事件再触发。
        companion_action=None,
    )


def _evt_boss_stunned(request: CombatEventRequest, ctx: CombatContext) -> CombatEventResponse:
    reasons = ["BOSS_STUNNED", "BURST_WINDOW_OPEN"]
    action = None
    if not is_ability_ready(ctx, ABIL_EXPLOSION):
        reasons.append("EXPLOSION_NOT_READY")
    elif ctx.companion.mp_percent < COMPANION_MP_LOW:
        reasons.append("COMPANION_MP_LOW")
    else:
        reasons.append("EXPLOSION_READY")
        remaining = ctx.boss.stunned_remaining_seconds
        expires = (
            Expires(type="before_seconds", remaining_seconds=remaining)
            if remaining is not None
            else Expires(type="immediate")
        )
        action = _action(
            ctx, ability_id=ABIL_EXPLOSION, target_id=ctx.boss.id, priority=85, expires=expires
        )
    return _response(
        request,
        reaction=_load_reaction("boss_stunned"),
        recommendation=EventRecommendation(
            type="focus_fire",
            target_id=ctx.boss.id,
            reason_codes=reasons,
            display_text="Boss 眩晕中，建议集火。",
        ),
        companion_action=action,
    )


def _evt_boss_enraged(request: CombatEventRequest, ctx: CombatContext) -> CombatEventResponse:
    reasons = ["BOSS_ENRAGED"]
    action = None
    if is_ability_ready(ctx, ABIL_SHIELD):
        action = _action(ctx, ability_id=ABIL_SHIELD, target_id=ctx.player.id, priority=70)
        reasons.append("SHIELD_READY")
    else:
        reasons.append("SHIELD_NOT_READY")
    return _response(
        request,
        reaction=_load_reaction("boss_enraged"),
        recommendation=EventRecommendation(
            type="retreat_or_defend",
            target_id=ctx.boss.id,
            reason_codes=reasons,
            display_text="Boss 狂暴了，注意躲避高伤害技能。",
        ),
        companion_action=action,
    )


def _evt_companion_mp_low(request: CombatEventRequest, ctx: CombatContext) -> CombatEventResponse:
    return _response(
        request,
        reaction=_load_reaction("companion_mp_low"),
        recommendation=EventRecommendation(
            type="conserve_resources",
            target_id=ctx.companion.id,
            reason_codes=["COMPANION_MP_LOW"],
            display_text="艾莉蓝量不足，建议让她节省技能。",
        ),
        companion_action=None,
    )


def _evt_boss_defeated(request: CombatEventRequest, ctx: CombatContext) -> CombatEventResponse:
    return _response(
        request,
        reaction=_load_reaction("boss_defeated"),
        recommendation=None,
        companion_action=None,
    )


_HANDLERS = {
    "player_hp_critical": _evt_player_hp_critical,
    "boss_stun_near": _evt_boss_stun_near,
    "boss_stunned": _evt_boss_stunned,
    "boss_enraged": _evt_boss_enraged,
    "companion_mp_low": _evt_companion_mp_low,
    "boss_defeated": _evt_boss_defeated,
}


def handle_combat_event(request: CombatEventRequest) -> CombatEventResponse:
    """按事件类型分发；与 resolver 一样保持可解释的决策表结构。"""
    handler = _HANDLERS.get(request.event.event_type)
    if handler is None:  # pragma: no cover - schema 已用 Literal 限定
        raise ValueError(f"Unsupported event_type: {request.event.event_type}")
    return handler(request, request.combat_context)
