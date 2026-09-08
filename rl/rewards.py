"""奖励函数（纯函数，sim 与 eval 共用）。

信号设计动机（详见 docs/design/rl-feasibility-design.md §4）：
- 输出导向：Boss 伤害给正奖励；眩晕窗口内「同伴主动技能」的伤害放大计权
  → 奖励「等窗口再爆发」（玩家自动输出不受策略控制，只在基础权重计一次）；
- 生存导向：玩家每 tick 存活给小奖励，终局胜负给强信号；
- 资源纪律：浪费治疗（玩家血量健康时）、无效施法（蓝不足/CD 中）给负奖励；
- 防拖延：每 tick 步惩罚对冲 noop 刷生存奖励。
"""

from rl.sim.core import SimState, SimStepResult

# --- 权重常量（扫描时只动这里） ---
REWARD_BOSS_DAMAGE_PER_10 = 0.5   # 每 10 点 Boss 伤害
STUN_WINDOW_DAMAGE_MULT = 2.5     # 眩晕窗口内的伤害计权（与 sim 的承受倍率一致）
REWARD_SURVIVE_TICK = 0.05        # 玩家每 tick 存活
REWARD_WASTED_HEAL = -1.0         # 玩家血量健康时施放治疗
REWARD_INVALID_CAST = -0.5        # 蓝不足 / CD 中施法失败
REWARD_WIN = 10.0                 # Boss 击杀
REWARD_PLAYER_DOWN = -10.0
REWARD_COMPANION_DOWN = -5.0
REWARD_STEP = -0.01               # 每 tick 步惩罚，防 noop 拖延


def compute_reward(events: SimStepResult, state: SimState, done_reason: str | None) -> float:
    """单 tick 奖励。``state`` 为本 tick 结束后的状态。"""
    # 基础伤害对所有来源计一次（含玩家自动输出，作为背景信号）；
    # 眩晕窗口内只有同伴主动技能的伤害享受额外计权，避免奖励不可控输出。
    reward = REWARD_BOSS_DAMAGE_PER_10 * (events.damage_to_boss / 10.0)
    if events.boss_stunned_at_action:
        bonus = (STUN_WINDOW_DAMAGE_MULT - 1.0) * REWARD_BOSS_DAMAGE_PER_10
        reward += bonus * (events.companion_damage_to_boss / 10.0)
    if state.player_hp > 0:
        reward += REWARD_SURVIVE_TICK
    if events.wasted_heal:
        reward += REWARD_WASTED_HEAL
    if events.invalid_cast:
        reward += REWARD_INVALID_CAST
    reward += REWARD_STEP
    if done_reason == "boss_dead":
        reward += REWARD_WIN
    elif done_reason == "player_downed":
        reward += REWARD_PLAYER_DOWN
    elif done_reason == "companion_downed":
        reward += REWARD_COMPANION_DOWN
    return reward
