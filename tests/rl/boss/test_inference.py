"""Standalone Boss inference contract tests without loading a real model."""

from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy", reason="Boss inference requires optional NumPy runtime")
from fastapi.testclient import TestClient

from rl.boss.contract import BossAction, OBSERVATION_DIM
from rl.boss.inference import BossPolicyRuntime, _validate_model_spaces
from rl.boss import release
from rl.boss.contract import FEATURE_NAMES, make_observation
from rl.boss.inference_app import create_app


class FakeMaskableModel:
    def predict(self, observation, deterministic, action_masks):
        assert observation.shape == (OBSERVATION_DIM,)
        assert deterministic is True
        legal_actions = np.flatnonzero(action_masks)
        return int(legal_actions[-1]), None


def make_runtime(tmp_path) -> BossPolicyRuntime:
    runtime = BossPolicyRuntime(tmp_path / "test-policy.zip")
    runtime._model = FakeMaskableModel()
    runtime._provenance = {"model_sha256": "0" * 64, "release_id": "test-release"}
    return runtime


def test_decide_returns_highest_available_action(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
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


def test_state_locked_observation_defers_without_prediction(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
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


def test_invalid_observation_is_rejected(tmp_path) -> None:
    client = TestClient(create_app(make_runtime(tmp_path)))
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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.01, 1.01])
def test_runtime_rejects_nonfinite_or_out_of_range_observation(tmp_path, value):
    observation = [0.0] * OBSERVATION_DIM
    observation[0] = value
    with pytest.raises(ValueError):
        make_runtime(tmp_path).decide(observation)


@pytest.mark.parametrize("value", [0.5, float("nan"), float("inf"), -1, 9, True, [1, 2], [[1]]])
def test_runtime_rejects_invalid_model_output(tmp_path, value):
    runtime = make_runtime(tmp_path)
    runtime._model.predict = lambda *args, **kwargs: (value, None)
    with pytest.raises(RuntimeError):
        runtime.decide([1.0] * OBSERVATION_DIM)


def test_runtime_rejects_masked_model_action(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime._model.predict = lambda *args, **kwargs: (0, None)
    observation = [1.0] * OBSERVATION_DIM
    observation[-len(BossAction)] = 0.0
    with pytest.raises(RuntimeError, match="masked action"):
        runtime.decide(observation)


def test_locked_request_still_requires_verified_release(tmp_path):
    runtime = BossPolicyRuntime(tmp_path / "boss_policy_schema_v4_sim005.zip")
    with pytest.raises(FileNotFoundError):
        runtime.decide([0.0] * OBSERVATION_DIM)
    assert not runtime.is_loaded


def test_response_exposes_content_identity(tmp_path):
    client = TestClient(create_app(make_runtime(tmp_path)))
    response = client.post("/v1/boss/policy/decide", json={
        "request_id": "identity", "sequence": 1, "observation": [1.0] * OBSERVATION_DIM,
    })
    assert response.status_code == 200
    assert response.json()["model_sha256"] == "0" * 64
    assert response.json()["release_id"] == "test-release"
    assert client.get("/health").json()["model_sha256"] == "0" * 64
    assert "model_path" not in client.get("/health").json()


@pytest.mark.parametrize("sequence", [1.5, True, "1"])
def test_api_rejects_noninteger_sequence(tmp_path, sequence):
    response = TestClient(create_app(make_runtime(tmp_path))).post(
        "/v1/boss/policy/decide", json={
            "request_id": "bad-sequence", "sequence": sequence,
            "observation": [1.0] * OBSERVATION_DIM,
        })
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_api_rejects_nonfinite_json_observation(tmp_path, value):
    body = '{"request_id":"nonfinite","sequence":0,"observation":['
    body += value + ',0' * (OBSERVATION_DIM - 1) + ']}'
    response = TestClient(create_app(make_runtime(tmp_path))).post(
        "/v1/boss/policy/decide", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422



@pytest.mark.parametrize("mutate", [
    lambda model: setattr(model.observation_space, "shape", (25,)),
    lambda model: setattr(model.observation_space, "dtype", np.float64),
    lambda model: setattr(model.observation_space, "low", np.full(26, -1)),
    lambda model: setattr(model.observation_space, "high", np.full(26, 2)),
    lambda model: setattr(model.action_space, "n", 8),
    lambda model: setattr(model.action_space, "start", 1),
    lambda model: setattr(model.action_space, "shape", (1,)),
])
def test_model_spaces_must_match_contract(mutate):
    model = SimpleNamespace(
        observation_space=SimpleNamespace(shape=(26,), dtype=np.float32,
                                          low=np.zeros(26), high=np.ones(26)),
        action_space=SimpleNamespace(n=9, start=0, shape=()),
    )
    _validate_model_spaces(model)
    mutate(model)
    with pytest.raises(ValueError, match="spaces mismatch"):
        _validate_model_spaces(model)
