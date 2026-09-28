"""executions 回执的 JSONL 落盘（v0.2 草案 §7）。

按天分文件（``{目录}/{YYYYMMDD}.jsonl``）且只追加：避免多进程写冲突，
也便于 UE 联调后按天清档。所有写入显式 utf-8（Windows 默认 GBK 会炸
中文 reason_code）。
"""

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.tactical_execution import ExecutionReceipt


def _day_file(directory: str | Path, day: datetime) -> Path:
    return Path(directory) / f"{day:%Y%m%d}.jsonl"


def append_receipt(receipt: ExecutionReceipt, *, directory: str | None = None) -> Path:
    """追加一条回执并返回写入的文件路径。父目录不存在时自动创建。"""
    return append_receipts([receipt], directory=directory)


def append_receipts(receipts: list[ExecutionReceipt], *, directory: str | None = None) -> Path:
    """批量追加回执并返回写入的文件路径。

    一次性打开当天 JSONL 文件，循环写入全部回执，减少 I/O 次数。
    同一批次使用统一的 UTC 时间补齐 ``received_at``。
    """
    from app.config import get_settings

    if not receipts:
        raise ValueError("receipts 不能为空列表")

    target_dir = Path(directory) if directory is not None else Path(get_settings().receipts_dir)
    now = datetime.now(timezone.utc)
    path = _day_file(target_dir, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for receipt in receipts:
            record = receipt.model_dump()
            if not record["received_at"]:
                record["received_at"] = now.isoformat()
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_receipts(path: str | Path) -> Iterator[ExecutionReceipt]:
    """逐行解析回执；坏行（非 JSON / 字段非法）跳过，供分析与测试用。"""
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield ExecutionReceipt.model_validate_json(line)
            except ValueError:
                continue
