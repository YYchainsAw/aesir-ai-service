"""记忆分级存储读写与分区测试（SDD T020 / FR-006~FR-007）。"""

from __future__ import annotations

import threading

import pytest

from app.schemas.memory import MemoryEntry
from app.services.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path) -> MemoryStore:
    s = MemoryStore("companion.alice", root=str(tmp_path))
    s.load()
    return s


def test_entry_roundtrip_across_tiers(store: MemoryStore) -> None:
    """短忆/摘要/档案三层各自落盘并可回读。"""
    store.append_short_term(MemoryEntry(content="玩家说：我怕高。", source="player_statement"))
    store.record_experience([MemoryEntry(content="一起击败了森林深处的魔像。", source="shared_experience")])
    store.record_fact(MemoryEntry(content="玩家答应找回那本笔记。", source="promise", importance="critical"))

    snapshot = store.snapshot()
    assert len(snapshot.short_term) == 1
    assert len(snapshot.summaries) >= 1
    assert len(snapshot.archive) == 1
    assert snapshot.archive[0].source == "promise"


def test_partitions_by_npc(tmp_path) -> None:
    """按角色分区：不同 NPC 的记忆互不可见（FR-044）。"""
    alice = MemoryStore("companion.alice", root=str(tmp_path))
    alice.load()
    alice.record_fact(MemoryEntry(content="艾莉的长期档案条目。"))

    bob = MemoryStore("companion.bob", root=str(tmp_path))
    bob.load()
    assert bob.snapshot().archive == []
    bob.record_fact(MemoryEntry(content="Bob 自己的档案条目。"))

    assert len(alice.snapshot().archive) == 1
    assert len(bob.snapshot().archive) == 1
    assert alice.snapshot().archive[0].content != bob.snapshot().archive[0].content


def test_record_mention_filters_blacklisted_topics(store: MemoryStore) -> None:
    """合并入口统一过滤黑名单：LLM 顺带返回「艾莉」也不入印象。"""
    store.record_mention(["钓鱼", "艾莉", "名字"])
    snapshot = store.snapshot()
    assert [i.topic for i in snapshot.impressions] == ["钓鱼"]


def test_record_mention_filters_noise_fragments(store: MemoryStore) -> None:
    """合并入口统一过滤口语噪声：LLM 顺带返回「不过」「意思呀」也不入印象。"""
    store.record_mention(["钓鱼", "不过", "意思呀", "趁天"])
    snapshot = store.snapshot()
    assert [i.topic for i in snapshot.impressions] == ["钓鱼"]


def test_record_mention_persists_care_scaled_boost(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """郑重声明的等效提及加成（在意值缩放后）持久化，检索按其分档。

    提高注入权重阈值到 2.0 隔离「近期闲聊也记得」的默认语义，专测加成
    档位随在意值分档：无感加成 0.5（权重 1.32）不入注入，极在意加成
    4.0（权重 2.59）首提即 deep。
    """
    monkeypatch.setenv("AESIR_MEMORY_IMPRESSION_INJECT_WEIGHT", "2.0")

    from app.services.memory.retrieval import retrieve_impressions

    # 无感时缩放后的加成 0.5：权重 1.32 < 2.0，声明不入注入档。
    store.record_mention(["搬家"], salient=True, salience_boost=0.5)
    assert retrieve_impressions(store) == []

    # 极在意时缩放后的加成 4.0：首提即 deep。
    store.record_mention(["上海"], salient=True, salience_boost=4.0)
    ranked = retrieve_impressions(store)
    assert [i.topic for i in ranked] == ["上海"]
    shanghai = next(i for i in store.snapshot().impressions if i.topic == "上海")
    assert shanghai.salience_boost == 4.0


def test_recent_single_mention_is_retrieved(store: MemoryStore) -> None:
    """近期单次提及的闲聊也进检索（用户语义：时间不过太久就记得）。"""
    from app.services.memory.retrieval import retrieve_impressions

    store.record_mention(["钓鱼"])
    ranked = retrieve_impressions(store)
    assert [i.topic for i in ranked] == ["钓鱼"]


def test_stored_noise_fragments_are_not_retrieved(store: MemoryStore) -> None:
    """检索侧兜底：旧数据里已落的噪声碎片（不过 / 意思呀）不再注入。"""
    from app.services.memory.retrieval import retrieve_impressions

    store.record_mention(["钓鱼"])
    with store._lock:
        store._snapshot.impressions.append(
            type(store._snapshot.impressions[0])(topic="不过")
        )
    assert [i.topic for i in retrieve_impressions(store)] == ["钓鱼"]


def test_stale_single_mention_fades_out_of_retrieval(
    store: MemoryStore,
) -> None:
    """三天前的单次提及淡出检索；再提一次（当天）又被记起。"""
    from datetime import datetime, timedelta, timezone

    from app.services.memory.retrieval import retrieve_impressions

    store.record_mention(["钓鱼"])
    # snapshot() 返回深拷贝，直接改存储内部状态的 last_seen 模拟「3 天没提」。
    with store._lock:
        store._snapshot.impressions[0].last_seen = (
            datetime.now(timezone.utc) - timedelta(days=3)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
    assert retrieve_impressions(store) == []
    store.record_mention(["钓鱼"])
    assert [i.topic for i in retrieve_impressions(store)] == ["钓鱼"]


def test_salience_boost_takes_max_not_retreat(store: MemoryStore) -> None:
    """在意加深可强化加成，淡化不回退（与 salient 旗标同一语义）。"""
    store.record_mention(["医院"], salient=True, salience_boost=4.0)
    store.record_mention(["医院"], salient=True, salience_boost=1.0)
    impression = store.snapshot().impressions[0]
    assert impression.salience_boost == 4.0
    assert impression.mention_count == 2


def test_companion_mention_does_not_reinforce_existing_topic(store: MemoryStore) -> None:
    """她自己反复提起的话题不加深、不刷新（防「注入 → 她提起 → 更必注入」回路）。

    实测 2026-09-21：钓鱼被聊到 24 次，其中多数是她自己接话带出来的；
    玩家只提一次时计数与 last_seen 照常强化。
    """
    store.record_mention(["钓鱼"], origin="player")
    before = store.snapshot().impressions[0]
    assert before.mention_count == 1

    store.record_mention(["钓鱼"], origin="companion")
    after = store.snapshot().impressions[0]
    assert after.mention_count == 1
    assert after.last_seen == before.last_seen

    store.record_mention(["钓鱼"], origin="player")
    assert store.snapshot().impressions[0].mention_count == 2


def test_companion_mention_still_creates_first_impression(store: MemoryStore) -> None:
    """首次由她提起的话题仍留痕：她记得自己说过什么（只是不再自强化）。"""
    store.record_mention(["月见草"], origin="companion")
    impression = store.snapshot().impressions[0]
    assert impression.topic == "月见草"
    assert impression.origin == "companion"
    assert impression.mention_count == 1


def test_player_mention_upgrades_companion_origin(store: MemoryStore) -> None:
    """她先提、玩家后提：来源升级为 player（注入措辞不再说成「她自己提的」）。"""
    store.record_mention(["月见草"], origin="companion")
    store.record_mention(["月见草"], origin="player")
    impression = store.snapshot().impressions[0]
    assert impression.origin == "player"
    assert impression.mention_count == 2


def test_retrieve_impressions_cools_down_recently_discussed_topics(
    store: MemoryStore,
) -> None:
    """近期会话里已聊过的话题本轮不注入（防复读同一话题）。"""
    from app.services.memory.retrieval import retrieve_impressions

    store.record_mention(["钓鱼"])
    store.record_mention(["旅行者"])
    assert {i.topic for i in retrieve_impressions(store)} == {"钓鱼", "旅行者"}

    cooled = retrieve_impressions(store, recent_texts=["我们聊聊钓鱼吧"])
    assert [i.topic for i in cooled] == ["旅行者"]


def test_drop_impressions_removes_topics_and_persists(store: MemoryStore) -> None:
    """旧数据清洗入口：按主题删除并落盘，未命中的主题不受影响。

    噪声主题走合并入口会被直接过滤，因此这里直接注入快照——模拟过滤规则
    升级**之前**已经落在盘上的历史数据。
    """
    from app.schemas.memory import TopicImpression

    store.record_mention(["钓鱼"])
    with store._lock:
        store._snapshot.impressions.extend(
            [TopicImpression(topic="不过"), TopicImpression(topic="人机味")]
        )
    assert store.drop_impressions({"不过", "人机味", "不存在的主题"}) == 2
    assert [i.topic for i in store.snapshot().impressions] == ["钓鱼"]

    reloaded = MemoryStore("companion.alice", root=str(store._dir.parent))
    reloaded.load()
    assert [i.topic for i in reloaded.snapshot().impressions] == ["钓鱼"]


def test_concurrent_append_is_thread_safe(tmp_path) -> None:
    """并发写入不丢条目、不损坏文件（T020 并发安全）。"""
    store = MemoryStore("companion.alice", root=str(tmp_path))
    store.load()
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            for i in range(5):
                store.append_short_term(
                    MemoryEntry(content=f"线程{index}条目{i}", source="player_statement")
                )
        except Exception as error:  # pragma: no cover - 记录意外异常
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    reloaded = MemoryStore("companion.alice", root=str(tmp_path))
    reloaded.load()
    assert len(reloaded.snapshot().short_term) == 40
