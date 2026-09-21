"""`/v1/world/events` 幂等与关系防刷测试（SDD T058 / US5 / FR-033、SC-007）。

覆盖：重复上报回放首次结果、跨遭遇同标识独立、**重复上报不重复计分关系**。

最后一条是 US5 与 US2 的接缝：关系计分必须发生在幂等检查**之后**，
否则网络重试会把赠礼、兑现承诺这类事件重复计入关系数值。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.combat_context import make_combat_context
from app.services.relationship.state import get_relationship_store
from app.services.tactical.event_policy import _reset_seen_events

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_event_cache():
    _reset_seen_events()
    yield
    _reset_seen_events()


def _payload(
    event_type: str,
    *,
    event_id: str,
    request_id: str = "req.world.idem.001",
    occurred_at: str = "2026-09-13T12:00:00Z",
    combat: dict | None = None,
) -> dict:
    return {
        "protocol_version": "0.3",
        "request_id": request_id,
        "companion_id": "companion.alice",
        "event": {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "sequence": 1,
            "details": {},
        },
        "world_context": {
            "snapshot_id": "44444444-4444-4444-8444-444444444444",
            "captured_at": occurred_at,
            "scene": "combat" if combat is not None else "exploration",
            "player": {"id": "party.player", "hp_percent": 80},
            "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
            "combat": combat,
        },
    }


def test_duplicate_event_replays_first_result() -> None:
    """FR-033：同一事件重复上报回放首次结果，不产生新行为。"""
    first = client.post("/v1/world/events", json=_payload("gift_given", event_id="event.world.idem.001"))
    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    retry = client.post(
        "/v1/world/events",
        json=_payload("gift_given", event_id="event.world.idem.001", request_id="req.world.idem.002"),
    )
    assert retry.status_code == 200
    body = retry.json()
    assert body["duplicate"] is True
    assert body["request_id"] == "req.world.idem.002"  # 回显本次请求标识
    assert body["reaction"] == first.json()["reaction"]


def test_duplicate_event_does_not_score_relationship_twice() -> None:
    """SC-007：重复上报不重复计分。

    重试刻意用**超出冷却窗口**的 occurred_at——只有幂等缓存能挡住第二次计分，
    排除「冷却窗口恰好挡住」造成的假通过。
    """
    store = get_relationship_store("companion.alice")
    before = store.state().value

    first = client.post("/v1/world/events", json=_payload("gift_given", event_id="event.world.idem.gift.001"))
    assert first.status_code == 200
    after_first = store.state().value
    assert after_first == before + 3  # relationship_policy: gift_given +3

    retry = client.post(
        "/v1/world/events",
        json=_payload(
            "gift_given",
            event_id="event.world.idem.gift.001",
            request_id="req.world.idem.002",
            occurred_at="2026-09-13T13:30:00Z",  # 已远超 60s 冷却窗口
        ),
    )
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert store.state().value == after_first  # 关系数值不再变化


def test_same_event_id_across_encounters_is_independent() -> None:
    """不同 encounter 下的同 event_id 是两次独立事件，不作重放。"""
    first = client.post(
        "/v1/world/events",
        json=_payload(
            "boss_stunned",
            event_id="event.world.enc.001",
            combat=make_combat_context(
                player_hp=60, stunned_remaining=4.0, encounter_id="encounter.test.001"
            ).model_dump(mode="json"),
        ),
    )
    second = client.post(
        "/v1/world/events",
        json=_payload(
            "boss_stunned",
            event_id="event.world.enc.001",
            combat=make_combat_context(
                player_hp=60, stunned_remaining=4.0, encounter_id="encounter.test.002"
            ).model_dump(mode="json"),
        ),
    )
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False
    assert (
        second.json()["companion_action"]["order_id"]
        != first.json()["companion_action"]["order_id"]
    )


def test_combat_and_world_channels_share_idempotency() -> None:
    """同一 event_id 经两个通道上报不得重复产生行为（T061 统一幂等键）。"""
    combat = make_combat_context(player_hp=60, stunned_remaining=4.0)
    world_first = client.post(
        "/v1/world/events",
        json=_payload("boss_stunned", event_id="event.world.shared.001", combat=combat.model_dump(mode="json")),
    )
    assert world_first.status_code == 200
    assert world_first.json()["duplicate"] is False

    combat_retry = client.post(
        "/v1/combat/events",
        json={
            "protocol_version": "0.2",
            "request_id": "req.combat.shared.001",
            "event": {
                "event_id": "event.world.shared.001",
                "event_type": "boss_stunned",
                "occurred_at": "2026-09-13T12:00:00Z",
                "sequence": 1,
            },
            "combat_context": combat.model_dump(mode="json"),
        },
    )
    assert combat_retry.status_code == 200
    assert combat_retry.json()["duplicate"] is True
