"""关系阶段化行为差异（SDD T039 / FR-016）。

对决策做阶段调制：同一意图在 distant/neutral/close 下产出不同的
资源投入意愿与服从度，全部以 reason_codes 标记（可解释，原则 V）：

- ``conservative``（疏远）：维持既有保守拒绝，追加关系原因码；
- ``devoted``（亲密）：低蓝下的资源保留让位于玩家保命（重建护盾动作）；
- ``obedience=low``（亲密）：对危险指令有权以角色口吻质疑（追加抗议码，
  不改变动作本身——UE 保有最终否决权，原则 III）。
"""

from __future__ import annotations

from uuid import uuid4

from app.schemas.combat_context import CombatContext
from app.schemas.tactical_decision import DecisionAction, Expires, TacticalDecision
from app.services.relationship.policy import StagePolicy, get_policy
from app.services.tactical.policy import get_policy as get_tactical_policy

# 有权被亲密阶段质疑的「危险指令」类型（不在表中 = 正常执行）
_PROTESTABLE_INTENTS = {"retreat_and_survive"}


def _stage_policy(stage: str) -> StagePolicy | None:
    for sp in get_policy().stages:
        if sp.name == stage:
            return sp
    return None


def modulate_decision(
    decision: TacticalDecision,
    stage: str,
    ctx: CombatContext | None = None,
) -> TacticalDecision:
    """按关系阶段调制决策；未知阶段原样返回（降级思路，原则 II/V）。"""
    sp = _stage_policy(stage)
    if sp is None:
        return decision

    code = f"RELATIONSHIP_{sp.name.upper()}"

    if sp.resource_willingness == "conservative":
        # 疏远阶段维持保守策略，但标注关系原因（让 UE/玩家可解释）
        if decision.status == "not_actionable" and f"{code}_CONSERVATIVE" not in decision.reason_codes:
            decision.reason_codes.append(f"{code}_CONSERVATIVE")
        return decision

    if (
        sp.resource_willingness == "devoted"
        and decision.status == "not_actionable"
        and "COMPANION_MP_LOW" in decision.reason_codes
        and ctx is not None
        and ctx.companion.ability_states.get("ability.alice.shield") == "ready"
    ):
        # 亲密阶段：玩家保命优先于自己的资源保留（FR-016 资源投入意愿）
        priorities = get_tactical_policy().priorities
        return TacticalDecision(
            decision_id=str(uuid4()),
            status="actionable",
            intent_id=decision.intent_id,
            action=DecisionAction(
                order_id=str(uuid4()),
                agent_id=ctx.companion.id,
                type="cast_ability",
                ability_id="ability.alice.shield",
                target_id=ctx.player.id,
                priority=priorities.shield,
                expires=Expires(type="immediate"),
                authority="player_requested",
            ),
            reason_codes=[f"{code}_DEVOTED", "SHIELD_READY"],
            explanation="……我知道了。这点蓝量，护住你要紧。",
        )

    if (
        sp.obedience == "low"
        and decision.status == "actionable"
        and decision.intent_id in _PROTESTABLE_INTENTS
        and f"{code}_PROTEST" not in decision.reason_codes
    ):
        # 亲密阶段有权质疑危险指令：标记抗议，但执行权在 UE
        decision.reason_codes.append(f"{code}_PROTEST")

    return decision
