"""记忆持久化与重启回读测试（SDD T022 / FR-006，SC-001 前置）。"""

from __future__ import annotations

from app.schemas.memory import MemoryEntry
from app.services.memory.store import MemoryStore


def test_reload_reads_back_all_entries_100_percent(tmp_path) -> None:
    """写入 → 新实例（模拟重启）→ 回读正确率 100%。"""
    first = MemoryStore("companion.alice", root=str(tmp_path))
    first.load()
    expected: list[str] = []
    for i in range(10):
        content = f"记忆条目{i}"
        first.append_short_term(MemoryEntry(content=content, source="player_statement"))
        expected.append(content)
    first.record_experience([MemoryEntry(content="一起击败了魔像。", source="shared_experience")])
    first.record_fact(MemoryEntry(content="玩家说：我怕高。"))
    first.record_fact(MemoryEntry(content="承诺：我会替你找回笔记。", source="promise", importance="critical"))

    restarted = MemoryStore("companion.alice", root=str(tmp_path))
    restarted.load()
    snapshot = restarted.snapshot()
    all_contents = {
        e.content for tier in ("short_term", "summaries", "archive") for e in getattr(snapshot, tier)
    }
    for content in expected + ["玩家说：我怕高。", "承诺：我会替你找回笔记。"]:
        assert content in all_contents
    # 摘要条目带日期前缀（T026 聚合格式），按内容包含断言
    assert any("一起击败了魔像。" in e.content for e in snapshot.summaries)


def test_survives_process_boundary_via_factory(tmp_path) -> None:
    """模块级入口两次获取（模拟两次进程/会话）仍读到同一份持久化记忆。"""
    from app.services.memory.store import get_memory_store

    store = get_memory_store("companion.alice", root=str(tmp_path))
    store.record_fact(MemoryEntry(content="玩家曾替她挡下攻击。"))

    again = get_memory_store("companion.alice", root=str(tmp_path))
    assert any(e.content == "玩家曾替她挡下攻击。" for e in again.snapshot().archive)
