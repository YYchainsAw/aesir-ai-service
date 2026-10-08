"""S4/T029 L0/L3 能力门控回归。

demo-vn（L0）进程下：
- 对话 / 记忆 / 关系链路保持可用；
- 战术、战斗事件、自主行为、执行回执、v0.1 指令解析一律 403 显式拒绝，
  响应体带 ``CAPABILITY_LEVEL_INSUFFICIENT`` 结构化原因；
- 世界事件按档案声明门禁：已声明（gift_given）放行，未声明 403 ``EVENT_NOT_DECLARED``。

Aesir（L3）基线不受门控影响（由既有全量回归覆盖）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.combat_context import make_combat_context
from app.services.companion import profile_repository as pr
from app.services.tactical.event_policy import _reset_seen_events

RID = "99d7e6b4-f4f2-4d39-8c96-a23d293882f6"


@pytest.fixture()
def l0_client(monkeypatch):
    """切到 demo-vn（L0）进程；用例后恢复默认游戏并清缓存。"""
    monkeypatch.setenv("AESIR_GAME_ID", "demo-vn")
    pr._profile_cache.clear()  # noqa: SLF001
    pr._capability_cache.clear()  # noqa: SLF001
    _reset_seen_events()
    yield TestClient(app)
    monkeypatch.delenv("AESIR_GAME_ID", raising=False)
    pr._profile_cache.clear()  # noqa: SLF001
    pr._capability_cache.clear()  # noqa: SLF001
    _reset_seen_events()


def _assert_l3_reject(response, feature: str) -> None:
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["reason_code"] == "CAPABILITY_LEVEL_INSUFFICIENT"
    assert detail["feature"] == feature
    assert detail["game_id"] == "demo-vn"
    assert detail["capability_level"] == "L0"
    assert detail["required"] == "L3"


# -- L0 下保持可用的链路 -----------------------------------------------------


def test_l0_chat_still_available(l0_client) -> None:
    response = l0_client.post(
        "/v1/companion/chat",
        json={"text": "你好", "companion_id": "companion.narrator", "game_state": "conversation"},
    )
    assert response.status_code == 200


def test_l0_declared_world_event_allowed(l0_client) -> None:
    response = l0_client.post(
        "/v1/world/events",
        json={
            "protocol_version": "0.3",
            "request_id": "req.world.l0.001",
            "companion_id": "companion.narrator",
            "event": {
                "event_id": "event.world.l0.001",
                "event_type": "gift_given",
                "occurred_at": "2026-10-08T12:00:00Z",
                "sequence": 1,
                "details": {},
            },
            "world_context": {
                "snapshot_id": "44444444-4444-4444-8444-444444444444",
                "captured_at": "2026-10-08T12:00:00Z",
                "scene": "conversation",
                "player": {"id": "party.player", "hp_percent": 100},
                "companion": {"id": "companion.narrator", "hp_percent": 100, "mp_percent": 100},
            },
        },
    )
    assert response.status_code == 200


def test_l0_undeclared_world_event_rejected(l0_client) -> None:
    response = l0_client.post(
        "/v1/world/events",
        json={
            "protocol_version": "0.3",
            "request_id": "req.world.l0.002",
            "companion_id": "companion.narrator",
            "event": {
                "event_id": "event.world.l0.002",
                "event_type": "promise_kept",
                "occurred_at": "2026-10-08T12:00:00Z",
                "sequence": 1,
                "details": {},
            },
            "world_context": {
                "snapshot_id": "44444444-4444-4444-8444-444444444444",
                "captured_at": "2026-10-08T12:00:00Z",
                "scene": "conversation",
                "player": {"id": "party.player", "hp_percent": 100},
                "companion": {"id": "companion.narrator", "hp_percent": 100, "mp_percent": 100},
            },
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["reason_code"] == "EVENT_NOT_DECLARED"
    assert detail["event_type"] == "promise_kept"
    assert detail["game_id"] == "demo-vn"


# -- L0 下显式拒绝的完整链路 ---------------------------------------------------


def test_l0_tactical_command_rejected(l0_client) -> None:
    response = l0_client.post(
        "/v1/tactical/command",
        json={
            "protocol_version": "0.2",
            "request_id": RID,
            "text": "旁白，帮我回血",
            "combat_context": make_combat_context(player_hp=18).model_dump(),
        },
    )
    _assert_l3_reject(response, "tactical.command")


def test_l0_tactical_executions_rejected(l0_client) -> None:
    response = l0_client.post(
        "/v1/tactical/executions",
        json={
            "receipt": {
                "order_id": RID,
                "result": "executed",
                "encounter_id": "encounter.test.001",
            }
        },
    )
    _assert_l3_reject(response, "tactical.executions")


def test_l0_combat_events_rejected(l0_client) -> None:
    response = l0_client.post(
        "/v1/combat/events",
        json={
            "protocol_version": "0.2",
            "request_id": RID,
            "companion_id": "companion.narrator",
            "event": {
                "event_id": "event.combat.l0.001",
                "event_type": "boss_stunned",
                "occurred_at": "2026-10-08T12:00:00Z",
                "sequence": 1,
                "details": {},
            },
            "combat_context": make_combat_context(player_hp=18).model_dump(),
        },
    )
    _assert_l3_reject(response, "combat.events")


def test_l0_agent_step_rejected(l0_client) -> None:
    response = l0_client.post(
        "/v1/agent/step",
        json={
            "protocol_version": "0.3",
            "request_id": RID,
            "companion_id": "companion.narrator",
            "world_context": {
                "snapshot_id": "22222222-2222-4222-8222-222222222222",
                "captured_at": "2026-10-08T12:00:00Z",
                "scene": "conversation",
                "player": {"id": "party.player", "hp_percent": 100},
                "companion": {"id": "companion.narrator", "hp_percent": 100, "mp_percent": 100},
            },
        },
    )
    _assert_l3_reject(response, "agent.step")


def test_l0_legacy_parse_command_rejected(l0_client) -> None:
    response = l0_client.post("/parse-command", json={"text": "旁白，撤退"})
    _assert_l3_reject(response, "commands.parse")


def test_l0_cross_game_companion_404(l0_client) -> None:
    """L0 进程请求 Aesir 角色：404，不回退默认角色。"""
    response = l0_client.post(
        "/v1/companion/chat",
        json={"text": "你好", "companion_id": "companion.alice", "game_state": "conversation"},
    )
    assert response.status_code == 404
