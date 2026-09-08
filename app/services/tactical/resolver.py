"""v0.2 `/v1/tactical/resolve` 的规则版策略（草案 §5）。

输入语义意图 + 战斗状态快照，输出带 ``reason_codes`` 的决策。原则：
- 只引用快照中 ``ready`` 的能力；不可用时绝不虚构动作（``not_actionable``）。
- 艾莉蓝量过低时倾向保守（治疗优先级仍最高，但爆发/护盾让位）。
- ``authority`` 仅描述来源，UE 拥有最终否决权。

策略刻意保持为可解释的决策表：每个分支产出可读的 reason_codes，答辩时
能解释「每个决策为何发生」。
"""

from uuid import uuid4

from app.schemas.combat_context import CombatContext
from app.schemas.tactical_decision import (
    DecisionAction,
    Expires,
    TacticalDecision,
)
from app.schemas.tactical_intent import TacticalIntent

# 能力目录（与 v0.2 草案 §3 的示例快照一致；UE 上传什么就用什么，这里只做映射）
ABIL_MAJOR_HEAL = "ability.alice.major_heal"
ABIL_QUICK_HEAL = "ability.alice.quick_heal"
ABIL_SHIELD = "ability.alice.shield"
ABIL_EXPLOSION = "ability.alice.explosion"

PLAYER_HP_CRITICAL = 30   # 低于此阈值用强效治疗
PLAYER_HP_LOW = 70        # 低于此阈值用快速治疗
COMPANION_MP_LOW = 20     # 艾莉蓝量低于此值走保守策略
BOSS_MELEE_RANGE_M = 5.0  # 玩家贴脸判定（reason code 用）


def _is_ready(ctx: CombatContext, ability_id: str) -> bool:
    return ctx.companion.ability_states.get(ability_id) == "ready"


def _action(
    *,
    ctx: CombatContext,
    type_: str,
    ability_id: str | None = None,
    target_id: str | None = None,
    priority: int,
    expires: Expires | None = None,
    authority: str = "player_requested",
) -> DecisionAction:
    return DecisionAction(
        order_id=str(uuid4()),
        agent_id=ctx.companion.id,
        type=type_,
        ability_id=ability_id,
        target_id=target_id,
        priority=priority,
        expires=expires or Expires(),
        authority=authority,
    )


def _not_actionable(intent_id: str, reasons: list[str], explanation: str) -> TacticalDecision:
    return TacticalDecision(
        decision_id=str(uuid4()),
        status="not_actionable",
        intent_id=intent_id,
        action=None,
        reason_codes=reasons,
        explanation=explanation,
    )


def resolve_intent(intent: TacticalIntent, ctx: CombatContext) -> TacticalDecision:
    """按意图分发到三类策略（治疗/保护、爆发、撤退与跟随）。"""
    mp_low = ctx.companion.mp_percent < COMPANION_MP_LOW
    handlers = {
        "support_heal_player": _heal,
        "support_protect_player": _protect,
        "burst_boss": _burst,
        "prepare_burst_on_stun": _burst,
        "focus_fire_boss": _burst,
        "retreat_and_survive": _retreat,
        "follow_player": _follow,
    }
    handler = handlers.get(intent.intent_id)
    if handler is None:
        return _not_actionable(intent.intent_id, ["INTENT_NOT_SUPPORTED"], "暂不支持该意图。")
    return handler(intent, ctx, mp_low)


# ---------------------------------------------------------------------------
# 治疗 / 保护
# ---------------------------------------------------------------------------
def _heal(intent: TacticalIntent, ctx: CombatContext, mp_low: bool) -> TacticalDecision:
    hp = ctx.player.hp_percent
    reasons: list[str] = []

    if hp <= PLAYER_HP_CRITICAL and _is_ready(ctx, ABIL_MAJOR_HEAL):
        if ctx.player.distance_to_boss_m <= BOSS_MELEE_RANGE_M:
            reasons.append("BOSS_IN_MELEE_RANGE")
        reasons += ["PLAYER_HP_CRITICAL", "MAJOR_HEAL_READY"]
        return TacticalDecision(
            decision_id=str(uuid4()),
            status="actionable",
            intent_id=intent.intent_id,
            action=_action(
                ctx=ctx,
                type_="cast_ability",
                ability_id=ABIL_MAJOR_HEAL,
                target_id=ctx.player.id,
                priority=95,
                expires=Expires(type="immediate"),
            ),
            reason_codes=reasons,
            explanation="玩家生命值危急，强效治疗当前可用。",
        )

    if hp <= PLAYER_HP_LOW and _is_ready(ctx, ABIL_QUICK_HEAL):
        return TacticalDecision(
            decision_id=str(uuid4()),
            status="actionable",
            intent_id=intent.intent_id,
            action=_action(
                ctx=ctx,
                type_="cast_ability",
                ability_id=ABIL_QUICK_HEAL,
                target_id=ctx.player.id,
                priority=85,
                expires=Expires(type="immediate"),
            ),
            reason_codes=["PLAYER_HP_LOW", "QUICK_HEAL_READY"],
            explanation="玩家生命值偏低，快速治疗当前可用。",
        )

    if hp > PLAYER_HP_LOW:
        return _not_actionable(
            intent.intent_id, ["PLAYER_HP_HEALTHY"], "玩家生命值健康，暂不需要治疗。"
        )
    if hp <= PLAYER_HP_CRITICAL:
        return _not_actionable(
            intent.intent_id,
            ["PLAYER_HP_CRITICAL", "HEAL_NOT_READY"],
            "玩家生命值危急但治疗技能当前不可用。",
        )
    return _not_actionable(
        intent.intent_id, ["PLAYER_HP_LOW", "HEAL_NOT_READY"], "治疗技能当前不可用。"
    )


def _protect(intent: TacticalIntent, ctx: CombatContext, mp_low: bool) -> TacticalDecision:
    if not _is_ready(ctx, ABIL_SHIELD):
        return _not_actionable(
            intent.intent_id, ["SHIELD_NOT_READY"], "护盾技能当前不可用。"
        )
    if mp_low:
        return _not_actionable(
            intent.intent_id, ["COMPANION_MP_LOW", "SHIELD_READY"], "蓝量过低，优先保留资源。"
        )
    reasons = ["SHIELD_READY"]
    if ctx.player.hp_percent <= PLAYER_HP_CRITICAL:
        reasons.insert(0, "PLAYER_HP_CRITICAL")
    return TacticalDecision(
        decision_id=str(uuid4()),
        status="actionable",
        intent_id=intent.intent_id,
        action=_action(
            ctx=ctx,
            type_="cast_ability",
            ability_id=ABIL_SHIELD,
            target_id=ctx.player.id,
            priority=80,
            expires=Expires(type="immediate"),
        ),
        reason_codes=reasons,
        explanation="护盾当前可用，可以为玩家抵挡伤害。",
    )


# ---------------------------------------------------------------------------
# 爆发
# ---------------------------------------------------------------------------
def _burst(intent: TacticalIntent, ctx: CombatContext, mp_low: bool) -> TacticalDecision:
    if not _is_ready(ctx, ABIL_EXPLOSION):
        return _not_actionable(
            intent.intent_id, ["EXPLOSION_NOT_READY"], "爆裂魔法当前不可用。"
        )
    if mp_low:
        return _not_actionable(
            intent.intent_id,
            ["COMPANION_MP_LOW", "EXPLOSION_READY"],
            "蓝量不足以支撑爆发，建议先恢复资源。",
        )
    if intent.intent_id == "prepare_burst_on_stun" and "state.stunned" not in ctx.boss.state_tags:
        # 等眩晕：登记到战斗结束，UE 在 Boss 进入眩晕时触发
        return TacticalDecision(
            decision_id=str(uuid4()),
            status="actionable",
            intent_id=intent.intent_id,
            action=_action(
                ctx=ctx,
                type_="cast_ability",
                ability_id=ABIL_EXPLOSION,
                target_id=ctx.boss.id,
                priority=80,
                expires=Expires(type="encounter_end"),
            ),
            reason_codes=["EXPLOSION_READY", "BOSS_NOT_STUNNED_YET"],
            explanation="爆裂魔法就绪；Boss 进入眩晕后施放。",
        )
    return TacticalDecision(
        decision_id=str(uuid4()),
        status="actionable",
        intent_id=intent.intent_id,
        action=_action(
            ctx=ctx,
            type_="cast_ability",
            ability_id=ABIL_EXPLOSION,
            target_id=ctx.boss.id,
            priority=85,
            expires=Expires(type="immediate"),
        ),
        reason_codes=["EXPLOSION_READY"],
        explanation="爆裂魔法就绪，立即对 Boss 施放。",
    )


# ---------------------------------------------------------------------------
# 撤退与跟随
# ---------------------------------------------------------------------------
def _retreat(intent: TacticalIntent, ctx: CombatContext, _mp_low: bool) -> TacticalDecision:
    return TacticalDecision(
        decision_id=str(uuid4()),
        status="actionable",
        intent_id=intent.intent_id,
        action=_action(
            ctx=ctx, type_="retreat", target_id=None, priority=90, expires=Expires(type="immediate")
        ),
        reason_codes=["RETREAT_REQUESTED"],
        explanation="知道了，先保命。",
    )


def _follow(intent: TacticalIntent, ctx: CombatContext, _mp_low: bool) -> TacticalDecision:
    return TacticalDecision(
        decision_id=str(uuid4()),
        status="actionable",
        intent_id=intent.intent_id,
        action=_action(
            ctx=ctx,
            type_="follow",
            target_id=ctx.player.id,
            priority=40,
        ),
        reason_codes=["FOLLOW_REQUESTED"],
        explanation="好的，我跟上你并保持施法距离。",
    )
