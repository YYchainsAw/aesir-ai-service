"""事件幂等埋点测试（T38：SC-007 数据源）。

覆盖：单元落盘字段、world 通道重放写两条记录（第二条 duplicate=True）、
故障静默。聚合侧的一致性判定（非首条 duplicate=False → FAIL）见
tests/scripts/test_metrics_report.py 的 collect_event_signals 用例。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.tactical.event_policy import _reset_seen_events
from app.services.tactical.event_signals import record_event_resolved

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_event_cache():
    _reset_seen_events()
    yield
    _reset_seen_events()


def test_record_writes_full_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_EVENT_SIGNALS_DIR", str(tmp_path))
    record_event_resolved(
        "companion.alice",
        game_id="aesir",
        channel="world",
        event_type="gift_given",
        event_id="event.test.001",
        duplicate=False,
    )
    record = json.loads(
        (tmp_path / "aesir" / "companion.alice.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["event_type"] == "gift_given"
    assert record["event_id"] == "event.test.001"
    assert record["duplicate"] is False
    assert record["channel"] == "world"


def test_failure_is_silent(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_EVENT_SIGNALS_DIR", str(tmp_path / "bad<>|dir"))
    record_event_resolved("companion.alice", event_id="event.test.001")


def _payload(event_id: str, request_id: str) -> dict:
    return {
        "protocol_version": "0.3",
        "request_id": request_id,
        "companion_id": "companion.alice",
        "event": {
            "event_id": event_id,
            "event_type": "gift_given",
            "occurred_at": "2026-09-13T12:00:00Z",
            "sequence": 1,
            "details": {},
        },
        "world_context": {
            "snapshot_id": "55555555-5555-4555-8555-555555555555",
            "captured_at": "2026-09-13T12:00:00Z",
            "scene": "exploration",
            "player": {"id": "party.player", "hp_percent": 80},
            "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
        },
    }


def test_replay_writes_two_records_with_duplicate_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_EVENT_SIGNALS_DIR", str(tmp_path))
    first = client.post("/v1/world/events", json=_payload("event.sig.001", "req.sig.001"))
    assert first.status_code == 200
    retry = client.post("/v1/world/events", json=_payload("event.sig.001", "req.sig.002"))
    assert retry.status_code == 200

    lines = (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first_record, second_record = json.loads(lines[0]), json.loads(lines[1])
    assert first_record["duplicate"] is False
    assert second_record["duplicate"] is True
    assert first_record["event_id"] == second_record["event_id"] == "event.sig.001"
    assert first_record["channel"] == "world"
