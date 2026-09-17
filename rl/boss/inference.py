"""Frozen MaskablePPO adapter for the standalone Boss inference service."""

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Lock
from time import perf_counter

import numpy as np

from rl.boss.contract import (
    BossAction,
    OBSERVATION_DIM,
    SCHEMA_VERSION,
    make_action_mask,
    make_observation,
)
from rl.boss.sim import SIMULATION_REVISION


DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "rl"
    / "boss"
    / "deployment"
    / "boss_policy_schema_v4_sim005.zip"
)

UNREAL_ACTION_NAMES = {
    BossAction.LIGHT_ATTACK: "LightAttack",
    BossAction.HEAVY_ATTACK: "HeavyAttack",
    BossAction.DEFEND: "Defend",
    BossAction.DODGE: "Dodge",
    BossAction.PURSUE: "Pursue",
    BossAction.DISENGAGE: "Disengage",
    BossAction.USE_ABILITY: "UseAbility",
    BossAction.GAP_CLOSER_SKILL: "GapCloserSkill",
    BossAction.UNBLOCKABLE_AREA_SKILL: "UnblockableAreaSkill",
}


@dataclass(frozen=True)
class BossPolicyDecision:
    actionable: bool
    action: BossAction | None
    reason: str
    inference_milliseconds: float


class BossPolicyRuntime:
    """Loads one frozen policy and serializes prediction calls."""

    def __init__(self, model_path: Path | None = None) -> None:
        configured_path = os.getenv("AESIR_BOSS_POLICY_MODEL")
        self.model_path = Path(configured_path) if configured_path else (
            model_path or DEFAULT_MODEL_PATH
        )
        self._model = None
        self._lock = Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_id(self) -> str:
        return self.model_path.stem

    def load(self) -> None:
        if self.is_loaded:
            return
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Boss policy model not found: {self.model_path}")

        from sb3_contrib import MaskablePPO

        self._model = MaskablePPO.load(str(self.model_path), device="cpu")

    def decide(self, values: list[float]) -> BossPolicyDecision:
        observation = make_observation(values)
        raw_availability = tuple(value >= 0.5 for value in observation[-len(BossAction):])
        if not any(raw_availability):
            return BossPolicyDecision(
                actionable=False,
                action=None,
                reason="state_locked",
                inference_milliseconds=0.0,
            )

        if not self.is_loaded:
            self.load()

        action_mask = np.asarray(make_action_mask(observation), dtype=np.bool_)
        started = perf_counter()
        with self._lock:
            action_value, _ = self._model.predict(
                np.asarray(observation, dtype=np.float32),
                deterministic=True,
                action_masks=action_mask,
            )
        elapsed_ms = (perf_counter() - started) * 1000.0
        action = BossAction(int(action_value))
        return BossPolicyDecision(
            actionable=True,
            action=action,
            reason="policy_selected",
            inference_milliseconds=elapsed_ms,
        )


def runtime_metadata(runtime: BossPolicyRuntime) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_dimension": OBSERVATION_DIM,
        "simulation_revision": SIMULATION_REVISION,
        "model_id": runtime.model_id,
        "model_path": str(runtime.model_path),
        "loaded": runtime.is_loaded,
    }
