"""观测特征提取：CombatContext → 固定长度向量（L2，依赖 numpy）。

sim 内核直接产出 ``CombatContext``，训练与服务端特征提取走同一条代码
路径；UE 真数据接入后只需换数据源，不需要改特征定义。

17 维（全部归一化到 [0,1]）：
  0  player_hp / 100
  1  player_distance_to_boss / 30（30m 视为满刻度）
  2  boss_hp / 100
  3  boss_stun / 100
  4  boss_enraged（0/1）
  5  boss_stunned_remaining / 10（10s 满刻度）
  6  companion_hp / 100
  7  companion_mp / 100
  8-12 ability ready（basic_attack/explosion/quick_heal/major_heal/shield）
  13 shield_active（0/1，由 env 传入，快照本身不含）
  14 retreat_active（0/1，同上）
  15 tick / max_ticks
  16 companion_downed（0/1）
"""

from typing import TYPE_CHECKING

import numpy as np

from app.schemas.combat_context import CombatContext
from app.services.tactical.resolver import (
    ABIL_EXPLOSION,
    ABIL_MAJOR_HEAL,
    ABIL_QUICK_HEAL,
    ABIL_SHIELD,
)

if TYPE_CHECKING:
    from rl.sim.core import SimState

OBS_DIM = 17
_PLAYER_DISTANCE_SCALE = 30.0
_STUNNED_REMAINING_SCALE = 10.0
# 固定顺序（勿改为依赖字典插入顺序）：basic_attack/explosion/quick_heal/major_heal/shield
_ABILITY_ORDER = [
    "ability.alice.basic_attack",
    ABIL_EXPLOSION,
    ABIL_QUICK_HEAL,
    ABIL_MAJOR_HEAL,
    ABIL_SHIELD,
]


def extract_observation(
    ctx: CombatContext,
    *,
    shield_active: bool = False,
    retreat_active: bool = False,
    tick: int = 0,
    max_ticks: int = 300,
) -> np.ndarray:
    obs = np.zeros(OBS_DIM, dtype=np.float32)
    obs[0] = ctx.player.hp_percent / 100.0
    obs[1] = min(1.0, ctx.player.distance_to_boss_m / _PLAYER_DISTANCE_SCALE)
    obs[2] = ctx.boss.hp_percent / 100.0
    obs[3] = ctx.boss.stun_percent / 100.0
    obs[4] = 1.0 if ctx.boss.is_enraged else 0.0
    obs[5] = min(1.0, (ctx.boss.stunned_remaining_seconds or 0.0) / _STUNNED_REMAINING_SCALE)
    obs[6] = ctx.companion.hp_percent / 100.0
    obs[7] = ctx.companion.mp_percent / 100.0
    for i, ability_id in enumerate(_ABILITY_ORDER):
        obs[8 + i] = 1.0 if ctx.companion.ability_states.get(ability_id) == "ready" else 0.0
    obs[13] = 1.0 if shield_active else 0.0
    obs[14] = 1.0 if retreat_active else 0.0
    obs[15] = min(1.0, tick / max(1, max_ticks))
    obs[16] = 1.0 if ctx.companion.hp_percent <= 0 else 0.0
    return obs


def extract_observation_from_state(state: "SimState") -> np.ndarray:
    """sim 状态便捷封装：to_context() 与服务端走同一特征路径。"""
    from rl.sim.constants import MAX_TICKS

    return extract_observation(
        state.to_context(),
        shield_active=state.shield_active_ticks > 0,
        retreat_active=state.retreat_active_ticks > 0,
        tick=state.tick,
        max_ticks=MAX_TICKS,
    )
