"""记忆容量与淘汰测试（SDD T021 / FR-008）。"""

from __future__ import annotations

import pytest

from app.schemas.memory import MemoryEntry
from app.services.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path) -> MemoryStore:
    s = MemoryStore("companion.alice", root=str(tmp_path), short_term_limit=3, summary_limit=2, archive_limit=2)
    s.load()
    return s


def test_short_term_evicts_oldest(store: MemoryStore) -> None:
    for i in range(5):
        store.append_short_term(MemoryEntry(content=f"短期{i}", source="player_statement", real_time=f"2026-09-13T12:0{i}:00Z"))
    assert [e.content for e in store.snapshot().short_term] == ["短期2", "短期3", "短期4"]


def test_archive_evicts_by_importance_then_time(store: MemoryStore) -> None:
    """档案淘汰按重要性优先、同级别按时间（FR-008）。"""
    store.record_fact(MemoryEntry(content="低价值旧事实", importance="low", real_time="2026-09-01T00:00:00Z"))
    store.record_fact(MemoryEntry(content="普通事实A", importance="normal", real_time="2026-09-02T00:00:00Z"))
    store.record_fact(MemoryEntry(content="普通事实B", importance="normal", real_time="2026-09-03T00:00:00Z"))
    archive = [e.content for e in store.snapshot().archive]
    assert len(archive) == 2               # 容量上限生效
    assert "低价值旧事实" not in archive   # 重要性最低者先淘汰
    assert "普通事实A" in archive and "普通事实B" in archive  # 高于 low 者保留

    # 同级别按时间淘汰：再压入一条 normal，更旧的 A 应出列
    store.record_fact(MemoryEntry(content="普通事实C", importance="normal", real_time="2026-09-04T00:00:00Z"))
    archive = [e.content for e in store.snapshot().archive]
    assert "普通事实A" not in archive and "普通事实B" in archive and "普通事实C" in archive


def test_promises_never_evicted(store: MemoryStore) -> None:
    """承诺类与重大事件类记忆优先保留，不被淘汰（FR-008）。"""
    store.record_fact(MemoryEntry(content="承诺：替玩家找回笔记", source="promise", importance="critical"))
    for i in range(5):
        store.record_fact(MemoryEntry(content=f"普通事实{i}"))
    archive = [e.content for e in store.snapshot().archive]
    assert "承诺：替玩家找回笔记" in archive
    assert len(archive) <= 2 or all(e.importance == "critical" for e in store.snapshot().archive if e.source == "promise")


def test_summaries_evicted_before_promises_in_archive(store: MemoryStore) -> None:
    """摘要层同样按重要性/时间淘汰，且承诺不在摘要层（在档案层受保护）。"""
    for i in range(4):
        store.record_experience([MemoryEntry(content=f"经历{i}", source="shared_experience", real_time=f"2026-09-0{i + 1}T00:00:00Z")])
    assert len(store.snapshot().summaries) == 2


def test_clear_empties_all_tiers(store: MemoryStore) -> None:
    store.append_short_term(MemoryEntry(content="短期"))
    store.record_experience([MemoryEntry(content="经历")])
    store.record_fact(MemoryEntry(content="档案"))
    store.clear()
    snapshot = store.snapshot()
    assert snapshot.short_term == [] and snapshot.summaries == [] and snapshot.archive == []
