"""HTTP runtime wrapper around the shared frozen loader and policy adapter."""
from dataclasses import dataclass
from time import perf_counter
from rl.boss.contract import ACTION_COUNT, BossAction, OBSERVATION_DIM, SCHEMA_VERSION, make_observation
from rl.boss.sim import SIMULATION_REVISION
from rl.boss.model_loader import FrozenModelLoader, ModelValidationError, DEFAULT_MODEL_PATH, UNREAL_ACTION_NAMES
from rl.boss.policy_adapter import predict_action

@dataclass(frozen=True)
class BossPolicyDecision:
    actionable: bool
    action: BossAction | None
    reason: str
    inference_milliseconds: float


class BossPolicyRuntime(FrozenModelLoader):
    def decide(self, values: list[float]) -> BossPolicyDecision:
        observation = make_observation(values)
        if not self.is_ready:
            self.load()
        raw_availability = tuple(value >= 0.5 for value in observation[-len(BossAction):])
        if not any(raw_availability):
            return BossPolicyDecision(
                actionable=False,
                action=None,
                reason="state_locked",
                inference_milliseconds=0.0,
            )

        started = perf_counter()
        with self._lock:
            action = predict_action(self._model, observation)
        elapsed_ms = (perf_counter() - started) * 1000.0
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
        "manifest_path": str(runtime.manifest_path),
        "loaded": runtime.is_loaded,
        "ready": runtime.is_ready,
        "action_count": ACTION_COUNT,
        "model_validation": runtime.validation,
    }
