"""一次性清洗：删除印象层里已判为噪声/黑名单的历史主题。

背景：过滤规则升级（停用词、噪声词、黑名单扩充，见 topics.py）只对
**新落**的印象生效——旧数据里已经存在的「不过」「这话」「人机味」「幻视」
这类碎片不会自愈，它们仍占用印象容量、出现在调试视图里。本脚本用
与合并入口同一套判定（``is_blocked_topic`` / ``looks_like_noise``）
扫一遍现有 memory.json，把命中的主题删掉。

用法：
    .venv/Scripts/python -m scripts.prune_noise_impressions --dry-run
    .venv/Scripts/python -m scripts.prune_noise_impressions
    .venv/Scripts/python -m scripts.prune_noise_impressions --root data/memory
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.services.memory.store import MemoryStore
from app.services.memory.topics import is_blocked_topic, looks_like_noise

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def main(root: str, *, dry_run: bool) -> int:
    root_path = Path(root)
    print(f"=== 印象层噪声清洗（根目录：{root_path}）===")

    if not root_path.is_dir():
        print("根目录不存在，无需清洗。")
        return 0

    npc_dirs = sorted(p for p in root_path.iterdir() if (p / "memory.json").is_file())
    if not npc_dirs:
        print("没有发现任何 memory.json，无需清洗。")
        return 0

    total = 0
    for npc_dir in npc_dirs:
        store = MemoryStore(npc_dir.name, root=root)
        store.load()
        impressions = store.snapshot().impressions
        noisy = {
            impression.topic
            for impression in impressions
            if is_blocked_topic(impression.topic) or looks_like_noise(impression.topic)
        }
        if not noisy:
            print(f"[{npc_dir.name}] {len(impressions)} 个印象，无噪声，跳过。")
            continue
        if dry_run:
            print(
                f"[{npc_dir.name}] DRY-RUN：将删除 {len(noisy)}/{len(impressions)} 个噪声印象："
                f"{'、'.join(sorted(noisy))}"
            )
            continue
        removed = store.drop_impressions(noisy)
        total += removed
        print(
            f"[{npc_dir.name}] 删除 {removed} 个噪声印象，"
            f"剩余 {len(store.snapshot().impressions)} 个。"
        )

    print(f"完成：共删除 {total} 个（{'dry-run' if dry_run else '已落盘'}）。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清洗印象层里的噪声/黑名单主题")
    parser.add_argument(
        "--root",
        default=get_settings().memory_root,
        help="记忆根目录（默认取 AESIR_MEMORY_ROOT / data/memory）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只统计不落盘（先预览影响面）"
    )
    args = parser.parse_args()
    raise SystemExit(main(args.root, dry_run=args.dry_run))
