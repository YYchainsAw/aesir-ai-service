"""记忆降级测试（SDD T023 / FR-011：记忆不可用时服务继续可用）。"""

from __future__ import annotations

import pytest

from app.schemas.memory import MemoryEntry
from app.services.memory.store import MemoryStore, MemoryStoreError
from app.services.memory.retrieval import retrieve


def test_unwritable_directory_raises_memory_error(tmp_path) -> None:
    """存储路径不可用（写入失败）：抛 MemoryStoreError，由上层捕获降级（不崩服务）。

    用「目录位置被普通文件占用」模拟跨平台不可写：mkdir/写 tmp 均以 OSError 失败
    （Windows 上 chmod 无法阻止目录内建文件）。
    """
    blocked = tmp_path / "blocked"
    blocked.write_text("占位文件", encoding="utf-8")  # companion.alice/ 目录无法创建

    store = MemoryStore("companion.alice", root=str(blocked))
    store.load()
    with pytest.raises(MemoryStoreError):
        store.append_short_term(MemoryEntry(content="写不进去"))


def test_corrupted_file_quarantines_and_starts_empty(tmp_path) -> None:
    """文件损坏：隔离损坏文件并以空记忆继续（回退初值，不卡死）。"""
    npc_dir = tmp_path / "aesir" / "companion.alice"
    npc_dir.mkdir(parents=True)
    (npc_dir / "memory.json").write_text("{ not valid json !!", encoding="utf-8")

    store = MemoryStore("companion.alice", root=str(tmp_path))
    store.load()
    snapshot = store.snapshot()
    assert snapshot.short_term == [] and snapshot.summaries == [] and snapshot.archive == []
    # 损坏文件被隔离（保留现场，不覆盖），新写入可用
    store.record_fact(MemoryEntry(content="重建后的新事实。"))
    restarted = MemoryStore("companion.alice", root=str(tmp_path))
    restarted.load()
    assert any(e.content == "重建后的新事实。" for e in restarted.snapshot().archive)
    assert (npc_dir / "memory.json.corrupt").exists()


def test_retrieval_failure_degrades_to_empty(tmp_path, monkeypatch) -> None:
    """检索层故障（存储抛错）→ 返回空记忆，不向调用方抛异常（服务继续）。"""

    class _BrokenStore:
        def snapshot(self):
            raise MemoryStoreError("检索失败模拟")

    assert retrieve(_BrokenStore(), budget=5) == []


def test_retrieval_respects_budget(tmp_path) -> None:
    store = MemoryStore("companion.alice", root=str(tmp_path))
    store.load()
    store.record_fact(MemoryEntry(content="重要承诺", source="promise", importance="critical"))
    store.record_fact(MemoryEntry(content="普通事实"))
    for i in range(10):
        store.append_short_term(MemoryEntry(content=f"短期{i}", source="player_statement"))

    entries = retrieve(store, budget=3)
    assert len(entries) == 3
    assert entries[0].importance == "critical"   # 重要性优先（FR-009 预算内排序）
