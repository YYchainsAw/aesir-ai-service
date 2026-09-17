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

# 阈值、优先级与能力目录都来自 data/policy/tactical_policy.yaml（策划书 §5.1/§6.2），
# 进程启动时加载快照——改 YAML 后重启生效。保留原常量名供 rl/ 基线引用。
from app.services.tactical.policy import get_policy  # noqa: E402

_policy = get_policy()

# 能力目录（FR-035）：ID 只在 tactical_policy.yaml 写一次，这里派生常量，
# 不再在代码里另写一份字面量。UE 上传什么就用什么，Python 只做映射。
ABIL_MAJOR_HEAL = _policy.abilities["major_heal"].id
ABIL_QUICK_HEAL = _policy.abilities["quick_heal"].id
ABIL_SHIELD = _policy.abilities["shield"].id
ABIL_EXPLOSION = _policy.abilities["explosion"].id
PLAYER_HP_CRITICAL = _policy.thresholds.player_hp_critical   # 低于此阈值用强效治疗
PLAYER_HP_LOW = _policy.thresholds.player_hp_low             # 低于此阈值用快速治疗
COMPANION_MP_LOW = _policy.thresholds.companion_mp_low       # 艾莉蓝量低于此值走保守策略
BOSS_MELEE_RANGE_M = _policy.thresholds.boss_melee_range_m   # 玩家贴脸判定（reason code 用）
POLICY_REVISION = _policy.revision


def is_ability_ready(ctx: CombatContext, ability_id: str) -> bool:
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


def resolve_intent(
    intent: TacticalIntent,
    ctx: CombatContext,
    relationship_stage: str | None = None,
) -> TacticalDecision:
    """按意图分发到三类策略（治疗/保护、爆发、撤退与跟随）。

    ``relationship_stage``（US2 / T039）非空时，决策结果再经关系阶段调制：
    资源投入意愿与服从度随阶段变化，全部落在 reason_codes（可解释）。
    缺省时行为与既有契约完全一致。
    """
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
    decision = handler(intent, ctx, mp_low)
    if relationship_stage:
        from app.services.relationship.effect import modulate_decision

        decision = modulate_decision(decision, relationship_stage, ctx)
    return decision


# ---------------------------------------------------------------------------
# 治疗 / 保护
# ---------------------------------------------------------------------------
def _heal(intent: TacticalIntent, ctx: CombatContext, mp_low: bool) -> TacticalDecision:
    hp = ctx.player.hp_percent
    reasons: list[str] = []

    if hp <= PLAYER_HP_CRITICAL and is_ability_ready(ctx, ABIL_MAJOR_HEAL):
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
                priority=_policy.priorities.major_heal,
                expires=Expires(type="immediate"),
            ),
            reason_codes=reasons,
            explanation="玩家生命值危急，强效治疗当前可用。",
        )

    if hp <= PLAYER_HP_LOW and is_ability_ready(ctx, ABIL_QUICK_HEAL):
        return TacticalDecision(
            decision_id=str(uuid4()),
            status="actionable",
            intent_id=intent.intent_id,
            action=_action(
                ctx=ctx,
                type_="cast_ability",
                ability_id=ABIL_QUICK_HEAL,
                target_id=ctx.player.id,
                priority=_policy.priorities.quick_heal,
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
    if not is_ability_ready(ctx, ABIL_SHIELD):
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
            priority=_policy.priorities.shield,
            expires=Expires(type="immediate"),
        ),
        reason_codes=reasons,
        explanation="护盾当前可用，可以为玩家抵挡伤害。",
    )


# ---------------------------------------------------------------------------
# 爆发
# ---------------------------------------------------------------------------
def _burst(intent: TacticalIntent, ctx: CombatContext, mp_low: bool) -> TacticalDecision:
    if not is_ability_ready(ctx, ABIL_EXPLOSION):
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
                priority=_policy.priorities.burst_pending_stun,
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
            priority=_policy.priorities.burst,
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
            ctx=ctx, type_="retreat", target_id=None, priority=_policy.priorities.retreat, expires=Expires(type="immediate")
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
            priority=_policy.priorities.follow,
        ),
        reason_codes=["FOLLOW_REQUESTED"],
        explanation="好的，我跟上你并保持施法距离。",
    )
