"""训练侧轨迹 JSONL 存储（L2，依赖 numpy）。

与回执存储（``app/services/tactical/receipt_store.py``）分离：回执是
UE 真实数据（服务侧），轨迹是模拟器数据（训练侧）。同样按天分文件、
只追加、显式 utf-8。
"""

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TRAJECTORY_DIR = Path("data") / "rl" / "trajectories"


class TrajectoryWriter:
    """逐 tick 追加 {episode, tick, action, reward, done_reason} 记录。"""

    def __init__(self, directory: str | Path | None = None):
        self._dir = Path(directory) if directory is not None else DEFAULT_TRAJECTORY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{datetime.now(timezone.utc):%Y%m%d}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_trajectories(path: str | Path) -> Iterator[dict[str, Any]]:
    """逐行解析；坏行跳过。"""
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
