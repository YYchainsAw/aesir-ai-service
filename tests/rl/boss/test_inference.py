"""Standalone Boss inference contract tests without loading a real model."""

import numpy as np
from fastapi.testclient import TestClient

from rl.boss.contract import BossAction, OBSERVATION_DIM
from rl.boss.inference import BossPolicyRuntime
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
