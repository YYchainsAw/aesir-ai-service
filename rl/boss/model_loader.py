"""Frozen MaskablePPO adapter for the standalone Boss inference service."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from threading import Lock


from rl.boss.contract import (
    ACTION_COUNT,
    BossAction,
    FEATURE_NAMES,
    OBSERVATION_DIM,
    SCHEMA_VERSION,
    make_action_mask,
    make_observation,
)
from rl.boss.artifact import (
    EXPECTED_ACTION_COUNT,
    EXPECTED_OBSERVATION_DIM,
    EXPECTED_REWARD_REVISION,
    EXPECTED_SCHEMA_VERSION,
    EXPECTED_SHA256,
    EXPECTED_SIMULATION_REVISION,
    MODEL_NAME,
)
from rl.boss.sim import SIMULATION_REVISION
from rl.boss.rewards import REWARD_REVISION


DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "rl"
    / "boss"
    / "deployment"
    / f"{MODEL_NAME}.zip"
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


class ModelValidationError(RuntimeError):
    """A stable failure code, without leaking model loader exception details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Boss policy validation failed: {code}")


class FrozenModelLoader:
    """Loads one frozen policy and serializes prediction calls."""

    def __init__(self, model_path: Path | None = None, *, manifest_path: Path | None = None) -> None:
        configured_path = os.getenv("AESIR_BOSS_POLICY_MODEL")
        self.model_path = Path(model_path or configured_path or DEFAULT_MODEL_PATH)
        self.manifest_path = manifest_path or self.model_path.with_suffix(".training.manifest.json")
        self._model = None
        self._lock = Lock()
        self._validation = self._new_validation()

    @staticmethod
    def _new_validation() -> dict:
        return {
            "state": "not_checked", "error_code": None,
            "expected": {"model_id": MODEL_NAME, "sha256": EXPECTED_SHA256,
                         "schema_version": EXPECTED_SCHEMA_VERSION,
                         "observation_dimension": EXPECTED_OBSERVATION_DIM,
                         "action_count": EXPECTED_ACTION_COUNT,
                         "simulation_revision": EXPECTED_SIMULATION_REVISION,
                         "reward_revision": EXPECTED_REWARD_REVISION},
            "actual": {"sha256": None, "manifest_sha256": None, "schema_version": None,
                       "observation_shape": None, "action_count": None,
                       "simulation_revision": None, "reward_revision": None},
        }

    @property
    def validation(self) -> dict:
        return deepcopy(self._validation)

    @property
    def is_ready(self) -> bool:
        return self.is_loaded and self._validation["state"] == "passed"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_id(self) -> str:
        return MODEL_NAME

    def load(self) -> None:
        with self._lock:
            if self.is_ready:
                return
            self._model = None
            self._validation = self._new_validation()
            self._validation["state"] = "checking"
            try:
                self._load_validated()
            except ModelValidationError as exc:
                self._validation.update(state="failed", error_code=exc.code)
                raise
            except Exception as exc:
                self._validation.update(state="failed", error_code="MODEL_LOAD_FAILED")
                raise ModelValidationError("MODEL_LOAD_FAILED") from exc

    def _load_validated(self) -> None:
        if (SCHEMA_VERSION, OBSERVATION_DIM, ACTION_COUNT, SIMULATION_REVISION, REWARD_REVISION) != (
            EXPECTED_SCHEMA_VERSION, EXPECTED_OBSERVATION_DIM, EXPECTED_ACTION_COUNT,
            EXPECTED_SIMULATION_REVISION, EXPECTED_REWARD_REVISION,
        ):
            raise ModelValidationError("RUNTIME_CONTRACT_MISMATCH")
        try:
            # Hash and deserialize the same immutable snapshot, never reopen the path.
            model_bytes = self.model_path.read_bytes()
        except FileNotFoundError as exc:
            raise ModelValidationError("MODEL_NOT_FOUND") from exc
        except OSError as exc:
            raise ModelValidationError("MODEL_UNREADABLE") from exc
        actual = self._validation["actual"]
        actual["sha256"] = sha256(model_bytes).hexdigest()
        if actual["sha256"] != EXPECTED_SHA256:
            raise ModelValidationError("MODEL_SHA256_MISMATCH")
        self._validate_manifest()
        try:
            from sb3_contrib import MaskablePPO
            from gymnasium import spaces
            import numpy as np
        except ImportError as exc:
            raise ModelValidationError("INFERENCE_DEPENDENCIES_MISSING") from exc
        with BytesIO(model_bytes) as snapshot:
            model = MaskablePPO.load(snapshot, device="cpu")
        observation_space = getattr(model, "observation_space", None)
        action_space = getattr(model, "action_space", None)
        shape = getattr(observation_space, "shape", None)
        actual["observation_shape"] = list(shape) if shape is not None else None
        count = getattr(action_space, "n", None)
        actual["action_count"] = int(count) if isinstance(count, (int, np.integer)) else None
        if not isinstance(observation_space, spaces.Box) or shape != (OBSERVATION_DIM,):
            raise ModelValidationError("MODEL_OBSERVATION_SPACE_MISMATCH")
        if (observation_space.dtype != np.float32
                or not np.all(observation_space.low == 0.0)
                or not np.all(observation_space.high == 1.0)):
            raise ModelValidationError("MODEL_OBSERVATION_BOUNDS_MISMATCH")
        if (not isinstance(action_space, spaces.Discrete) or count != ACTION_COUNT
                or action_space.start != 0):
            raise ModelValidationError("MODEL_ACTION_SPACE_MISMATCH")
        # Publish only after every check succeeds.
        self._model = model
        self._validation["state"] = "passed"

    def _validate_manifest(self) -> None:
        try:
            with self.manifest_path.open("rb") as stream:
                data = stream.read(1024 * 1024 + 1)
        except FileNotFoundError as exc:
            raise ModelValidationError("MANIFEST_NOT_FOUND") from exc
        except OSError as exc:
            raise ModelValidationError("MANIFEST_UNREADABLE") from exc
        if len(data) > 1024 * 1024:
            raise ModelValidationError("MANIFEST_INVALID")
        self._validation["actual"]["manifest_sha256"] = sha256(data).hexdigest()
        try:
            manifest = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ModelValidationError("MANIFEST_INVALID") from exc
        if not isinstance(manifest, dict):
            raise ModelValidationError("MANIFEST_INVALID")
        actual = self._validation["actual"]
        for key in ("schema_version", "simulation_revision", "reward_revision"):
            value = manifest.get(key)
            # Only scalar values belong in health diagnostics, even for malformed input.
            actual[key] = value if type(value) in (str, int) else None
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
            raise ModelValidationError("MANIFEST_SCHEMA_MISMATCH")
        if manifest.get("feature_names") != list(FEATURE_NAMES):
            raise ModelValidationError("MANIFEST_FEATURES_MISMATCH")
        actions = manifest.get("actions")
        if (not isinstance(actions, dict) or any(type(v) is not int for v in actions.values())
                or actions != {action.name: int(action) for action in BossAction}):
            raise ModelValidationError("MANIFEST_ACTIONS_MISMATCH")
        if (manifest.get("simulation_revision") != SIMULATION_REVISION
                or manifest.get("reward_revision") != REWARD_REVISION):
            raise ModelValidationError("MANIFEST_REVISION_MISMATCH")
