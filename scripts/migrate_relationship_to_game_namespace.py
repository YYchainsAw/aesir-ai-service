#!/usr/bin/env python3
"""迁移关系目录：从旧的 ``data/relationship/<npc_id>`` 到 ``data/relationship/<game_id>/<npc_id>``。

B-01/S1 路径改造后，旧数据不会自动出现在新路径下。本脚本在仓库根目录运行，
把 ``data/relationship`` 下直接以 npc_id 命名的子目录移动到 ``data/relationship/aesir/``
命名空间下；已在新路径下的目录跳过，避免重复迁移。

用法（项目根目录）：
    .venv/Scripts/python.exe scripts/migrate_relationship_to_game_namespace.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def migrate(*, relationship_root: Path | None = None, game_id: str = "aesir") -> int:
    """执行迁移，返回迁移的目录数。"""
    root = relationship_root or Path(__file__).resolve().parents[1] / "data" / "relationship"
    if not root.exists():
        print(f"关系根目录不存在：{root}")
        return 0

    target_root = root / game_id
    target_root.mkdir(parents=True, exist_ok=True)

    moved = 0
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        if path.name == game_id:
            # 已经是命名空间目录
            continue
        target = target_root / path.name
        if target.exists():
            print(f"跳过：目标目录已存在 {target}")
            continue
        shutil.move(str(path), str(target))
        print(f"已迁移：{path} -> {target}")
        moved += 1

    return moved


if __name__ == "__main__":
    count = migrate()
    print(f"共迁移 {count} 个角色目录到 game_id='aesir' 命名空间下。")
    sys.exit(0)
