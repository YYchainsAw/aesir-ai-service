"""`POST /v1/combat/events` 端点与事件策略测试（v0.2 草案 §6）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.combat_context import make_combat_context
from app.schemas.combat_event import CombatEvent, CombatEventRequest
from app.services.tactical.event_policy import _reset_seen_events

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_event_cache():
    """各测试独立：清空事件幂等缓存，避免用例间串扰。"""
    _reset_seen_events()
    yield
    _reset_seen_events()


def _request(event_type: str, *, context=None, event_id="event.encounter.001.test.001") -> dict:
    return CombatEventRequest(
        request_id="779a1aa2-6358-4641-8393-e8c20e5e827d",
        event=CombatEvent(
            event_id=event_id,
            event_type=event_type,
            occurred_at="2026-09-03T12:00:00Z",
            sequence=1,
        ),
        combat_context=context or make_combat_context(player_hp=60),
    ).model_dump()


def test_boss_stunned_returns_reaction_recommendation_and_burst_action() -> None:
    response = client.post(
        "/v1/combat/events",
        json=_request(
            "boss_stunned",
            context=make_combat_context(player_hp=60, stunned_remaining=4.0),
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["protocol_version"] == "0.2"
    assert body["source"] == "rule"
    assert body["event_id"] == "event.encounter.001.test.001"
    # 人设反应来自 YAML（情绪 ID 在白名单内）
    reaction = body["reaction"]
    assert reaction["reply_text"] == "就是现在！它动不了了，我们一起解决它！"
    assert reaction["emotion_id"] == "emotion.excited"
    assert reaction["gesture_id"] == "gesture.enthusiastic_nod"
    assert reaction["interruptible"] is True
    # 建议：集火
    assert body["recommendation"]["type"] == "focus_fire"
    assert body["recommendation"]["target_id"] == "encounter.primary_hostile"
    assert "BOSS_STUNNED" in body["recommendation"]["reason_codes"]
    # 动作候选：爆裂魔法，过期时间绑定眩晕剩余秒数
    action = body["companion_action"]
    assert action["ability_id"] == "ability.alice.explosion"
    assert action["authority"] == "event_policy"
    assert action["priority"] == 85
    assert action["expires"]["type"] == "before_seconds"
    assert action["expires"]["remaining_seconds"] == 4.0
    assert body["observability"]["used_snapshot_id"]


def test_boss_stunned_without_explosion_ready_returns_null_action() -> None:
    context = make_combat_context(
        player_hp=60,
        stunned_remaining=3.0,
        ability_states={
            "ability.alice.basic_attack": "ready",
            "ability.alice.explosion": "cooldown",
            "ability.alice.quick_heal": "ready",
            "ability.alice.major_heal": "ready",
            "ability.alice.shield": "ready",
        },
    )
    response = client.post("/v1/combat/events", json=_request("boss_stunned", context=context))
    assert response.status_code == 200
    body = response.json()
    # 反应与建议照常返回，但不得虚构可施放动作
    assert body["companion_action"] is None
    assert "EXPLOSION_NOT_READY" in body["recommendation"]["reason_codes"]
    assert body["reaction"]["reply_text"]


def test_player_hp_critical_prefers_major_heal() -> None:
    response = client.post(
        "/v1/combat/events", json=_request("player_hp_critical", context=make_combat_context(player_hp=15))
    )
    assert response.status_code == 200
    body = response.json()
    action = body["companion_action"]
    assert action["ability_id"] == "ability.alice.major_heal"
    assert action["target_id"] == "party.player"
    assert action["authority"] == "event_policy"
    assert "PLAYER_HP_CRITICAL" in body["recommendation"]["reason_codes"]


def test_boss_enraged_casts_shield_when_ready() -> None:
    response = client.post(
        "/v1/combat/events", json=_request("boss_enraged", context=make_combat_context(player_hp=55))
    )
    assert response.status_code == 200
    body = response.json()
    assert body["companion_action"]["ability_id"] == "ability.alice.shield"
    assert body["recommendation"]["type"] == "retreat_or_defend"


def test_boss_stun_near_and_mp_low_return_null_action() -> None:
    for event_type in ("boss_stun_near", "companion_mp_low"):
        response = client.post("/v1/combat/events", json=_request(event_type))
        assert response.status_code == 200
        body = response.json()
        assert body["companion_action"] is None
        assert body["recommendation"] is not None
        assert body["reaction"]["reply_text"]


def test_boss_defeated_returns_reaction_without_recommendation() -> None:
    response = client.post("/v1/combat/events", json=_request("boss_defeated"))
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"] is None
    assert body["companion_action"] is None
    assert "赢了" in body["reaction"]["reply_text"]


def test_unknown_event_type_rejected_with_422() -> None:
    payload = _request("boss_stunned")
    payload["event"]["event_type"] = "player_buffed"
    response = client.post("/v1/combat/events", json=payload)
    assert response.status_code == 422


def test_duplicate_event_id_replays_first_response() -> None:
    """策划书 §4.2：网络重试复用同一 event_id，服务端幂等回放。"""
    context = make_combat_context(player_hp=60, stunned_remaining=4.0)
    first = client.post("/v1/combat/events", json=_request("boss_stunned", context=context))
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["duplicate"] is False

    retry = client.post("/v1/combat/events", json=_request("boss_stunned", context=context))
    assert retry.status_code == 200
    retry_body = retry.json()
    # 回放标记：同一 order_id / 台词，不重复下发新动作
    assert retry_body["duplicate"] is True
    assert retry_body["companion_action"]["order_id"] == first_body["companion_action"]["order_id"]
    assert retry_body["reaction"]["reply_text"] == first_body["reaction"]["reply_text"]


def test_duplicate_event_id_across_encounters_is_independent() -> None:
    """不同 encounter_id 的同 event_id 是两次独立事件，不作重放。"""
    first = client.post(
        "/v1/combat/events",
        json=_request("boss_stunned", context=make_combat_context(player_hp=60, stunned_remaining=4.0)),
    )
    second = client.post(
        "/v1/combat/events",
        json=_request(
            "boss_stunned",
            context=make_combat_context(
                player_hp=60, stunned_remaining=4.0, encounter_id="encounter.test.002"
            ),
        ),
    )
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False
    assert (
        second.json()["companion_action"]["order_id"]
        != first.json()["companion_action"]["order_id"]
    )
