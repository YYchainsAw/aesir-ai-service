"""`/v1/tactical/executions` 回执端点测试（v0.2 草案 §7）。

验证：合法回执 202 落盘、缺必填字段 422、非法 result 枚举 422、
落盘目录由 AESIR_RECEIPTS_DIR 指向临时路径。
"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _payload(**overrides) -> dict:
    body = {
        "receipt": {
            "order_id": "ord-test-001",
            "result": "executed",
            "reason_code": "",
            "encounter_id": "encounter.20260907.001",
            "agent_id": "companion.alice",
            "ability_id": "ability.alice.explosion",
        }
    }
    body["receipt"].update(overrides)
    return body


def test_receipt_accepted_and_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AESIR_RECEIPTS_DIR", str(tmp_path / "exec"))
    resp = client.post("/v1/tactical/executions", json=_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert body["stored"] is True
    assert body["order_id"] == "ord-test-001"
    assert body["path"].endswith(".jsonl")

    files = list((tmp_path / "exec").glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8"))
    assert record["order_id"] == "ord-test-001"
    assert record["result"] == "executed"
    assert record["received_at"]  # 服务端补齐


def test_receipt_missing_order_id_rejected() -> None:
    resp = client.post("/v1/tactical/executions", json=_payload(order_id=""))
    assert resp.status_code == 422


def test_receipt_invalid_result_rejected() -> None:
    resp = client.post("/v1/tactical/executions", json=_payload(result="exploded"))
    assert resp.status_code == 422


def test_receipt_appends_across_days(tmp_path, monkeypatch) -> None:
    """同一目录追加两条：单文件累积（同一天），内容逐行可解析。"""
    monkeypatch.setenv("AESIR_RECEIPTS_DIR", str(tmp_path / "exec"))
    client.post("/v1/tactical/executions", json=_payload())
    client.post(
        "/v1/tactical/executions",
        json=_payload(order_id="ord-test-002", result="rejected", reason_code="UE_CAST_INTERRUPTED"),
    )
    files = list((tmp_path / "exec").glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["result"] == "rejected"
