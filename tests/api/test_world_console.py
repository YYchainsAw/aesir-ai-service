"""`/v1/world/events` 与 `/v1/console/*` 的骨架测试（SDD T014 / T015）。

覆盖：未知事件类型 422、未登记角色 404、幂等回放（重复上报回放首次结果）、
console 状态查询与记忆重置。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.world import _reset_seen_world_events

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_world_cache():
    _reset_seen_world_events()
    yield
    _reset_seen_world_events()


def _event_payload(**overrides) -> dict:
    payload = {
        "protocol_version": "0.3",
        "request_id": "req.world.001",
        "companion_id": "companion.alice",
        "event": {
            "event_id": "event.world.test.001",
            "event_type": "region_first_entered",
            "occurred_at": "2026-09-13T12:00:00Z",
            "sequence": 1,
            "details": {"region_id": "region.forest.north"},
        },
        "world_context": {
            "snapshot_id": "33333333-3333-4333-8333-333333333333",
            "captured_at": "2026-09-13T12:00:00Z",
            "scene": "exploration",
            "region": {"region_id": "region.forest.north", "first_visit": True},
            "player": {"id": "party.player", "hp_percent": 90},
            "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
        },
    }
    payload.update(overrides)
    return payload


def test_world_event_returns_skeleton_reaction() -> None:
    response = client.post("/v1/world/events", json=_event_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == "event.world.test.001"
    assert body["duplicate"] is False
    assert body["reaction"]["reply_text"]  # 回退到角色默认对话表现，非空
    assert body["observability"]["reason_codes"] == ["EVENT_REACTION_DEFAULT"]


def test_world_event_unknown_type_returns_422() -> None:
    response = client.post("/v1/world/events", json=_event_payload(
        **{"event": {"event_id": "x", "event_type": "not_in_whitelist", "occurred_at": "2026-09-13T12:00:00Z", "sequence": 1}}
    ))
    assert response.status_code == 422


def test_world_event_unregistered_companion_returns_404() -> None:
    response = client.post("/v1/world/events", json=_event_payload(companion_id="companion.unknown"))
    assert response.status_code == 404


def test_world_event_duplicate_replays_first_result() -> None:
    """FR-033：同一事件重复上报回放首次结果且不产生新行为。"""
    first = client.post("/v1/world/events", json=_event_payload())
    assert first.status_code == 200
    retry = client.post("/v1/world/events", json=_event_payload(
        request_id="req.world.002"  # 新 request_id，模拟网络重试
    ))
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert retry.json()["request_id"] == "req.world.002"
    assert retry.json()["reaction"] == first.json()["reaction"]


def test_console_state_returns_registered_summary() -> None:
    response = client.get("/v1/console/state", params={"companion_id": "companion.alice"})
    assert response.status_code == 200
    body = response.json()
    assert "companion.alice" in body["registered_companions"]
    assert body["companion_id"] == "companion.alice"
    assert body["tactical_policy_revision"]


def test_console_state_unknown_companion_returns_404() -> None:
    response = client.get("/v1/console/state", params={"companion_id": "companion.unknown"})
    assert response.status_code == 404


def test_console_memory_reset_clears_session_partition() -> None:
    response = client.post("/v1/console/memory/reset", json={"companion_id": "companion.alice"})
    assert response.status_code == 200
    body = response.json()
    assert body["reset"] is True
    assert body["cleared_sessions"] >= 0  # 无会话时为 0，也是成功
