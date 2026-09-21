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

    def _broken_record(self, topics, **_kwargs):
        raise store_module.MemoryStoreError("模拟写入失败")

    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr(store_module.MemoryStore, "record_mention", _broken_record)

    response = _chat("艾莉，今天天气不错。")
    assert response.status_code == 200
    assert response.json()["reply_text"]


def test_solemn_statement_archived_verbatim_and_impressed(_fresh_memory) -> None:
    """双通道：郑重声明逐字入档案（精确复述）+ 主题入印象（显著性加成）。"""
    _chat("记住：我最讨厌蘑菇。", session_id="s4")

    snapshot = get_memory_store("companion.alice").snapshot()
    assert any(
        "蘑菇" in entry.content and entry.importance == "high"
        for entry in snapshot.archive
    )
    salient_topics = [i for i in snapshot.impressions if "蘑菇" in i.topic]
    assert salient_topics and salient_topics[0].salient is True


def test_companion_own_reply_topics_recorded(_fresh_memory) -> None:
    """艾莉自己的回复也提取主题入印象（非显著）——她记得自己说过什么。"""
    from app.schemas.companion_dialogue import (
        CompanionDialogueRequest,
        CompanionDialogueResponse,
    )
    from app.services.companion.dialogue_service import _record_turn

    request = CompanionDialogueRequest(
        text="嗯嗯好的。",
        companion_id="companion.alice",
        game_state="conversation",
    )
    response = CompanionDialogueResponse(
        companion_id="companion.alice",
        session_id=None,
        reply_text="钓鱼吗？我也挺喜欢钓鱼的。",
        emotion_id="neutral",
        gesture_id="idle",
        facial_expression_id="default",
    )
    _record_turn(request, response)  # 玩家侧无主题，回复侧主题入印象

    impressions = get_memory_store("companion.alice").snapshot().impressions
    assert "钓鱼" in [i.topic for i in impressions]
    assert all(not i.salient for i in impressions)  # 她自己的话不显著

    # 她自己说的主题标 origin=companion——注入文案按「她说过」而非「玩家提过」。
    from app.services.memory.retrieval import format_impression_block

    reply_impression = next(i for i in impressions if i.topic == "钓鱼")
    assert reply_impression.origin == "companion"
    line = format_impression_block([reply_impression], "艾莉").splitlines()[-1]
    assert "her own words" in line
    assert "player often brings up" not in line

    # 玩家随后也提及时升级为 player（双方便都算数）。
    from app.services.memory.store import get_memory_store as _get_store

    _get_store("companion.alice").record_mention(["钓鱼"], origin="player")
    upgraded = next(
        i for i in _get_store("companion.alice").snapshot().impressions if i.topic == "钓鱼"
    )
    assert upgraded.origin == "player"


def test_plain_chat_is_not_archived(_fresh_memory) -> None:
    """普通闲聊只入印象层，不进档案（档案留给郑重声明/承诺/经历）。"""
    _chat("钓鱼、钓鱼，还是钓鱼。", session_id="s5")

    snapshot = get_memory_store("companion.alice").snapshot()
    assert snapshot.archive == []
    assert all(not i.salient for i in snapshot.impressions)


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


class _StubFactsLLM:
    """返回固定负载的 LLM 替身：用于验证 facts 通道的落档与拦截。"""

    def __init__(self, facts: list[str]) -> None:
        self.facts = facts

    def generate_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        return {
            "action": "reply",
            "reply_text": "记下了。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.enthusiastic_nod",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
            "topics": [],
            "facts": self.facts,
            "salient": False,
        }


def _chat_with_facts(monkeypatch, facts: list[str], text: str, session_id: str = "s6"):
    """走 LLM 后端发一轮对话，LLM 顺带返回指定 facts。"""
    from app.services.companion import llm_dialogue_service as llm_module

    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")
    monkeypatch.setattr(llm_module, "create_llm_client", lambda: _StubFactsLLM(facts))
    return _chat(text, session_id=session_id)


def test_grounded_fact_is_archived(_fresh_memory, monkeypatch) -> None:
    """LLM 抽出的事实（玩家真说过）写进档案——她从此有据可说。"""
    response = _chat_with_facts(monkeypatch, ["玩家养了一只叫小黑的猫"], "我养了只猫，它叫小黑。")
    assert response.status_code == 200

    archive = get_memory_store("companion.alice").snapshot().archive
    assert [entry.content for entry in archive] == ["玩家养了一只叫小黑的猫"]


def test_invented_fact_is_rejected(_fresh_memory, monkeypatch) -> None:
    """编造的事实被接地校验拦下：档案里不留永久错误记忆。"""
    _chat_with_facts(monkeypatch, ["玩家上次给艾莉烤了鱼"], "今天天气不错。")

    assert get_memory_store("companion.alice").snapshot().archive == []


def test_archived_fact_is_injected_next_turn(_fresh_memory, monkeypatch) -> None:
    """落档的事实下一轮进入注入块，且措辞标明「她确定知道」。"""
    from app.services.memory.retrieval import format_memory_block, retrieve

    _chat_with_facts(monkeypatch, ["玩家养了一只叫小黑的猫"], "我养了只猫，它叫小黑。")

    block = format_memory_block(retrieve(get_memory_store("companion.alice")), "艾莉")
    assert "玩家养了一只叫小黑的猫" in block
    assert "sure of these" in block  # 给她「可以直说」的许可，而非含糊其辞


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
