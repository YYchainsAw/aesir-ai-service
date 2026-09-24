"""多角色隔离测试（SDD T080 / US8 / FR-044）。

验证：新增角色无需改动代码结构即可正确路由；不同角色的记忆与关系
状态互不干扰；未登记角色被拒绝且不回退默认角色。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.companion.dialogue_service import create_dialogue_reply
from app.services.companion.profile_repository import (
    CompanionProfileRepository,
    UnknownCompanionError,
    get_registered_profile,
    list_registered_companions,
)
from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.memory.store import get_memory_store, reset_memory_stores
from app.services.relationship.state import get_relationship_store, reset_relationship_stores

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_stores(monkeypatch, tmp_path):
    """每测试独立：记忆与关系落临时目录，并清空进程内缓存。"""
    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path / "memory"))
    monkeypatch.setenv("AESIR_RELATIONSHIP_ROOT", str(tmp_path / "relationship"))
    reset_memory_stores()
    reset_relationship_stores()
    yield
    reset_memory_stores()
    reset_relationship_stores()


def test_registry_lists_both_companions() -> None:
    """T081：注册表能发现 Alice 与 Bruno 两个角色。"""
    ids = list_registered_companions()
    assert "companion.alice" in ids
    assert "companion.bruno" in ids
    assert len(ids) == 2


def test_registry_loads_distinct_profiles() -> None:
    """不同角色返回不同人设快照。"""
    alice = get_registered_profile("companion.alice")
    bruno = get_registered_profile("companion.bruno")

    assert alice.companion_id == "companion.alice"
    assert alice.display_name == "Alice"
    assert bruno.companion_id == "companion.bruno"
    assert bruno.display_name == "Bruno"
    # 表现目录不同：Alice 有明亮情绪，Bruno 以 neutral 为基线
    assert "emotion.bright" in alice.allowed_emotion_ids
    assert "emotion.bright" not in bruno.allowed_emotion_ids
    assert "emotion.neutral" in bruno.allowed_emotion_ids


def test_dialogue_service_routes_by_companion_id(monkeypatch) -> None:
    """T082：对话服务按 companion_id 选择角色，返回对应默认/mock 回复。"""
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")

    alice = create_dialogue_reply(
        CompanionDialogueRequest(text="今天天气不错。", companion_id="companion.alice")
    )
    bruno = create_dialogue_reply(
        CompanionDialogueRequest(text="今天天气不错。", companion_id="companion.bruno")
    )

    assert alice.companion_id == "companion.alice"
    assert bruno.companion_id == "companion.bruno"
    # 同一输入下两角色 mock 回复应不同（Alice 活泼 / Bruno 寡言）
    assert alice.reply_text != bruno.reply_text


def test_unknown_companion_returns_404_and_no_fallback() -> None:
    """FR-044：未登记角色 404，不回退默认角色人格。"""
    with pytest.raises(UnknownCompanionError):
        get_registered_profile("companion.unknown")

    response = client.post(
        "/v1/companion/chat",
        json={
            "text": "你好。",
            "companion_id": "companion.unknown",
            "game_state": "conversation",
        },
    )
    assert response.status_code == 404


def test_memory_is_isolated_between_companions() -> None:
    """两角色记忆互不污染：Alice 的印象 Bruno 读不到。"""
    # 直接写入不同角色的记忆存储（模拟各自经历）
    alice_store = get_memory_store("companion.alice")
    bruno_store = get_memory_store("companion.bruno")

    alice_store.record_mention(["钓鱼"])
    bruno_store.record_mention(["巡逻"])

    alice_topics = {i.topic for i in alice_store.snapshot().impressions}
    bruno_topics = {i.topic for i in bruno_store.snapshot().impressions}

    assert "钓鱼" in alice_topics
    assert "钓鱼" not in bruno_topics
    assert "巡逻" in bruno_topics
    assert "巡逻" not in alice_topics


def test_relationship_is_isolated_between_companions() -> None:
    """两角色关系数值互不污染：Alice 加分 Bruno 不变。"""
    alice_store = get_relationship_store("companion.alice")
    bruno_store = get_relationship_store("companion.bruno")

    alice_store.apply_event("gift_given", occurred_at="2026-09-24T12:00:00Z")

    assert alice_store.state().value > 20  # 默认初值 20，礼物应加分
    assert bruno_store.state().value == 20  # Bruno 保持初值


def test_agent_step_accepts_second_companion() -> None:
    """/v1/agent/step 主入口无需改动即可处理第二角色。"""
    from app.api.v1 import agent as agent_module

    agent_module._reset_heartbeat_tracker()
    response = client.post(
        "/v1/agent/step",
        json={
            "protocol_version": "0.3",
            "request_id": "00000000-0000-4000-8000-000000000001",
            "companion_id": "companion.bruno",
            "world_context": {
                "snapshot_id": "11111111-1111-4111-8111-111111111111",
                "captured_at": "2026-09-24T12:00:00Z",
                "scene": "exploration",
                "player": {"id": "party.player", "hp_percent": 80},
                "companion": {"id": "companion.bruno", "hp_percent": 90, "mp_percent": 70},
                "interactables": [
                    {"object_id": "object.campfire.001", "kind": "prop", "distance_m": 3.5, "notable": True}
                ],
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["companion_id"] == "companion.bruno"
    assert body["observability"]["persona_revision"] != ""


def test_profile_repository_load_registered_uses_directory() -> None:
    """load_registered 从 data/companions/ 目录扫描 YAML，不依赖硬编码主角色。"""
    repository = CompanionProfileRepository()
    profiles = {
        repository.load_registered(cid).companion_id: repository.load_registered(cid).display_name
        for cid in repository.list_registered()
    }
    assert profiles == {
        "companion.alice": "Alice",
        "companion.bruno": "Bruno",
    }
