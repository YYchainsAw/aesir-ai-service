"""`POST /v1/agent/step` 主入口契约测试（SDD T019，骨架空动作路径）。

覆盖四类用例（章程原则 IV）：正常心跳、缺字段 422、未登记角色 404、
心跳过频 429；另覆盖骨架期的文本指令路径（如实返回待接入原因码）。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.agent import _reset_heartbeat_tracker

client = TestClient(app)

_REQUEST_ID = "0f9f4b62-6f37-4d0f-9bb5-2be97a4d0f27"


@pytest.fixture(autouse=True)
def _clean_heartbeat_tracker():
    """各测试独立：清空心跳限流状态，避免用例间串扰。"""
    _reset_heartbeat_tracker()
    yield
    _reset_heartbeat_tracker()


def _step_payload(**overrides) -> dict:
    payload = {
        "protocol_version": "0.3",
        "request_id": _REQUEST_ID,
        "companion_id": "companion.alice",
        "world_context": {
            "snapshot_id": "22222222-2222-4222-8222-222222222222",
            "captured_at": "2026-09-13T12:00:00Z",
            "scene": "exploration",
            "player": {"id": "party.player", "hp_percent": 80},
            "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
            "interactables": [
                {"object_id": "object.campfire.001", "kind": "prop", "distance_m": 3.5, "notable": True}
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_heartbeat_returns_none_action_with_observability() -> None:
    response = client.post("/v1/agent/step", json=_step_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == _REQUEST_ID
    assert body["companion_id"] == "companion.alice"
    assert body["action"] == "none"
    assert body["directive"] is None
    assert body["observability"]["source"] == "rule"
    assert body["observability"]["used_snapshot_id"] == "22222222-2222-4222-8222-222222222222"


def test_text_command_skeleton_reports_pending_reason() -> None:
    """骨架期文本指令：空动作 + 如实原因码，不猜测执行（FR-028）。"""
    response = client.post("/v1/agent/step", json=_step_payload(text="艾莉，帮我回一下血"))
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert "TEXT_PIPELINE_PENDING" in body["observability"]["reason_codes"]


def test_missing_required_field_returns_422() -> None:
    payload = _step_payload()
    del payload["world_context"]
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 422


def test_invalid_world_context_returns_422() -> None:
    """非法快照（时间非 ISO-8601）按 422 拒绝。"""
    payload = _step_payload()
    payload["world_context"]["captured_at"] = "not-a-timestamp"
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 422


def test_unregistered_companion_returns_404_without_fallback() -> None:
    """FR-044：未登记角色明确拒绝，不回退默认角色人格。"""
    response = client.post("/v1/agent/step", json=_step_payload(companion_id="companion.unknown"))
    assert response.status_code == 404


def test_heartbeat_too_frequent_returns_429() -> None:
    first = client.post("/v1/agent/step", json=_step_payload())
    assert first.status_code == 200
    second = client.post("/v1/agent/step", json=_step_payload())
    assert second.status_code == 429


def test_text_commands_are_not_throttled() -> None:
    """文本指令不受心跳限流约束（限流仅针对无产出的心跳，FR-022）。"""
    assert client.post("/v1/agent/step", json=_step_payload(text="艾莉，跟上")).status_code == 200
    assert client.post("/v1/agent/step", json=_step_payload(text="艾莉，等等我")).status_code == 200
