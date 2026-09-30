"""`receipt_store` 落盘往返测试：追加/读取、坏行跳过、按天文件名。"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schemas.tactical_execution import ExecutionReceipt
from app.services.tactical.receipt_store import append_receipt, append_receipts, read_receipts


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


def test_append_receipts_multiple_records(tmp_path) -> None:
    receipts = [_receipt(order_id=f"ord-{i}") for i in range(3)]
    path = append_receipts(receipts, directory=str(tmp_path))
    got = list(read_receipts(path))
    assert len(got) == 3
    assert [r.order_id for r in got] == ["ord-0", "ord-1", "ord-2"]
    assert all(r.received_at for r in got)


def test_append_receipts_then_single_mixed(tmp_path) -> None:
    batch = [_receipt(order_id="ord-batch")]
    path1 = append_receipts(batch, directory=str(tmp_path))
    path2 = append_receipt(_receipt(order_id="ord-single"), directory=str(tmp_path))
    assert path1 == path2
    got = list(read_receipts(path1))
    assert [r.order_id for r in got] == ["ord-batch", "ord-single"]


def test_append_receipts_empty_list_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="不能为空列表"):
        append_receipts([], directory=str(tmp_path))


def test_game_id_partitions_receipt_files(monkeypatch, tmp_path) -> None:
    """不同 game_id 的回执写入不同子目录（S1）。"""
    monkeypatch.setenv("AESIR_RECEIPTS_DIR", str(tmp_path))
    path1 = append_receipt(_receipt(order_id="ord-aesir"), game_id="aesir")
    path2 = append_receipt(_receipt(order_id="ord-other"), game_id="other")
    assert path1.parent.name == "aesir"
    assert path2.parent.name == "other"
    assert list(read_receipts(path1))[0].order_id == "ord-aesir"
    assert list(read_receipts(path2))[0].order_id == "ord-other"
