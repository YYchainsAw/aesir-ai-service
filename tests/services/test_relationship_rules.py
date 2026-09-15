"""关系事件增减与防刷测试（SDD T033 / FR-014、FR-017）。"""

from __future__ import annotations

import pytest

from app.schemas.relationship import RelationshipState
from app.services.relationship.rules import apply_relationship_event

T0 = "2026-09-14T10:00:00Z"


def _state(value: int = 20) -> RelationshipState:
    return RelationshipState(value=value, day="2026-09-14", daily_net=0)


def test_registered_event_applies_delta() -> None:
    """已登记事件按策略表增减（promise_kept +8）。"""
    state, delta = apply_relationship_event(_state(), "promise_kept", T0)
    assert delta == 8
    assert state.value == 28


def test_negative_event_applies_delta() -> None:
    state, delta = apply_relationship_event(_state(50), "promise_broken", T0)
    assert delta == -8
    assert state.value == 42


def test_unknown_event_ignored() -> None:
    """未登记事件一律忽略：数值不变、不计入当日净变化。"""
    state, delta = apply_relationship_event(_state(), "totally_unknown_event", T0)
    assert delta == 0
    assert state.value == 20
    assert state.daily_net == 0


def test_cooldown_window_dedup() -> None:
    """冷却窗口内同类型重复事件不计分（防刷）。"""
    state = _state()
    state, delta = apply_relationship_event(state, "gift_given", T0)
    assert delta == 3
    # 30 秒后（窗口 60s 内）重复 → 不计分
    state, delta = apply_relationship_event(state, "gift_given", "2026-09-14T10:00:30Z")
    assert delta == 0
    assert state.value == 23
    # 61 秒后 → 正常计分
    state, delta = apply_relationship_event(state, "gift_given", "2026-09-14T10:01:01Z")
    assert delta == 3
    assert state.value == 26


def test_cooldown_independent_per_event_type() -> None:
    """冷却按事件类型独立：窗口内不同类型事件各自计分。"""
    state = _state()
    state, _ = apply_relationship_event(state, "gift_given", T0)
    state, delta = apply_relationship_event(state, "companion_recovered", T0)
    assert delta == 2


def test_daily_positive_cap() -> None:
    """每日正向净变化上限（15）：超限部分不计，负向不受正向上限约束。"""
    state = _state()
    # promise_kept(+8) ×2 = +16，第二笔只允许 +7
    state, d1 = apply_relationship_event(state, "promise_kept", "2026-09-14T10:00:00Z")
    state, d2 = apply_relationship_event(state, "promise_kept", "2026-09-14T11:00:00Z")
    assert d1 == 8 and d2 == 7
    assert state.value == 35
    assert state.daily_net == 15
    # 当日再刷正事件 → 全部不计
    state, d3 = apply_relationship_event(state, "gift_given", "2026-09-14T12:00:00Z")
    assert d3 == 0
    # 负事件不受正向上限影响
    state, d4 = apply_relationship_event(state, "companion_downed", "2026-09-14T13:00:00Z")
    assert d4 == -5


def test_daily_counter_resets_next_day() -> None:
    """跨日重置当日净变化窗口。"""
    state = _state()
    state, _ = apply_relationship_event(state, "promise_kept", "2026-09-14T10:00:00Z")
    state, _ = apply_relationship_event(state, "promise_kept", "2026-09-14T11:00:00Z")
    assert state.daily_net == 15
    # 次日：正向额度重新可用
    state, delta = apply_relationship_event(state, "promise_kept", "2026-09-15T10:00:00Z")
    assert delta == 8
    assert state.daily_net == 8


def test_recent_events_recorded() -> None:
    """近期事件留痕（可解释，FR-012 同思路）。"""
    state, _ = apply_relationship_event(_state(), "gift_given", T0)
    assert state.recent_events
    assert state.recent_events[-1].event_type == "gift_given"
    assert state.recent_events[-1].delta == 3
