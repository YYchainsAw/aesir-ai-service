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
