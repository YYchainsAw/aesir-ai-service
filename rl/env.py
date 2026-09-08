"""Gymnasium 环境封装（L2，依赖 gymnasium + numpy）。

薄包装：``BossSim.step`` 出状态与明细，``compute_reward`` 出奖励，
``extract_observation_from_state`` 出观测——本文件只做组合，不承载逻辑。
"""

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from rl.features import OBS_DIM, extract_observation
from rl.rewards import compute_reward
from rl.sim.constants import N_ACTIONS, SimConstants
from rl.sim.core import BossSim


class AliceBossEnv(gym.Env):
    """单 Boss 单遭遇；动作 Discrete(7)，观测 Box[0,1]^17。

    ``reset(seed=...)`` 遵循 gymnasium 1.x 规范（``super().reset(seed=seed)``），
    同 seed 可复现整局。``max_ticks`` 会注入到模拟器常量，决定超时截断。
    """

    metadata = {"render_modes": []}

    def __init__(self, seed: int = 0, max_ticks: int = 300):
        super().__init__()
        self._max_ticks = max_ticks
        self._sim = BossSim(seed=seed, constants=SimConstants(max_ticks=max_ticks))
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(OBS_DIM,), dtype=np.float32)

    def _obs(self) -> np.ndarray:
        return extract_observation(
            self._sim.to_context(),
            shield_active=self._sim.state.shield_active_ticks > 0,
            retreat_active=self._sim.state.retreat_active_ticks > 0,
            tick=self._sim.state.tick,
            max_ticks=self._max_ticks,
        )

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        super().reset(seed=seed)
        self._sim.reset(seed=seed)
        return self._obs(), {}

    def step(self, action: int):
        state, events, done_reason = self._sim.step(int(action))
        reward = compute_reward(events, state, done_reason)
        terminated = done_reason in ("boss_dead", "player_downed", "companion_downed")
        truncated = done_reason == "timeout"
        return self._obs(), float(reward), terminated, truncated, {
            "done_reason": done_reason,
            "events": events,
        }

    def render(self):  # pragma: no cover - 无渲染需求，占位以满足 API
        return None

    @property
    def unwrapped_sim(self) -> BossSim:
        """暴露内核供 eval 统计 tick 明细（眩晕窗口施法率等）。"""
        return self._sim
