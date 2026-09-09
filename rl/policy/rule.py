"""规则基线适配器：包装生产 ``resolve_intent()``，作为 A/B 的基准 agent。

sim 状态先经启发式映射为 ``TacticalIntent``（危急→治疗、眩晕→爆发、
临近眩晕→等爆发、低血量→护盾、其余→集火），再调用线上同一份策略代码
决策，最后把 ``TacticalDecision`` 映射回 sim 动作索引。

注意信息不对称：A/B 度量的是「意图映射 + 决策表」的合计行为，这与线上
架构一致（LLM/规则出意图 → resolver 决策）。映射规则固定为本文件一版，
A/B 结论对它敏感（详见 docs/design/rl-feasibility-design.md §6）。
"""

from app.schemas.tactical_intent import TacticalIntent
from app.services.tactical.resolver import (
    ABIL_SHIELD,
    PLAYER_HP_CRITICAL,
    PLAYER_HP_LOW,
    resolve_intent,
)

from rl.sim.constants import (
    ACTION_BASIC_ATTACK,
    ACTION_NOOP,
    ACTION_RETREAT,
    ABILITY_ACTIONS,
    STUN_METER_MAX,
)
from rl.sim.core import SimState

# 眩晕值达到该比例即认为「破绽临近」，改走 prepare_burst_on_stun 等窗口
STUN_NEAR_RATIO = 0.8


def _ability_to_action(ability_id: str) -> int:
    return ABILITY_ACTIONS.get(ability_id, ACTION_NOOP)


_TYPE_TO_ACTION = {"retreat": ACTION_RETREAT, "follow": ACTION_NOOP, "hold_ability": ACTION_NOOP}


class RulePolicyAdapter:
    """A/B 的规则基线：直接复用生产 resolver，无任何 RL 依赖。"""

    def _intent_for(self, state: SimState, ctx) -> str:
        if state.player_hp <= PLAYER_HP_CRITICAL:
            return "support_heal_player"
        if state.boss_stunned:
            return "burst_boss"
        if state.boss_stun >= STUN_METER_MAX * STUN_NEAR_RATIO:
            return "prepare_burst_on_stun"
        if state.player_hp <= PLAYER_HP_LOW and ctx.companion.ability_states.get(ABIL_SHIELD) == "ready":
            return "support_protect_player"
        return "focus_fire_boss"

    def select_action(self, obs, state: SimState) -> int:
        """obs 忽略（规则策略读状态而非观测向量）；PPO 侧同样签名，eval 可互换。

        每次调用只构造一份 CombatContext：意图映射与 resolver 共用。
        """
        ctx = state.to_context()
        intent = TacticalIntent(
            intent_id=self._intent_for(state, ctx),  # type: ignore[arg-type]
            target_id="party.player",
            parse_confidence=1.0,
        )
        decision = resolve_intent(intent, ctx)
        action = decision.action
        if action is None or decision.status != "actionable":
            return ACTION_BASIC_ATTACK  # 无事可做时保持输出（积累眩晕）
        if action.ability_id:
            return _ability_to_action(action.ability_id)
        return _TYPE_TO_ACTION.get(action.type, ACTION_NOOP)
