"""US1 记忆持久化演示脚本（SDD T031）：写入 → 重启 → 回读。

不依赖起服务：直接使用记忆存储，用「新实例 + 重新 load()」模拟服务重启。
对话链路接入（写入时机 / prompt 注入）见 app/services/companion/dialogue_service.py。

用法：
    .venv/Scripts/python -m scripts.demo_memory_persistence
    .venv/Scripts/python -m scripts.demo_memory_persistence --root data/memory   # 指定根目录
"""

from __future__ import annotations

import argparse
import sys
import tempfile

from app.schemas.memory import MemoryEntry
from app.services.memory.retrieval import retrieve
from app.services.memory.store import MemoryStore

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def main(root: str) -> int:
    print(f"=== US1 记忆持久化演示（根目录：{root}）===")

    # 1. 写入（第一次「运行」）
    first = MemoryStore("companion.alice", root=root)
    first.load()
    first.record_fact(MemoryEntry(content="玩家说：我怕高。", source="player_statement", importance="high"))
    first.record_experience([
        MemoryEntry(content="一起击败了森林深处的石魔像", source="shared_experience", importance="high"),
        MemoryEntry(content="在那之后一起烤了鱼", source="shared_experience"),
    ])
    first.record_fact(MemoryEntry(content="玩家答应替艾莉找回借走的那本笔记。", source="promise", importance="critical"))
    first.append_short_term(MemoryEntry(content="今天聊到了北边的遗迹"))
    print(f"已写入：档案 {len(first.snapshot().archive)} 条、摘要 {len(first.snapshot().summaries)} 条、短期 {len(first.snapshot().short_term)} 条")

    # 2. 模拟重启：新实例 + 重新 load()
    restarted = MemoryStore("companion.alice", root=root)
    restarted.load()
    snapshot = restarted.snapshot()
    print(f"重启回读：档案 {len(snapshot.archive)} 条、摘要 {len(snapshot.summaries)} 条、短期 {len(snapshot.short_term)} 条")
    for entry in snapshot.archive:
        print(f"  [档案/{entry.importance}] {entry.content}")
    for entry in snapshot.summaries:
        print(f"  [摘要/{entry.importance}] {entry.content}")

    # 3. 注入预算检索（LLM prompt 实际拿到的内容）
    print(f"检索注入（预算 {restarted and ''}默认）：")
    for entry in retrieve(restarted):
        print(f"  [{entry.source}/{entry.importance}] {entry.content}")

    # 4. 记忆重置（console /memory/reset 的存储层等价物）
    restarted.clear()
    print(f"重置后条目数：{len(restarted.snapshot().archive) + len(restarted.snapshot().summaries)}（应为 0）")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US1 记忆持久化演示")
    parser.add_argument("--root", default=tempfile.mkdtemp(prefix="aesir-memory-demo-"),
                        help="记忆根目录（默认临时目录，演示完可丢弃）")
    raise SystemExit(main(parser.parse_args().root))
