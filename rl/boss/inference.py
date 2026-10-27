"""Frozen CPU MaskablePPO adapter for the local Boss inference service."""

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Lock
from time import perf_counter

import numpy as np

from rl.boss.contract import (
    BossAction, OBSERVATION_DIM, SCHEMA_VERSION, make_action_mask, make_observation,
)
from rl.boss.release import default_model_path, validate_frozen_artifact
from rl.boss.rewards import REWARD_REVISION
from rl.boss.sim import SIMULATION_REVISION

DEFAULT_MODEL_PATH = default_model_path()

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


def _validate_model_spaces(model) -> None:
    observation = model.observation_space
    action = model.action_space
    if (getattr(observation, "shape", None) != (OBSERVATION_DIM,)
            or np.dtype(observation.dtype) != np.dtype(np.float32)
            or not np.array_equal(observation.low, np.zeros(OBSERVATION_DIM))
            or not np.array_equal(observation.high, np.ones(OBSERVATION_DIM))
            or getattr(action, "n", None) != len(BossAction)
            or getattr(action, "start", None) != 0
            or getattr(action, "shape", None) != ()):
        raise ValueError("frozen model observation/action spaces mismatch")


class BossPolicyRuntime:
    """Verify one pinned release and serialize loading and CPU prediction."""

    def __init__(self, model_path: Path | None = None) -> None:
        configured_path = os.getenv("AESIR_BOSS_POLICY_MODEL")
        self.model_path = Path(model_path) if model_path is not None else (
            Path(configured_path) if configured_path else DEFAULT_MODEL_PATH
        )
        self._model = None
        self._provenance: dict[str, object] = {}
        self._lock = Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_id(self) -> str:
        return str(self._provenance.get("model_id", self.model_path.stem))

    @property
    def provenance(self) -> dict[str, object]:
        return dict(self._provenance)

    def load(self) -> None:
        with self._lock:
            if self.is_loaded:
                return
            provenance = validate_frozen_artifact(self.model_path)
            # Apply small CPU pools before importing model code; no GPU use or training.
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            os.environ.setdefault("MKL_NUM_THREADS", "1")
            import torch
            from sb3_contrib import MaskablePPO

            torch.set_num_threads(1)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                if torch.get_num_interop_threads() != 1:
                    raise RuntimeError("Boss CPU interop thread limit could not be applied")
            model = MaskablePPO.load(str(self.model_path), device="cpu")
            _validate_model_spaces(model)
            model.policy.set_training_mode(False)
            model.policy.requires_grad_(False)
            self._provenance = provenance
            self._model = model

    def decide(self, values: list[float]) -> BossPolicyDecision:
        observation = make_observation(values)
        if not self.is_loaded:
            self.load()
        raw_availability = tuple(value >= 0.5 for value in observation[-len(BossAction):])
        if not any(raw_availability):
            return BossPolicyDecision(False, None, "state_locked", 0.0)

        action_mask = np.asarray(make_action_mask(observation), dtype=np.bool_)
        started = perf_counter()
        with self._lock:
            action_value, _ = self._model.predict(
                np.asarray(observation, dtype=np.float32),
                deterministic=True,
                action_masks=action_mask,
            )
        elapsed_ms = (perf_counter() - started) * 1000.0
        prediction = np.asarray(action_value)
        if prediction.size != 1 or prediction.ndim > 1 or prediction.dtype.kind not in "iuf":
            raise RuntimeError("frozen policy returned a non-scalar numeric action")
        value = float(prediction.item())
        if not np.isfinite(value) or value != int(value) or not 0 <= value < len(BossAction):
            raise RuntimeError("frozen policy returned an invalid action")
        action = BossAction(int(value))
        if not action_mask[action]:
            raise RuntimeError("frozen policy returned a masked action")
        return BossPolicyDecision(True, action, "policy_selected", elapsed_ms)


def runtime_metadata(runtime: BossPolicyRuntime) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_dimension": OBSERVATION_DIM,
        "simulation_revision": SIMULATION_REVISION,
        "reward_revision": REWARD_REVISION,
        "model_id": runtime.model_id,
        "loaded": runtime.is_loaded,
        **runtime.provenance,
    }
