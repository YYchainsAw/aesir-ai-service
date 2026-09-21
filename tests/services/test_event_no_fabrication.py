"""世界事件的服务层契约：不虚构动作（FR-025）与关系降级不中断（FR-041）。

与 ``tests/api/test_world_events.py`` 的分工：那里验证 HTTP 契约（状态码、
响应字段），这里直接调 ``handle_world_event`` 验证服务层语义，尤其是
**故障路径**——关系存储不可写时必须照常返回反应，只标记降级原因码。
"""

import pytest

from app.schemas.combat_context import make_combat_context
from app.schemas.world_event import WorldEventRequest
from app.services.relationship.state import RelationshipStoreError
from app.services.tactical.event_policy import _reset_seen_events, handle_world_event

_OCCURRED_AT = "2026-09-13T12:00:00Z"


@pytest.fixture(autouse=True)
def _clean_event_cache():
    _reset_seen_events()
    yield
    _reset_seen_events()


def _request(
    event_type: str,
    *,
    event_id: str = "event.svc.test.001",
    combat: dict | None = None,
) -> WorldEventRequest:
    return WorldEventRequest.model_validate(
        {
            "protocol_version": "0.3",
            "request_id": "req.svc.test.001",
            "companion_id": "companion.alice",
            "event": {
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": _OCCURRED_AT,
                "sequence": 1,
                "details": {},
            },
            "world_context": {
                "snapshot_id": "44444444-4444-4444-8444-444444444444",
                "captured_at": _OCCURRED_AT,
                "scene": "combat" if combat is not None else "exploration",
                "player": {"id": "party.player", "hp_percent": 80},
                "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
                "combat": combat,
            },
        }
    )


# --- 不虚构动作（FR-025） ---------------------------------------------------


def test_combat_event_without_ready_ability_returns_no_action() -> None:
    """爆发技能在冷却：动作留空，反应与建议照常返回。"""
    ctx = make_combat_context(
        player_hp=60,
        stunned_remaining=4.0,
        ability_states={
            "ability.alice.basic_attack": "ready",
            "ability.alice.explosion": "cooldown",
            "ability.alice.quick_heal": "ready",
            "ability.alice.major_heal": "ready",
            "ability.alice.shield": "ready",
        },
    )
    response = handle_world_event(
        _request("boss_stunned", combat=ctx.model_dump(mode="json"))
    )
    assert response.companion_action is None
    assert response.reaction is not None and response.reaction.reply_text
    assert response.recommendation_text


def test_combat_event_without_snapshot_returns_no_action() -> None:
    """快照缺失：不猜动作，但反应与建议仍在（并留下可解释原因码）。"""
    response = handle_world_event(_request("boss_stunned", combat=None))
    assert response.companion_action is None
    assert response.reaction is not None and response.reaction.reply_text
    assert response.recommendation_text
    assert "COMBAT_CONTEXT_MISSING" in response.observability.reason_codes


# --- 关系联动与降级（FR-014 / FR-041） --------------------------------------


def test_relationship_event_scores_and_reports_delta() -> None:
    """赠礼/承诺这类事实事件驱动关系数值，并在可解释字段暴露结果。"""
    response = handle_world_event(_request("promise_kept", event_id="event.svc.rel.001"))
    assert response.observability.relationship_delta == 8  # relationship_policy: promise_kept +8
    assert response.observability.relationship_stage
    assert "RELATIONSHIP_UPDATED" in response.observability.reason_codes


def test_non_relationship_event_leaves_relationship_untouched() -> None:
    """非关系事件（天气/首次进入区域）不触碰关系存储，也不谎报"未变化"。"""
    response = handle_world_event(_request("weather_changed", event_id="event.svc.rel.002"))
    assert response.observability.relationship_delta == 0
    assert response.observability.relationship_stage == ""
    assert "RELATIONSHIP_UNCHANGED" not in response.observability.reason_codes
    assert "RELATIONSHIP_UPDATED" not in response.observability.reason_codes


def test_relationship_store_failure_degrades_without_interrupting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-041：关系目录不可写时事件处理照常返回，仅标记降级原因码。"""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RelationshipStoreError("模拟关系目录不可写")

    monkeypatch.setattr(
        "app.services.tactical.event_policy.get_relationship_store", _boom
    )
    response = handle_world_event(_request("gift_given", event_id="event.svc.rel.003"))

    assert response.reaction is not None and response.reaction.reply_text
    assert response.observability.relationship_delta == 0
    assert "RELATIONSHIP_UNAVAILABLE" in response.observability.reason_codes
