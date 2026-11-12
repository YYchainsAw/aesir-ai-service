"""Standalone Boss inference contract tests without loading a real model."""

import numpy as np
import json
from hashlib import sha256
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gymnasium import spaces
from fastapi.testclient import TestClient

from rl.boss.contract import BossAction, FEATURE_NAMES, OBSERVATION_DIM
from rl.boss import model_loader as inference
from rl.boss.inference import BossPolicyRuntime, ModelValidationError
from rl.boss.inference_app import create_app


class FakeMaskableModel:
    observation_space = spaces.Box(0.0, 1.0, shape=(OBSERVATION_DIM,), dtype=np.float32)
    action_space = spaces.Discrete(len(BossAction))

    def predict(self, observation, deterministic, action_masks):
        assert observation.shape == (OBSERVATION_DIM,)
        assert deterministic is True
        legal_actions = np.flatnonzero(action_masks)
        return int(legal_actions[-1]), None


def prepare_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("AESIR_BOSS_POLICY_MODEL", raising=False)
    runtime = BossPolicyRuntime(tmp_path / "test-policy.zip")
    runtime.model_path.write_bytes(b"synthetic fixture; not a real PPO model")
    monkeypatch.setattr(inference, "EXPECTED_SHA256", sha256(runtime.model_path.read_bytes()).hexdigest())
    runtime.manifest_path.write_text(json.dumps({
        "schema_version": 4, "feature_names": list(FEATURE_NAMES),
        "actions": {action.name: int(action) for action in BossAction},
        "simulation_revision": "boss-sim-005", "reward_revision": "boss-reward-003",
    }), encoding="utf-8")
    loader = Mock(return_value=FakeMaskableModel())
    monkeypatch.setitem(sys.modules, "sb3_contrib", SimpleNamespace(
        MaskablePPO=SimpleNamespace(load=loader)))
    return runtime, loader


def make_runtime(tmp_path, monkeypatch) -> BossPolicyRuntime:
    runtime, _ = prepare_runtime(tmp_path, monkeypatch)
    runtime.load()
    return runtime


def test_decide_returns_highest_available_action(tmp_path, monkeypatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch)
    client = TestClient(create_app(runtime))
    observation = [0.0] * OBSERVATION_DIM
    observation[0] = 1.0
    observation[1] = 1.0
    observation[-len(BossAction):] = [1.0] * len(BossAction)

    response = client.post(
        "/v1/boss/policy/decide",
        json={
            "request_id": "request-1",
            "schema_version": 4,
            "sequence": 12,
            "observation": observation,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "request-1"
    assert payload["sequence"] == 12
    assert payload["action_id"] == BossAction.UNBLOCKABLE_AREA_SKILL
    assert payload["action_name"] == "UnblockableAreaSkill"
    assert payload["actionable"] is True


def test_state_locked_observation_defers_without_prediction(tmp_path, monkeypatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch)
    client = TestClient(create_app(runtime))
    observation = [0.0] * OBSERVATION_DIM
    observation[0] = 1.0
    observation[1] = 1.0

    response = client.post(
        "/v1/boss/policy/decide",
        json={
            "request_id": "request-locked",
            "schema_version": 4,
            "sequence": 13,
            "observation": observation,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["actionable"] is False
    assert payload["action_id"] is None
    assert payload["reason"] == "state_locked"


def test_invalid_observation_is_rejected(tmp_path, monkeypatch) -> None:
    client = TestClient(create_app(make_runtime(tmp_path, monkeypatch)))
    response = client.post(
        "/v1/boss/policy/decide",
        json={
            "request_id": "request-invalid",
            "schema_version": 4,
            "sequence": 0,
            "observation": [0.0] * (OBSERVATION_DIM - 1),
        },
    )
    assert response.status_code == 422


def test_lifespan_loads_verified_snapshot_and_health_reports_actual_values(tmp_path, monkeypatch):
    runtime, loader = prepare_runtime(tmp_path, monkeypatch)
    snapshot_bytes = runtime.model_path.read_bytes()

    def load(snapshot, device):
        assert device == "cpu"
        assert snapshot.read() == snapshot_bytes
        # Replacing the path after hashing cannot change bytes passed to SB3.
        runtime.model_path.write_bytes(b"changed on disk")
        return FakeMaskableModel()

    loader.side_effect = load
    with TestClient(create_app(runtime)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        health = response.json()
        assert health["status"] == "ok"
        assert health["loaded"] is health["ready"] is True
        assert health["model_id"] == "boss_policy_schema_v4_sim005"
        validation = health["model_validation"]
        assert validation["state"] == "passed"
        assert validation["error_code"] is None
        assert validation["actual"] == {
            "sha256": sha256(snapshot_bytes).hexdigest(),
            "manifest_sha256": sha256(runtime.manifest_path.read_bytes()).hexdigest(),
            "schema_version": 4, "observation_shape": [26], "action_count": 9,
            "simulation_revision": "boss-sim-005", "reward_revision": "boss-reward-003",
        }
        runtime.load()
        loader.assert_called_once()


@pytest.mark.parametrize("failure,code", [
    ("missing_model", "MODEL_NOT_FOUND"),
    ("wrong_sha", "MODEL_SHA256_MISMATCH"),
    ("missing_manifest", "MANIFEST_NOT_FOUND"),
    ("bad_json", "MANIFEST_INVALID"),
    ("non_object", "MANIFEST_INVALID"),
    ("large_manifest", "MANIFEST_INVALID"),
    ("missing_schema", "MANIFEST_SCHEMA_MISMATCH"),
    ("schema", "MANIFEST_SCHEMA_MISMATCH"),
    ("float_schema", "MANIFEST_SCHEMA_MISMATCH"),
    ("features", "MANIFEST_FEATURES_MISMATCH"),
    ("actions", "MANIFEST_ACTIONS_MISMATCH"),
    ("bool_action", "MANIFEST_ACTIONS_MISMATCH"),
    ("simulation", "MANIFEST_REVISION_MISMATCH"),
    ("reward", "MANIFEST_REVISION_MISMATCH"),
])
def test_preflight_failure_prevents_deserialization_and_startup(tmp_path, monkeypatch, failure, code):
    runtime, loader = prepare_runtime(tmp_path, monkeypatch)
    manifest = json.loads(runtime.manifest_path.read_text())
    if failure == "missing_model":
        runtime.model_path.unlink()
    elif failure == "wrong_sha":
        runtime.model_path.write_bytes(b"wrong model")
    elif failure == "missing_manifest":
        runtime.manifest_path.unlink()
    elif failure == "bad_json":
        runtime.manifest_path.write_text("{")
    elif failure == "non_object":
        runtime.manifest_path.write_text("[]")
    elif failure == "large_manifest":
        runtime.manifest_path.write_bytes(b" " * (1024 * 1024 + 1))
    else:
        if failure == "missing_schema":
            del manifest["schema_version"]
        elif failure == "schema":
            manifest["schema_version"] = 3
        elif failure == "float_schema":
            manifest["schema_version"] = 4.0
        elif failure == "features":
            manifest["feature_names"].reverse()
        elif failure == "actions":
            manifest["actions"]["LIGHT_ATTACK"] = 1
        elif failure == "bool_action":
            manifest["actions"]["LIGHT_ATTACK"] = False
        elif failure == "simulation":
            manifest["simulation_revision"] = "boss-sim-old"
        elif failure == "reward":
            manifest["reward_revision"] = "boss-reward-old"
        runtime.manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ModelValidationError, match=code):
        with TestClient(create_app(runtime)):
            pytest.fail("lifespan accepted invalid materials")
    loader.assert_not_called()
    assert runtime.is_loaded is runtime.is_ready is False
    assert runtime.validation["state"] == "failed"
    assert runtime.validation["error_code"] == code


@pytest.mark.parametrize("observation_space,action_space,code", [
    (spaces.Box(0.0, 1.0, shape=(17,), dtype=np.float32), spaces.Discrete(9),
     "MODEL_OBSERVATION_SPACE_MISMATCH"),
    (spaces.Box(0.0, 1.0, shape=(26, 1), dtype=np.float32), spaces.Discrete(9),
     "MODEL_OBSERVATION_SPACE_MISMATCH"),
    (spaces.Box(-1.0, 1.0, shape=(26,), dtype=np.float32), spaces.Discrete(9),
     "MODEL_OBSERVATION_BOUNDS_MISMATCH"),
    (spaces.Box(0.0, 1.0, shape=(26,), dtype=np.float64), spaces.Discrete(9),
     "MODEL_OBSERVATION_BOUNDS_MISMATCH"),
    (FakeMaskableModel.observation_space, spaces.Discrete(7), "MODEL_ACTION_SPACE_MISMATCH"),
    (FakeMaskableModel.observation_space, spaces.Discrete(9, start=1), "MODEL_ACTION_SPACE_MISMATCH"),
    (FakeMaskableModel.observation_space, spaces.MultiBinary(9), "MODEL_ACTION_SPACE_MISMATCH"),
])
def test_loaded_spaces_checked_before_publishing_model(tmp_path, monkeypatch,
                                                       observation_space, action_space, code):
    runtime, loader = prepare_runtime(tmp_path, monkeypatch)
    loader.return_value = SimpleNamespace(observation_space=observation_space, action_space=action_space)
    with pytest.raises(ModelValidationError, match=code):
        with TestClient(create_app(runtime)):
            pytest.fail("lifespan accepted incompatible spaces")
    assert runtime.is_loaded is runtime.is_ready is False
    assert runtime.validation["error_code"] == code


def test_not_checked_health_does_not_claim_validation_or_readiness(tmp_path):
    runtime = BossPolicyRuntime(tmp_path / "absent.zip")
    # Intentionally bypass lifespan to inspect the unstarted object's diagnostics.
    response = TestClient(create_app(runtime)).get("/health")
    assert response.status_code == 503
    assert response.json()["model_validation"]["state"] == "not_checked"
    assert response.json()["model_validation"]["actual"]["schema_version"] is None
    assert response.json()["ready"] is False


def test_locked_state_cannot_bypass_model_validation(tmp_path):
    runtime = BossPolicyRuntime(tmp_path / "absent.zip")
    client = TestClient(create_app(runtime))
    response = client.post("/v1/boss/policy/decide", json={
        "request_id": "locked-unvalidated", "sequence": 0, "observation": [0.0] * 26,
    })
    assert response.status_code == 503
    health = client.get("/health")
    assert health.status_code == 503
    assert health.json()["model_validation"]["error_code"] == "MODEL_NOT_FOUND"


def test_loader_failure_remains_unloaded_and_retry_revalidates(tmp_path, monkeypatch):
    runtime, loader = prepare_runtime(tmp_path, monkeypatch)
    loader.side_effect = ValueError("invalid checkpoint internals")
    with pytest.raises(ModelValidationError, match="MODEL_LOAD_FAILED"):
        runtime.load()
    assert runtime.is_loaded is runtime.is_ready is False
    loader.side_effect = None
    runtime.load()
    assert runtime.is_ready
    assert runtime.validation["error_code"] is None


def test_missing_dependencies_have_distinct_failure_status(tmp_path, monkeypatch):
    runtime, _ = prepare_runtime(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "sb3_contrib", None)
    with pytest.raises(ModelValidationError, match="INFERENCE_DEPENDENCIES_MISSING"):
        runtime.load()
    assert runtime.validation["state"] == "failed"
    assert not runtime.is_loaded


def test_explicit_model_path_precedes_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AESIR_BOSS_POLICY_MODEL", str(tmp_path / "environment.zip"))
    assert BossPolicyRuntime().model_path.name == "environment.zip"
    assert BossPolicyRuntime(tmp_path / "explicit.zip").model_path.name == "explicit.zip"


def test_runtime_contract_drift_is_rejected(tmp_path, monkeypatch):
    runtime, loader = prepare_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(inference, "SCHEMA_VERSION", 5)
    with pytest.raises(ModelValidationError, match="RUNTIME_CONTRACT_MISMATCH"):
        runtime.load()
    loader.assert_not_called()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_observation_is_rejected_at_http_boundary(tmp_path, monkeypatch, value):
    client = TestClient(create_app(make_runtime(tmp_path, monkeypatch)))
    response = client.post("/v1/boss/policy/decide", json={
        "request_id": "nonfinite", "sequence": 0, "observation": [value] + [0.0] * 25,
    })
    assert response.status_code == 422


def test_offline_evaluation_uses_same_verified_snapshot_and_manifest(tmp_path, monkeypatch):
    from scripts.rl.boss.eval_frozen import load_frozen_policy
    runtime, loader = prepare_runtime(tmp_path, monkeypatch)
    original = runtime.model_path.read_bytes()
    def load(snapshot, device):
        assert snapshot.read() == original
        runtime.model_path.write_bytes(b"replacement after verification")
        return FakeMaskableModel()
    loader.side_effect = load
    policy = load_frozen_policy(runtime.model_path)
    assert policy.validation["state"] == "passed"
    assert policy.validation["actual"]["sha256"] == sha256(original).hexdigest()
    assert policy.validation["actual"]["sha256"] != sha256(runtime.model_path.read_bytes()).hexdigest()


@pytest.mark.parametrize("invalid", [1.5, float("nan"), [1, 2]])
def test_policy_adapter_rejects_noninteger_or_multiple_actions(invalid):
    from rl.boss.policy_adapter import predict_action
    model = SimpleNamespace(predict=lambda *args, **kwargs: (invalid, None))
    with pytest.raises(ValueError):
        predict_action(model, [1.0] * 26)
