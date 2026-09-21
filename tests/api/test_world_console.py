"""`/v1/world/events` 的 HTTP 边界与 `/v1/console/*` 调试端点测试（SDD T014 / T015）。

本文件只保留**边界**与 console 覆盖：世界事件的策略行为（生活事件反应、
战斗类经世界通道、幂等与关系防刷）已由 ``test_world_events.py`` 与
``test_world_events_idempotency.py`` 系统覆盖，这里不再重复。
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def test_world_event_unregistered_companion_returns_404() -> None:
    """FR-044：未登记角色明确拒绝，不静默回退到主队友人设。"""
    response = client.post("/v1/world/events", json=_event_payload(companion_id="companion.unknown"))
    assert response.status_code == 404


def test_console_state_returns_registered_summary() -> None:
    response = client.get("/v1/console/state", params={"companion_id": "companion.alice"})
    assert response.status_code == 200
    body = response.json()
    assert "companion.alice" in body["registered_companions"]
    assert body["companion_id"] == "companion.alice"
    assert body["tactical_policy_revision"]


def test_console_state_exposes_us7_debug_fields() -> None:
    """T077：调试台返回场景/情绪/关系/近期记忆/版本（如实，不虚构）。"""
    from app.services.console.runtime_state import reset_runtime_observations

    reset_runtime_observations()
    # 先跑一次对话，观测记录应有情绪
    chat = client.post(
        "/v1/companion/chat",
        json={"text": "艾莉，今天心情怎么样？", "companion_id": "companion.alice"},
    )
    assert chat.status_code == 200
    response = client.get("/v1/console/state", params={"companion_id": "companion.alice"})
    assert response.status_code == 200
    body = response.json()
    # 版本字段（US7 链路信息）
    assert body["persona_revision"]
    assert body["agency_policy_revision"]
    # 关系字段（体系故障降级为空，但不缺字段）
    assert "relationship_stage" in body
    assert "relationship_value" in body
    # 运行观测：对话路径只记录情绪；场景来自 /v1/agent/step（此处未调用，可为空）
    assert body["last_emotion_id"]
    assert isinstance(body["recent_memory"], list)


def test_console_state_unknown_companion_returns_404() -> None:
    response = client.get("/v1/console/state", params={"companion_id": "companion.unknown"})
    assert response.status_code == 404


def test_console_memory_reset_clears_session_partition() -> None:
    response = client.post("/v1/console/memory/reset", json={"companion_id": "companion.alice"})
    assert response.status_code == 200
    body = response.json()
    assert body["reset"] is True
    assert body["cleared_sessions"] >= 0  # 无会话时为 0，也是成功


def test_console_memory_view_shows_tiers_after_chat() -> None:
    # 对话写入模糊印象后，调试端点能看到分层视图（方案 A /memory 命令的数据源）。
    chat = client.post(
        "/v1/companion/chat",
        json={
            "text": "记住：我最讨厌蘑菇。",
            "companion_id": "companion.alice",
            "game_state": "conversation",
        },
    )
    assert chat.status_code == 200

    response = client.get("/v1/console/memory", params={"companion_id": "companion.alice"})
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["impressions"] >= 1
    assert any("蘑菇" in impression["topic"] for impression in body["impressions"])
    assert all(impression["mention_count"] >= 1 for impression in body["impressions"])
    # 玩家说的话 origin=player；视图带 origin 供调试区分「玩家提过/她自己说过」。
    assert all(impression["origin"] in ("player", "companion") for impression in body["impressions"])


def test_console_memory_view_unknown_companion_returns_404() -> None:
    response = client.get("/v1/console/memory", params={"companion_id": "companion.unknown"})
    assert response.status_code == 404
