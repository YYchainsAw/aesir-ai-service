"""`POST /v1/world/events` 事件策略测试（SDD T057 / US5 / FR-032~FR-034）。

覆盖四类用例中的三类（重复事件见 ``test_world_events_idempotency.py``）：

- **正常**：六类生活事件各有专属人设反应，不再一律回退骨架默认台词；
- **不可识别**：白名单外的事件类型 422；
- **条件不满足**：战斗类事件缺少战斗快照时不虚构动作（FR-025）。

战斗类事件经世界通道上报时复用既有战斗决策表，产出候选动作；
反应台词仍从 ``combat_event_reactions`` 读取（T061 事件处理统一）。
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.combat_context import make_combat_context
from app.services.tactical.event_policy import _reset_seen_events

client = TestClient(app)

_GOLDEN_DIR = Path(__file__).resolve().parents[2] / "data" / "golden"

# 与 data/personas/aesir/companion.alice/reactions.yaml 的 world_event_reactions 一一对应
_LIFESTYLE_REPLIES = {
    "region_first_entered": "这地方我还没来过……别走太快，我先看看周围。",
    "weather_changed": "天色不太对，等下要是下起来，我们找个地方躲一躲。",
    "gift_given": "给我的？……那我就收下了，谢谢你。",
    "companion_recovered": "呼——总算缓过来了。你也没事吧？",
    "player_protected_companion": "你——你干嘛替我挡啊！让我看看伤到哪儿了！",
    "promise_kept": "你真的做到了……我一直都记着呢，谢谢你。",
}


@pytest.fixture(autouse=True)
def _clean_event_cache():
    """各测试独立：清空事件幂等缓存，避免用例间串扰。"""
    _reset_seen_events()
    yield
    _reset_seen_events()


def _world_payload(
    event_type: str,
    *,
    event_id: str = "event.world.test.001",
    details: dict | None = None,
    combat: dict | None = None,
) -> dict:
    """构造世界事件请求；``combat`` 非空时场景置 combat 并内嵌战斗快照。"""
    return {
        "protocol_version": "0.3",
        "request_id": "req.world.test.001",
        "companion_id": "companion.alice",
        "event": {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": "2026-09-13T12:00:00Z",
            "sequence": 1,
            "details": details or {},
        },
        "world_context": {
            "snapshot_id": "44444444-4444-4444-8444-444444444444",
            "captured_at": "2026-09-13T12:00:00Z",
            "scene": "combat" if combat is not None else "exploration",
            "region": {"region_id": "region.forest.north", "first_visit": True},
            "player": {"id": "party.player", "hp_percent": 80},
            "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
            "combat": combat,
        },
    }


@pytest.mark.parametrize(("event_type", "expected_reply"), sorted(_LIFESTYLE_REPLIES.items()))
def test_lifestyle_event_returns_configured_reaction(event_type: str, expected_reply: str) -> None:
    """六类生活事件各有专属人设反应（来自人设 YAML，非骨架默认回退）。"""
    response = client.post("/v1/world/events", json=_world_payload(event_type))
    assert response.status_code == 200
    body = response.json()
    assert body["reaction"]["reply_text"] == expected_reply
    assert body["duplicate"] is False
    # 事件类型进入可解释原因码，便于按事件归因
    assert event_type.upper() in body["observability"]["reason_codes"]


def test_lifestyle_event_reaction_ids_are_whitelisted() -> None:
    """表现 ID 必须来自人设白名单（FR-002 / 模型输出不可信原则）。"""
    response = client.post("/v1/world/events", json=_world_payload("gift_given"))
    assert response.status_code == 200
    reaction = response.json()["reaction"]
    assert reaction["emotion_id"].startswith("emotion.")
    assert reaction["gesture_id"].startswith("gesture.")
    assert reaction["facial_expression_id"].startswith("face.")


def test_unknown_event_type_returns_422() -> None:
    """白名单外的事件类型按 422 拒绝，不静默回退。"""
    response = client.post("/v1/world/events", json=_world_payload("not_in_whitelist"))
    assert response.status_code == 422


def test_invalid_occurred_at_returns_422() -> None:
    payload = _world_payload("gift_given")
    payload["event"]["occurred_at"] = "not-a-timestamp"
    response = client.post("/v1/world/events", json=payload)
    assert response.status_code == 422


def test_combat_event_via_world_channel_returns_action() -> None:
    """战斗类事件经世界通道上报：复用既有战斗决策表，产出候选动作。"""
    combat = make_combat_context(player_hp=60, stunned_remaining=4.0).model_dump(mode="json")
    response = client.post("/v1/world/events", json=_world_payload("boss_stunned", combat=combat))
    assert response.status_code == 200
    body = response.json()
    action = body["companion_action"]
    assert action is not None
    assert action["ability_id"] == "ability.alice.explosion"
    assert action["authority"] == "event_policy"
    assert action["expires"]["type"] == "before_seconds"
    # 反应来自 combat_event_reactions，与 v0.2 战斗通道同源
    assert body["reaction"]["reply_text"] == "就是现在！它动不了了，我们一起解决它！"


@pytest.mark.parametrize(
    ("filename", "expects_action"),
    [
        ("world_event_region_first_entered.json", False),  # 生活类：无动作可执行
        ("world_event_gift_given.json", False),
        ("world_event_boss_stunned.json", True),          # 战斗类：内嵌快照产出爆发
    ],
)
def test_golden_world_event_samples_are_accepted(filename: str, expects_action: bool) -> None:
    """data/golden 的世界事件样例必须被真实端点接受（防联调 fixture 腐化）。"""
    payload = json.loads((_GOLDEN_DIR / filename).read_text(encoding="utf-8"))
    response = client.post("/v1/world/events", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["reaction"]["reply_text"]
    assert (body["companion_action"] is not None) is expects_action


def test_combat_event_without_snapshot_does_not_fabricate_action() -> None:
    """FR-025：战斗快照缺失时不虚构动作，但仍返回反应与建议。"""
    response = client.post("/v1/world/events", json=_world_payload("boss_stunned", combat=None))
    assert response.status_code == 200
    body = response.json()
    assert body["companion_action"] is None
    assert body["reaction"]["reply_text"]
    assert body["recommendation_text"]
    assert "COMBAT_CONTEXT_MISSING" in body["observability"]["reason_codes"]
