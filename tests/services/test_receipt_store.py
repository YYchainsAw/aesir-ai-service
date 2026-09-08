"""`receipt_store` 落盘往返测试：追加/读取、坏行跳过、按天文件名。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.tactical_execution import ExecutionReceipt
from app.services.tactical.receipt_store import append_receipt, read_receipts


def _receipt(order_id: str = "ord-1", result: str = "accepted") -> ExecutionReceipt:
    return ExecutionReceipt(
        order_id=order_id,
        result=result,  # type: ignore[arg-type]
        encounter_id="encounter.test.001",
        reason_code="UE_TARGET_GONE" if result == "rejected" else "",
    )


def test_append_then_read_roundtrip(tmp_path) -> None:
    path = append_receipt(_receipt(), directory=str(tmp_path))
    assert path.exists()
    got = list(read_receipts(path))
    assert len(got) == 1
    assert got[0].order_id == "ord-1"
    assert got[0].result == "accepted"
    assert got[0].received_at  # append 时补齐


def test_bad_lines_skipped(tmp_path) -> None:
    path = append_receipt(_receipt(), directory=str(tmp_path))
    with path.open("a", encoding="utf-8") as f:
        f.write("not-json\n")
        f.write('{"order_id": "ord-x"}\n')  # 缺 result/encounter_id，校验不过
    got = list(read_receipts(path))
    assert [r.order_id for r in got] == ["ord-1"]


def test_day_file_naming(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    path = append_receipt(_receipt(), directory=str(tmp_path))
    assert path.name == f"{now:%Y%m%d}.jsonl"


def test_utf8_chinese_reason_code(tmp_path) -> None:
    receipt = _receipt(result="rejected")
    receipt.reason_code = "玩家目标已消失"
    path = append_receipt(receipt, directory=str(tmp_path))
    raw = path.read_text(encoding="utf-8")
    assert "玩家目标已消失" in raw  # ensure_ascii=False，中文原样写入
    assert list(read_receipts(path))[0].reason_code == "玩家目标已消失"


def test_creates_parent_dirs(tmp_path) -> None:
    deep = tmp_path / "a" / "b" / "c"
    path = append_receipt(_receipt(), directory=str(deep))
    assert isinstance(path, Path) and path.exists()
