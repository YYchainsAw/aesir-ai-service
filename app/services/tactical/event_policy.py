"""事件策略：v0.2 `/v1/combat/events` 与 v0.3 `/v1/world/events` 的统一决策层。

与 resolver 同一原则：
- 只引用快照中 ``ready`` 的能力；不可用时绝不虚构动作（``companion_action``
  返回 ``null``，反应与建议照常返回）。
- 艾莉蓝量过低时倾向保守。
- 治疗阈值等常量复用 resolver，保证事件策略与命令策略同源。
- 人设反应从 data/personas 人格包读取（战斗类 ``combat_event_reactions``、
  生活类 ``world_event_reactions``），ID 不在白名单或配置缺失时回退默认表现。

两个通道共享同一张幂等表（T061）：缓存的是与响应 schema 无关的
``EventEvaluation``，各自组装自己的响应。关系计分只在评估阶段发生一次，
且位于幂等检查之后（FR-033 / SC-007）。
"""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

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
from app.schemas.world_event import WorldEventObservability, WorldEventReaction, WorldEventRequest, WorldEventResponse
from app.services.companion.profile_repository import (
    CompanionProfileError,
    DialoguePresentation,
    get_registered_profile,
)
from app.services.memory.experiences import record_world_event_experience
from app.services.relationship.policy import get_policy as get_relationship_policy
from app.services.relationship.state import RelationshipStoreError, get_relationship_store
from app.services.tactical.policy import get_policy
from app.services.tactical.resolver import (
    ABIL_EXPLOSION,
    ABIL_MAJOR_HEAL,
    ABIL_QUICK_HEAL,
    ABIL_SHIELD,
    COMPANION_MP_LOW,
    is_ability_ready,
)

# 阈值/优先级/版本号与 resolver 同源：data/policy/tactical_policy.yaml
_policy = get_policy()
POLICY_REVISION = _policy.event_revision

_FALLBACK_REACTION = EventReaction(
    reply_text="收到，我看着呢。",
    emotion_id="emotion.serious",
    gesture_id="gesture.think",
    facial_expression_id="face.thoughtful",
)


def _game_id_for(companion_id: str) -> str:
    """从已登记角色 profile 取 game_id；未登记时回退默认 aesir。"""
    try:
        return get_registered_profile(companion_id).game_name.lower()
    except CompanionProfileError:
        return "aesir"


def _load_reaction(
    event_type: str, *, companion_id: str, section: str = "combat_event_reactions"
) -> EventReaction:
    """从指定角色 YAML 的指定段落读取事件反应；配置缺失/越界时回退安全默认。

    战斗类走 ``combat_event_reactions``，生活类走 ``world_event_reactions``；
    两段结构一致，校验路径共用（FR-002：模型输出不可信，表现 ID 必须过白名单）。
    未登记角色返回默认反应，不中断事件处理。
    """
    try:
        profile = get_registered_profile(companion_id)
    except CompanionProfileError:
        return _FALLBACK_REACTION

    reactions = profile.raw.get(section)
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
        action = _action(
            ctx, ability_id=ABIL_MAJOR_HEAL, target_id=ctx.player.id,
            priority=_policy.priorities.event_major_heal,
        )
        reasons.append("MAJOR_HEAL_READY")
    elif is_ability_ready(ctx, ABIL_QUICK_HEAL):
        action = _action(
            ctx, ability_id=ABIL_QUICK_HEAL, target_id=ctx.player.id,
            priority=_policy.priorities.event_quick_heal,
        )
        reasons.append("QUICK_HEAL_READY")
    else:
        reasons.append("HEAL_NOT_READY")
    return _response(
        request,
        reaction=_load_reaction("player_hp_critical", companion_id=ctx.companion.id),
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
        reaction=_load_reaction("boss_stun_near", companion_id=ctx.companion.id),
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
            ctx, ability_id=ABIL_EXPLOSION, target_id=ctx.boss.id,
            priority=_policy.priorities.event_burst, expires=expires,
        )
    return _response(
        request,
        reaction=_load_reaction("boss_stunned", companion_id=ctx.companion.id),
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
        action = _action(
            ctx, ability_id=ABIL_SHIELD, target_id=ctx.player.id,
            priority=_policy.priorities.event_shield,
        )
        reasons.append("SHIELD_READY")
    else:
        reasons.append("SHIELD_NOT_READY")
    return _response(
        request,
        reaction=_load_reaction("boss_enraged", companion_id=ctx.companion.id),
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
        reaction=_load_reaction("companion_mp_low", companion_id=ctx.companion.id),
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
        reaction=_load_reaction("boss_defeated", companion_id=ctx.companion.id),
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


# ---------------------------------------------------------------------------
# 评估结果与统一幂等缓存（两个通道共享）
# ---------------------------------------------------------------------------

# 关系联动状态：决定可解释原因码，也区分「事件不涉及关系」与「关系降级」
_REL_SKIPPED = "skipped"          # 事件不在关系策略表内，未触碰关系存储
_REL_SCORED = "scored"            # 已计分（delta 为 0 表示被冷却窗口/每日上限拦截）
_REL_UNAVAILABLE = "unavailable"  # 关系存储故障，降级不中断（FR-041）


@dataclass(frozen=True)
class EventEvaluation:
    """与响应 schema 无关的评估结果。

    幂等缓存存它而非响应对象，是为了让 v0.2 与 v0.3 两个通道共用一张表：
    同一 ``event_id`` 无论经哪个通道上报，都只评估一次、只产生一次副作用。
    """

    reaction: EventReaction
    recommendation: EventRecommendation | None = None
    action: DecisionAction | None = None
    reason_codes: tuple[str, ...] = ()  # 评估期确定的附加原因码
    relationship_status: str = _REL_SKIPPED
    relationship_stage: str = ""
    relationship_delta: int = 0
    policy_revision: str = POLICY_REVISION
    used_snapshot_id: str = ""


_MAX_CACHE = 1024  # 有界缓存：单进程内存足够，防长会话膨胀

_seen_events: "OrderedDict[tuple[str, str, str], EventEvaluation]" = OrderedDict()
_seen_events_lock = Lock()


def _resolve(
    key: tuple[str, str, str], evaluate: Callable[[], EventEvaluation]
) -> tuple[EventEvaluation, bool]:
    """统一幂等入口：命中则回放（``duplicate=True``），未命中则评估并登记。

    幂等键含角色维度（SDD T012 / FR-044）：不同队友对同一事件的同一标识
    各自独立处理，状态互不干扰。第三段为遭遇维度——战斗类事件带
    ``encounter_id``（跨遭遇的同标识是两次独立事件），生活类以空串占位。

    评估在锁内进行：生活事件的关系计分是副作用，若挪到锁外，并发重试可能
    在两次查表之间都未命中而重复计分（SC-007）。
    """
    with _seen_events_lock:
        cached = _seen_events.get(key)
        if cached is not None:
            return cached, True
        evaluation = evaluate()
        _seen_events[key] = evaluation
        if len(_seen_events) > _MAX_CACHE:
            _seen_events.popitem(last=False)  # 淘汰最旧事件
    return evaluation, False


def _reset_seen_events() -> None:
    """清空幂等缓存（仅测试用）。"""
    with _seen_events_lock:
        _seen_events.clear()


# ---------------------------------------------------------------------------
# v0.2 战斗通道
# ---------------------------------------------------------------------------


def _evaluate_combat(request: CombatEventRequest) -> EventEvaluation:
    """跑既有决策表，把响应折成评估结果（决策表本身不改写）。"""
    response = _HANDLERS[request.event.event_type](request, request.combat_context)
    return EventEvaluation(
        reaction=response.reaction,
        recommendation=response.recommendation,
        action=response.companion_action,
        policy_revision=response.observability.policy_revision,
        used_snapshot_id=response.observability.used_snapshot_id,
    )


def _combat_response(
    request: CombatEventRequest, evaluation: EventEvaluation, *, duplicate: bool
) -> CombatEventResponse:
    return CombatEventResponse(
        protocol_version="0.2",
        request_id=request.request_id,
        event_id=request.event.event_id,
        source="rule",
        reaction=evaluation.reaction,
        recommendation=evaluation.recommendation,
        companion_action=evaluation.action,
        observability=EventObservability(
            policy_revision=evaluation.policy_revision,
            used_snapshot_id=evaluation.used_snapshot_id,
        ),
        duplicate=duplicate,
    )


def handle_combat_event(request: CombatEventRequest) -> CombatEventResponse:
    """按事件类型分发；与 resolver 一样保持可解释的决策表结构。

    策划书 §4.2 要求 Python 也支持幂等：同一 ``encounter_id + event_id``
    的网络重试回放首次响应（同一 ``order_id``、同一台词），并标记
    ``duplicate: true``，防止艾莉重复说话或重复施法。
    """
    if request.event.event_type not in _HANDLERS:  # pragma: no cover - schema 已用 Literal 限定
        raise ValueError(f"Unsupported event_type: {request.event.event_type}")
    key = (
        request.combat_context.companion.id,
        request.combat_context.encounter_id,
        request.event.event_id,
    )
    evaluation, duplicate = _resolve(key, lambda: _evaluate_combat(request))
    if not duplicate:
        # 与 v0.3 世界通道同一张幂等表：同一事件经两个通道上报也只记一次。
        record_world_event_experience(
            request.combat_context.companion.id,
            request.event.event_type,
            game_id=_game_id_for(request.combat_context.companion.id),
            occurred_at=request.event.occurred_at,
        )
    return _combat_response(request, evaluation, duplicate=duplicate)


# ---------------------------------------------------------------------------
# v0.3 世界通道：战斗类复用决策表，生活类走人设反应 + 关系联动
# ---------------------------------------------------------------------------

# 战斗类事件经世界通道上报但快照缺失时的建议文本（FR-025：不虚构动作）
_COMBAT_CONTEXT_MISSING_TEXT = "看不清局势，先稳住，别急着进攻。"

_relationship_policy = get_relationship_policy()


def _as_combat_request(request: WorldEventRequest, ctx: CombatContext) -> CombatEventRequest:
    """把世界通道的战斗类事件折成 v0.2 请求，复用既有决策表（不重写策略）。"""
    return CombatEventRequest(
        protocol_version="0.2",
        request_id=request.request_id,
        event=CombatEvent(
            event_id=request.event.event_id,
            event_type=request.event.event_type,
            occurred_at=request.event.occurred_at,
            sequence=request.event.sequence,
        ),
        combat_context=ctx,
    )


def _evaluate_world_combat(request: WorldEventRequest) -> EventEvaluation:
    ctx = request.world_context.combat
    if ctx is None:
        # 快照缺失：只给反应与保守建议，绝不猜动作。
        return EventEvaluation(
            reaction=_load_reaction(request.event.event_type, companion_id=request.companion_id),
            recommendation=EventRecommendation(
                type="hold_position",
                target_id=None,
                reason_codes=["COMBAT_CONTEXT_MISSING"],
                display_text=_COMBAT_CONTEXT_MISSING_TEXT,
            ),
            action=None,
            reason_codes=("COMBAT_CONTEXT_MISSING",),
        )
    return _evaluate_combat(_as_combat_request(request, ctx))


def _score_relationship(
    companion_id: str, event_type: str, occurred_at: str, *, game_id: str
) -> tuple[str, str, int]:
    """事件驱动关系计分（FR-014）；返回（状态, 阶段, 实际计分值）。

    不在关系策略表内的事件直接跳过——不去加载/写盘，也不谎报「未变化」。
    存储故障按 FR-041 降级：只标记状态，不向上抛，事件处理照常返回。
    """
    if event_type not in _relationship_policy.events:
        return _REL_SKIPPED, "", 0
    try:
        state, delta = get_relationship_store(companion_id, game_id=game_id).apply_event(
            event_type, occurred_at
        )
    except RelationshipStoreError:
        return _REL_UNAVAILABLE, "", 0
    return _REL_SCORED, state.stage, delta


def _evaluate_lifestyle(request: WorldEventRequest) -> EventEvaluation:
    event_type = request.event.event_type
    game_id = _game_id_for(request.companion_id)
    reaction = _load_reaction(
        event_type, companion_id=request.companion_id, section="world_event_reactions"
    )
    status, stage, delta = _score_relationship(
        request.companion_id, event_type, request.event.occurred_at, game_id=game_id
    )
    return EventEvaluation(
        reaction=reaction,
        recommendation=None,
        action=None,
        relationship_status=status,
        relationship_stage=stage,
        relationship_delta=delta,
    )


def _world_response(
    request: WorldEventRequest, evaluation: EventEvaluation, *, duplicate: bool
) -> WorldEventResponse:
    # 基础原因码 = 事件类型本身，便于按事件归因（T063 可解释性）
    reason_codes = [request.event.event_type.upper(), *evaluation.reason_codes]
    if evaluation.relationship_status == _REL_SCORED:
        reason_codes.append(
            "RELATIONSHIP_UPDATED" if evaluation.relationship_delta else "RELATIONSHIP_UNCHANGED"
        )
    elif evaluation.relationship_status == _REL_UNAVAILABLE:
        reason_codes.append("RELATIONSHIP_UNAVAILABLE")

    return WorldEventResponse(
        request_id=request.request_id,
        companion_id=request.companion_id,
        event_id=request.event.event_id,
        duplicate=duplicate,
        reaction=WorldEventReaction(
            reply_text=evaluation.reaction.reply_text,
            emotion_id=evaluation.reaction.emotion_id,
            gesture_id=evaluation.reaction.gesture_id,
            facial_expression_id=evaluation.reaction.facial_expression_id,
        ),
        recommendation_text=(
            evaluation.recommendation.display_text if evaluation.recommendation else None
        ),
        companion_action=evaluation.action,
        observability=WorldEventObservability(
            source="rule",
            policy_revision=evaluation.policy_revision,
            used_snapshot_id=request.world_context.snapshot_id,
            reason_codes=reason_codes,
            relationship_stage=evaluation.relationship_stage,
            relationship_stage_display=_relationship_stage_display(evaluation.relationship_stage),
            relationship_delta=evaluation.relationship_delta,
        ),
    )


def _relationship_stage_display(stage: str) -> str:
    """FIX-05：关系阶段中文展示名；空字符串或未知时返回空字符串。"""
    from app.services.relationship.policy import get_stage_display_name

    return get_stage_display_name(stage)


def handle_world_event(request: WorldEventRequest) -> WorldEventResponse:
    """世界事件统一入口（FR-032~FR-034）：战斗类与生活类共用一张幂等表。

    战斗类事件复用 v0.2 决策表（同一 ``event_id`` 经两个通道上报只处理一次）；
    生活类事件读人设 ``world_event_reactions`` 并联动关系数值。关系计分发生在
    幂等检查之后，网络重试不重复计分（SC-007）。
    """
    ctx = request.world_context.combat
    if request.event.event_type in _HANDLERS:
        key = (
            request.companion_id,
            ctx.encounter_id if ctx is not None else "",
            request.event.event_id,
        )
        evaluation, duplicate = _resolve(key, lambda: _evaluate_world_combat(request))
    else:
        key = (request.companion_id, "", request.event.event_id)
        evaluation, duplicate = _resolve(key, lambda: _evaluate_lifestyle(request))
    if not duplicate:
        # 共同经历入摘要层（记忆接线）：只在首次处理时写，重放不重复记。
        record_world_event_experience(
            request.companion_id,
            request.event.event_type,
            game_id=_game_id_for(request.companion_id),
            details=request.event.details,
            occurred_at=request.event.occurred_at,
            region_id=(
                request.world_context.region.region_id
                if request.world_context.region is not None
                else ""
            ),
        )
    return _world_response(request, evaluation, duplicate=duplicate)
