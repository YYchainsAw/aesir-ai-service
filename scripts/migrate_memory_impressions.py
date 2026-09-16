"""一次性迁移：已存的逐字玩家发言 → 模糊印象（主题 × 提及频率）。

背景：对话链路已从「长期逐字存玩家发言」切换为模糊印象层（见
app/services/memory/topics.py）。本脚本把现有 memory.json 短期层中的
逐字发言按规则提取主题、合并进印象层，然后从短期层移除——旧对话的
主题印象无缝延续，原话按设计淡忘。

用法：
    .venv/Scripts/python -m scripts.migrate_memory_impressions
    .venv/Scripts/python -m scripts.migrate_memory_impressions --root data/memory
    .venv/Scripts/python -m scripts.migrate_memory_impressions --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.services.memory.store import MemoryStore

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def main(root: str, *, dry_run: bool) -> int:
    root_path = Path(root)
    print(f"=== 逐字记忆 → 模糊印象迁移（根目录：{root_path}）===")

    npc_dirs = sorted(p for p in root_path.iterdir() if (p / "memory.json").is_file())
    if not npc_dirs:
        print("没有发现任何 memory.json，无需迁移。")
        return 0

    total = 0
    for npc_dir in npc_dirs:
        store = MemoryStore(npc_dir.name, root=root)
        store.load()
        snapshot = store.snapshot()
        verbatim = [
            entry
            for entry in snapshot.short_term
            if entry.source == "player_statement" and "dialogue" in entry.tags
        ]
        if not verbatim:
            print(f"[{npc_dir.name}] 无逐字对话记忆，跳过。")
            continue
        if dry_run:
            print(f"[{npc_dir.name}] DRY-RUN：将迁移 {len(verbatim)} 条逐字发言。")
            continue
        migrated = store.migrate_verbatim_to_impressions()
        total += migrated
        print(
            f"[{npc_dir.name}] 迁移 {migrated} 条逐字发言 → "
            f"{len(store.snapshot().impressions)} 个主题印象。"
        )

    print(f"完成：共迁移 {total} 条（{'dry-run' if dry_run else '已落盘'}）。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="逐字记忆迁移为模糊印象")
    parser.add_argument(
        "--root",
        default=get_settings().memory_root,
        help="记忆根目录（默认取 AESIR_MEMORY_ROOT / data/memory）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只统计不落盘（先预览影响面）"
    )
    raise SystemExit(main(parser.parse_args().root, dry_run=parser.parse_args().dry_run))
