"""Gymnasium environment for the UE-aligned high-level Boss policy."""

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from rl.boss.contract import (
    ACTION_COUNT,
    FEATURE_NAMES,
    OBSERVATION_HIGH,
    OBSERVATION_LOW,
    SCHEMA_VERSION,
)
from rl.boss.rewards import REWARD_REVISION, compute_reward
from rl.boss.sim import BossPolicySim, BossSimConfig, PLAYER_PROFILES


class AesirBossEnv(gym.Env):
    """Boss-as-agent environment with optional mixed player profiles."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        seed: int = 0,
        profile: str = "mixed",
        max_steps: int = 400,
    ) -> None:
        super().__init__()
        if profile != "mixed" and profile not in PLAYER_PROFILES:
            raise ValueError(f"unknown player profile: {profile}")
        self._configured_profile = profile
        self._active_profile = "aggressive" if profile == "mixed" else profile
        self._sim = BossPolicySim(
            seed=seed,
            profile=self._active_profile,
            config=BossSimConfig(max_steps=max_steps),
        )
        self.action_space = spaces.Discrete(ACTION_COUNT)
        self.observation_space = spaces.Box(
            low=OBSERVATION_LOW,
            high=OBSERVATION_HIGH,
            dtype=np.float32,
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ):
        super().reset(seed=seed)
        requested_profile = (options or {}).get("profile", self._configured_profile)
        if requested_profile == "mixed":
            names = tuple(PLAYER_PROFILES)
            requested_profile = names[int(self.np_random.integers(len(names)))]
        if requested_profile not in PLAYER_PROFILES:
            raise ValueError(f"unknown player profile: {requested_profile}")
        self._active_profile = requested_profile
        self._sim.reset(seed=seed, profile=requested_profile)
        return self._observation(), self._base_info()

    def step(self, action: int):
        state, events, terminal_reason = self._sim.step(int(action))
        reward, terms = compute_reward(events, terminal_reason)
        events.reward_terms = terms
        terminated = terminal_reason in ("boss_victory", "boss_defeat")
        truncated = terminal_reason == "timeout"
        info = self._base_info()
        info.update(
            {
                "terminal_reason": terminal_reason,
                "action": events.action.name,
                "accepted": events.accepted,
                "action_result": events.result,
                "damage_dealt": events.damage_dealt,
                "damage_received": events.damage_received,
                "repeat_count": events.repeat_count,
                "reward_terms": terms,
            }
        )
        return self._observation(), reward, terminated, truncated, info

    def render(self):  # pragma: no cover
        return None

    @property
    def unwrapped_sim(self) -> BossPolicySim:
        return self._sim

    def _base_info(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "feature_names": FEATURE_NAMES,
            "reward_revision": REWARD_REVISION,
            "player_profile": self._active_profile,
        }

    def _observation(self) -> np.ndarray:
        return np.asarray(self._sim.state.observation(), dtype=np.float32)
