"""对话链路接入记忆的集成测试（SDD T028 / T030）。

覆盖：对话后写入短期记忆、重启后可回读（SC-001 的服务层路径）、
记忆故障时对话不受影响（FR-011）。
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


def test_dialogue_records_player_statement_to_short_term(_fresh_memory) -> None:
    response = _chat("艾莉，我怕高，别带我去悬崖那边。", session_id="s1")
    assert response.status_code == 200

    store = get_memory_store("companion.alice")
    short_term = [e.content for e in store.snapshot().short_term]
    assert any("怕高" in content for content in short_term)


def test_dialogue_memory_survives_store_reload(_fresh_memory) -> None:
    """对话写入 → 新存储实例（模拟重启）→ 回读正确（SC-001）。"""
    _chat("我小时候在湖边长大，最喜欢钓鱼。", session_id="s2")

    reset_memory_stores()  # 丢弃缓存，模拟重启
    store = get_memory_store("companion.alice")  # 重新 load
    contents = [e.content for e in store.snapshot().short_term]
    assert any("钓鱼" in content for content in contents)


def test_dialogue_continues_when_memory_store_fails(monkeypatch, tmp_path) -> None:
    """记忆写入故障 → 对话仍正常返回（FR-011：降级不中断）。"""
    from app.services.memory import store as store_module

    def _broken_append(self, entry):
        raise store_module.MemoryStoreError("模拟写入失败")

    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr(store_module.MemoryStore, "append_short_term", _broken_append)

    response = _chat("艾莉，今天天气不错。")
    assert response.status_code == 200
    assert response.json()["reply_text"]


def test_console_reset_clears_long_term_memory(_fresh_memory) -> None:
    _chat("记住：我最讨厌蘑菇。", session_id="s3")
    store = get_memory_store("companion.alice")
    assert store.snapshot().short_term

    response = client.post("/v1/console/memory/reset", json={"companion_id": "companion.alice"})
    assert response.status_code == 200
    assert response.json()["reset"] is True

    snapshot = get_memory_store("companion.alice").snapshot()
    assert snapshot.short_term == [] and snapshot.archive == [] and snapshot.summaries == []
