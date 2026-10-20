"""agent/step 决策埋点的 API 级挂载测试（T38）。

验证 POST /v1/agent/step 主汇合点把响应（observability + directive）落盘成
agent_steps JSONL——SC-005（行为类型分布）/ SC-006（相邻重复率）/
SC-013（reason_codes 覆盖率）三项验收的真实数据源。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1 import agent as agent_module
from app.api.v1.agent import _reset_heartbeat_tracker
from app.services.agency.throttle import reset_throttle

client = TestClient(app)

_REQUEST_ID = "1f9f4b62-6f37-4d0f-9bb5-2be97a4d0f27"


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_heartbeat_tracker()
    reset_throttle()
    yield
    _reset_heartbeat_tracker()
    reset_throttle()


def _step_payload(**overrides) -> dict:
    payload = {
        "protocol_version": "0.3",
        "request_id": _REQUEST_ID,
        "companion_id": "companion.alice",
        "world_context": {
            "snapshot_id": "33333333-3333-4333-8333-333333333333",
            "captured_at": "2026-09-13T12:00:00Z",
            "scene": "exploration",
            "player": {"id": "party.player", "hp_percent": 80},
            "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
            "interactables": [
                {"object_id": "object.campfire.001", "kind": "prop", "distance_m": 3.5, "notable": True}
            ],
        },
    }
    payload.update(overrides)
    return payload


def _last_record(tmp_path) -> dict:
    lines = (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_autonomous_heartbeat_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path))
    response = client.post("/v1/agent/step", json=_step_payload())
    assert response.status_code == 200
    record = _last_record(tmp_path)
    assert record["companion_id"] == "companion.alice"
    assert record["scene"] == "exploration"
    assert record["action"] == "directive"
    assert record["directive_action_type"] == "inspect"
    # SC-013 核心断言：每一步都带非空 reason_codes（可解释覆盖）。
    assert record["reason_codes"], "自主步必须携带 reason_codes"
    assert any(code.startswith("ARB_WON:") for code in record["reason_codes"])


def test_empty_step_is_recorded_with_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path))
    payload = _step_payload()
    payload["world_context"]["scene"] = "combat"
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    record = _last_record(tmp_path)
    assert record["action"] == "none"
    assert record["directive_action_type"] is None
    assert "NO_AUTONOMOUS_CANDIDATE" in record["reason_codes"]


def test_text_command_step_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path))
    payload = _step_payload(text="艾莉，跟我走")
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    record = _last_record(tmp_path)
    assert record["companion_id"] == "companion.alice"
    # 文本步也必须落盘且可解释（汇合点覆盖所有分支）。
    assert isinstance(record["reason_codes"], list)
