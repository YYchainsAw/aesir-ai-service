"""Policies that use the same discrete action contract as Unreal."""

from typing import Protocol

from rl.boss.contract import BossAction
from rl.boss.sim import BossCombatState, BossSimConfig


class BossPolicy(Protocol):
    def select_action(
        self,
        observation: tuple[float, ...],
        state: BossCombatState,
    ) -> BossAction:
        ...


class RuleBossPolicy:
    """Deterministic Behavior Tree-style baseline for offline comparison."""

    def __init__(self, config: BossSimConfig | None = None) -> None:
        self.config = config or BossSimConfig()

    def select_action(
        self,
        observation: tuple[float, ...],
        state: BossCombatState,
    ) -> BossAction:
        del observation

        if state.boss_stunned:
            return BossAction.DEFEND

        if state.target_attacking:
            if self._ready(state, BossAction.DODGE):
                return BossAction.DODGE
            if self._ready(state, BossAction.DEFEND):
                return BossAction.DEFEND

        if (
            state.target_health_ratio <= 0.45
            and state.normalized_distance <= self.config.ability_range
            and self._ready(state, BossAction.USE_ABILITY)
        ):
            return BossAction.USE_ABILITY

        if (
            state.target_blocking
            and state.normalized_distance <= self.config.area_skill_range
            and self._ready(state, BossAction.UNBLOCKABLE_AREA_SKILL)
        ):
            return BossAction.UNBLOCKABLE_AREA_SKILL

        if state.normalized_distance > self.config.light_range:
            if (
                state.normalized_distance <= self.config.gap_closer_range
                and self._ready(state, BossAction.GAP_CLOSER_SKILL)
            ):
                return BossAction.GAP_CLOSER_SKILL
            return BossAction.PURSUE

        if state.target_blocking and self._ready(state, BossAction.HEAVY_ATTACK):
            return BossAction.HEAVY_ATTACK

        if self._ready(state, BossAction.LIGHT_ATTACK):
            return BossAction.LIGHT_ATTACK
        if self._ready(state, BossAction.HEAVY_ATTACK):
            return BossAction.HEAVY_ATTACK
        if self._ready(state, BossAction.DEFEND):
            return BossAction.DEFEND
        if self._ready(state, BossAction.DISENGAGE):
            return BossAction.DISENGAGE
        return BossAction.PURSUE

    @staticmethod
    def _ready(state: BossCombatState, action: BossAction) -> bool:
        return state.cooldown_steps.get(action, 0) <= 0
