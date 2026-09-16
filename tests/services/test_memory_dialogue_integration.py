"""对话链路接入记忆的集成测试（SDD T028 / T030 + 模糊印象层）。

覆盖：对话后按主题写入模糊印象、重启后可回读（SC-001 的服务层路径）、
记忆故障时对话不受影响（FR-011）、迁移把逐字发言转为主题印象。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.memory.store import get_memory_store, reset_memory_stores

client = TestClient(app)


@pytest.fixture()
def _fresh_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path))
    reset_memory_stores()
    yield tmp_path
    reset_memory_stores()


def _chat(text: str, session_id: str | None = None):
    payload = {
        "text": text,
        "companion_id": "companion.alice",
        "game_state": "conversation",
    }
    if session_id:
        payload["session_id"] = session_id
    return client.post("/v1/companion/chat", json=payload)


def test_dialogue_records_topic_impression(_fresh_memory) -> None:
    response = _chat("钓鱼、钓鱼，今天还是想钓鱼。", session_id="s1")
    assert response.status_code == 200

    store = get_memory_store("companion.alice")
    topics = [i.topic for i in store.snapshot().impressions]
    assert "钓鱼" in topics


def test_dialogue_memory_survives_store_reload(_fresh_memory) -> None:
    """对话写入 → 新存储实例（模拟重启）→ 回读正确（SC-001）。"""
    _chat("钓鱼、钓鱼，今天还是想钓鱼。", session_id="s2")

    reset_memory_stores()  # 丢弃缓存，模拟重启
    store = get_memory_store("companion.alice")  # 重新 load
    topics = [i.topic for i in store.snapshot().impressions]
    assert "钓鱼" in topics


def test_repeated_mentions_reinforce_the_same_topic(_fresh_memory) -> None:
    """同一主题多次提及 → 合并计数（频率强化，不是重复建条目）。"""
    for _ in range(4):
        _chat("钓鱼、钓鱼，还是钓鱼。", session_id="s2")

    impressions = get_memory_store("companion.alice").snapshot().impressions
    fishing = [i for i in impressions if i.topic == "钓鱼"]
    assert len(fishing) == 1
    assert fishing[0].mention_count >= 4


def test_dialogue_continues_when_memory_store_fails(monkeypatch, tmp_path) -> None:
    """记忆写入故障 → 对话仍正常返回（FR-011：降级不中断）。"""
    from app.services.memory import store as store_module

    def _broken_record(self, topics):
        raise store_module.MemoryStoreError("模拟写入失败")

    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr(store_module.MemoryStore, "record_mention", _broken_record)

    response = _chat("艾莉，今天天气不错。")
    assert response.status_code == 200
    assert response.json()["reply_text"]


def test_verbatim_migration_converts_statements_to_impressions(_fresh_memory) -> None:
    """迁移：旧版逐字短期发言 → 主题印象后从短期层移除。"""
    from app.schemas.memory import MemoryEntry

    store = get_memory_store("companion.alice")
    for text in ("我最喜欢钓鱼。", "还是钓鱼，昨天也钓了。"):
        store.append_short_term(
            MemoryEntry(content=text, source="player_statement", tags=["dialogue"])
        )

    migrated = store.migrate_verbatim_to_impressions()

    snapshot = store.snapshot()
    assert migrated == 2
    assert snapshot.short_term == []
    assert any(i.topic == "钓鱼" for i in snapshot.impressions)


def test_console_reset_clears_long_term_memory(_fresh_memory) -> None:
    _chat("记住：我最讨厌蘑菇。", session_id="s3")
    store = get_memory_store("companion.alice")
    assert store.snapshot().impressions

    response = client.post("/v1/console/memory/reset", json={"companion_id": "companion.alice"})
    assert response.status_code == 200
    assert response.json()["reset"] is True

    snapshot = get_memory_store("companion.alice").snapshot()
    assert (
        snapshot.short_term == []
        and snapshot.archive == []
        and snapshot.summaries == []
        and snapshot.impressions == []
    )
