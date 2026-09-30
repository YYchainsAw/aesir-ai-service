"""`POST /v1/agent/step` 主入口契约测试（SDD T019 + T054 自主行为编排）。

覆盖四类用例（章程原则 IV）：正常心跳（自主行为产出指令）、缺字段 422、
未登记角色 404、心跳过频 429；另覆盖禁打断静止、节流静止与文本指令路径
（T075：战斗/非战斗意图按域路由，与 /v1/tactical 共用同一决策层）。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1 import agent as agent_module
from app.api.v1.agent import _reset_heartbeat_tracker
from app.services.agency.throttle import reset_throttle

client = TestClient(app)

_REQUEST_ID = "0f9f4b62-6f37-4d0f-9bb5-2be97a4d0f27"


@pytest.fixture(autouse=True)
def _clean_state():
    """各测试独立：清空心跳限流与自主行为节流状态，避免用例间串扰。"""
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
            "snapshot_id": "22222222-2222-4222-8222-222222222222",
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


def _bypass_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳过心跳限流（节流用例需要连续两次心跳）。"""
    monkeypatch.setattr(agent_module, "_heartbeat_too_soon", lambda *_args, **_kwargs: False)


def test_heartbeat_emits_autonomous_directive() -> None:
    """T054：探索场景 + notable 篝火 → 自主行为产出指令（US3 核心路径）。"""
    response = client.post("/v1/agent/step", json=_step_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == _REQUEST_ID
    assert body["companion_id"] == "companion.alice"
    assert body["action"] == "directive"
    # US7（T076）链路信息：人设版本；心跳路径不消费记忆（memory_layers 为空字典）
    assert body["observability"]["persona_revision"] != ""
    assert body["observability"]["memory_layers"] == {}
    directive = body["directive"]
    assert directive["agent_id"] == "companion.alice"
    assert directive["domain"] == "exploration"
    assert directive["source"] == "autonomy"
    assert directive["action_type"] == "inspect"
    assert directive["presentation"]["gaze_target_id"] == "object.campfire.001"
    assert directive["policy_revision"]
    observability = body["observability"]
    assert observability["source"] == "rule"
    assert observability["used_snapshot_id"] == "22222222-2222-4222-8222-222222222222"
    assert any(code.startswith("ARB_WON:") for code in observability["reason_codes"])


def test_heartbeat_no_candidates_returns_none_action() -> None:
    """战斗场景心跳：无生活类候选 → 空动作 + NO_AUTONOMOUS_CANDIDATE。"""
    payload = _step_payload()
    payload["world_context"]["scene"] = "combat"
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert body["directive"] is None
    assert "NO_AUTONOMOUS_CANDIDATE" in body["observability"]["reason_codes"]


def test_heartbeat_no_interrupt_returns_none_action() -> None:
    """禁打断（剧情演出）→ 静止观察，不发起自主行为（FR-023）。"""
    payload = _step_payload()
    payload["world_context"]["cutscene_playing"] = True
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert "INTERRUPT_FORBIDDEN:cutscene_playing" in body["observability"]["reason_codes"]


def test_repeated_trigger_throttled_to_none_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一触发源短期重复 → 节流为静止 + THROTTLED（FR-022 去重）。"""
    _bypass_heartbeat(monkeypatch)
    first = client.post("/v1/agent/step", json=_step_payload())
    assert first.status_code == 200
    assert first.json()["action"] == "directive"
    second = client.post("/v1/agent/step", json=_step_payload())
    assert second.status_code == 200
    body = second.json()
    assert body["action"] == "none"
    assert "THROTTLED" in body["observability"]["reason_codes"]
    assert "DEDUP_WINDOW" in body["observability"]["reason_codes"]


def test_text_command_without_combat_context_reports_missing() -> None:
    """战斗意图但快照未携带战斗上下文：空动作 + COMBAT_CONTEXT_MISSING，不虚构战况。"""
    response = client.post("/v1/agent/step", json=_step_payload(text="艾莉，帮我回一下血"))
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert "COMBAT_CONTEXT_MISSING" in body["observability"]["reason_codes"]


def test_text_command_unrecognized_replies_clarification() -> None:
    """不可识别文本：回复澄清 + INTENT_UNRECOGNIZED，不猜测执行（FR-028）。"""
    response = client.post("/v1/agent/step", json=_step_payload(text="艾莉，今天天气不错啊"))
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert "INTENT_UNRECOGNIZED" in body["observability"]["reason_codes"]
    assert body["reply_text"]


def test_text_command_non_combat_maps_to_agency_behavior() -> None:
    """T075：非战斗意图（查看篝火）→ agency 行为目录指令（快照内目标）。"""
    response = client.post("/v1/agent/step", json=_step_payload(text="艾莉，看看那个篝火"))
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "directive"
    directive = body["directive"]
    assert directive["domain"] == "exploration"
    assert directive["action_type"] == "inspect"
    assert directive["source"] == "player_command"
    assert directive["payload"]["target_id"] == "object.campfire.001"
    assert body["observability"]["source"] == "rule"
    assert "INTENT:inspect_interactable" in body["observability"]["reason_codes"]


def test_text_command_rest_in_combat_scene_not_actionable() -> None:
    """T075：战斗场景下「休息」不在行为目录域内 → 空动作 + BEHAVIOR_NOT_IN_SCENE。"""
    payload = _step_payload(text="艾莉，休息一下")
    payload["world_context"]["scene"] = "combat"
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert "BEHAVIOR_NOT_IN_SCENE" in body["observability"]["reason_codes"]


def test_text_command_combat_intent_resolves_via_shared_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T075：战斗意图复用 /v1/tactical 同一决策层（resolve_intent + 关系调制）。

    低蓝 + 护盾就绪 + 亲密阶段：devoted 调制重建护盾动作（US2/FR-016）。
    """
    monkeypatch.setattr(agent_module, "_relationship_stage_or_empty", lambda _cid: "close")
    payload = _step_payload(text="艾莉，给我开个护盾")
    payload["world_context"]["scene"] = "combat"
    payload["world_context"]["combat"] = {
        "snapshot_id": "22222222-2222-4222-8222-222222222222",
        "captured_at": "2026-09-13T12:00:00Z",
        "encounter_id": "encounter.demo.001",
        "mode": "combat",
        "player": {"id": "party.player", "hp_percent": 80, "distance_to_boss_m": 12.0},
        "companion": {
            "id": "companion.alice",
            "hp_percent": 90,
            "mp_percent": 5,
            "ability_states": {"ability.alice.shield": "ready"},
        },
        "boss": {"id": "encounter.primary_hostile", "hp_percent": 100, "state_tags": []},
    }
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    # 低蓝：基础决策 not_actionable → 亲密 devoted 调制重建护盾（关系原因码可解释）
    assert "RELATIONSHIP_CLOSE_DEVOTED" in body["observability"]["reason_codes"]
    assert body["action"] == "directive"
    assert body["directive"]["action_type"] == "shield"
    assert body["directive"]["source"] == "player_command"


def test_missing_required_field_returns_422() -> None:
    payload = _step_payload()
    del payload["world_context"]
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 422


def test_invalid_world_context_returns_422() -> None:
    """非法快照（时间非 ISO-8601）按 422 拒绝。"""
    payload = _step_payload()
    payload["world_context"]["captured_at"] = "not-a-timestamp"
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 422


def test_unregistered_companion_returns_404_without_fallback() -> None:
    """FR-044：未登记角色明确拒绝，不回退默认角色人格。"""
    response = client.post("/v1/agent/step", json=_step_payload(companion_id="companion.unknown"))
    assert response.status_code == 404


def test_heartbeat_too_frequent_returns_429() -> None:
    first = client.post("/v1/agent/step", json=_step_payload())
    assert first.status_code == 200
    second = client.post("/v1/agent/step", json=_step_payload())
    assert second.status_code == 429


def test_text_commands_are_not_throttled() -> None:
    """文本指令不受心跳限流约束（限流仅针对无产出的心跳，FR-022）。"""
    assert client.post("/v1/agent/step", json=_step_payload(text="艾莉，跟上")).status_code == 200
    assert client.post("/v1/agent/step", json=_step_payload(text="艾莉，等等我")).status_code == 200


def test_autonomous_directive_expires_come_from_policy() -> None:
    """CODE-03：自主行为指令的 expires 从 agency_policy.yaml 读取，不再硬编码。"""
    response = client.post("/v1/agent/step", json=_step_payload())
    assert response.status_code == 200
    directive = response.json()["directive"]
    assert directive["expires"]["type"] == "before_seconds"
    assert directive["expires"]["remaining_seconds"] == 10.0


def test_combat_directive_has_expires_from_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CODE-07：战斗指令统一携带来自策略的 expires。"""
    monkeypatch.setattr(agent_module, "_relationship_stage_or_empty", lambda _cid: "close")
    payload = _step_payload(text="艾莉，给我开个护盾")
    payload["world_context"]["scene"] = "combat"
    payload["world_context"]["combat"] = {
        "snapshot_id": "22222222-2222-4222-8222-222222222222",
        "captured_at": "2026-09-13T12:00:00Z",
        "encounter_id": "encounter.demo.001",
        "mode": "combat",
        "player": {"id": "party.player", "hp_percent": 80, "distance_to_boss_m": 12.0},
        "companion": {
            "id": "companion.alice",
            "hp_percent": 90,
            "mp_percent": 5,
            "ability_states": {"ability.alice.shield": "ready"},
        },
        "boss": {"id": "encounter.primary_hostile", "hp_percent": 100, "state_tags": []},
    }
    response = client.post("/v1/agent/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "directive"
    directive = body["directive"]
    assert directive["domain"] == "combat"
    assert directive["expires"]["type"] == "before_seconds"
    assert directive["expires"]["remaining_seconds"] == 10.0


def test_unmapped_non_combat_intent_returns_empty_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CODE-04：非战斗意图若不在行为映射表中，不得 KeyError/500，须降级为空动作。"""
    monkeypatch.setattr(agent_module, "_NON_COMBAT_BEHAVIOR", {})
    response = client.post("/v1/agent/step", json=_step_payload(text="艾莉，看看那个篝火"))
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "none"
    assert "BEHAVIOR_UNMAPPED" in body["observability"]["reason_codes"]
