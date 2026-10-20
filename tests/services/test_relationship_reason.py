"""关系层拦截原因透传测试（T38 / SC-004 数据源）。

覆盖：``apply_relationship_event_ex`` 四种「delta=0」可区分、旧两元组签名不变、
``RelationshipStore.apply_event`` 三元组透传、对话信号落盘 ``relationship_reason``。
"""

from __future__ import annotations

import json

from app.schemas.relationship import RelationshipState
from app.services.relationship.rules import (
    apply_relationship_event,
    apply_relationship_event_ex,
)
from app.services.relationship.state import RelationshipStore

T0 = "2026-09-14T10:00:00Z"


def _state(value: int = 20, *, day: str = "2026-09-14", daily_net: int = 0) -> RelationshipState:
    return RelationshipState(value=value, day=day, daily_net=daily_net)


def test_registered_event_reason_is_scored():
    state, delta, reason = apply_relationship_event_ex(_state(), "promise_kept", T0)
    assert delta == 8
    assert reason == "scored"


def test_unknown_event_reason_is_distinguished():
    new_state, delta, reason = apply_relationship_event_ex(_state(), "totally_unknown_event", T0)
    assert delta == 0
    assert reason == "unknown_event"
    assert new_state.value == 20


def test_cooldown_blocked_reason():
    """冷却窗口拦截是独立原因（SC-004 的核心观测对象）。"""
    state = _state()
    state, _delta, _reason = apply_relationship_event_ex(state, "gift_given", T0)
    state, delta, reason = apply_relationship_event_ex(
        state, "gift_given", "2026-09-14T10:00:30Z"
    )
    assert delta == 0
    assert reason == "cooldown_blocked"


def test_daily_cap_reason():
    """当日正向上限耗尽是独立原因。"""
    # daily_cap 默认 15：gift_given +3 × 5 次（跨冷却）= 15，第六次被日上限吃掉。
    state = _state()
    for i in range(5):
        state, _delta, _reason = apply_relationship_event_ex(
            state, "gift_given", f"2026-09-14T{10 + i:02d}:00:00Z"
        )
    assert state.daily_net == 15
    state, delta, reason = apply_relationship_event_ex(state, "gift_given", "2026-09-14T15:00:00Z")
    assert delta == 0
    assert reason == "daily_cap"


def test_clamped_zero_reason():
    """已在阶段上限：钳制吃掉全部变化。"""
    # value 在 policy.max 边界附近（默认 max 见策略表；用 promise_kept +8 顶到上限）。
    from app.services.relationship.policy import get_policy

    policy = get_policy()
    state = _state(policy.max)
    _new_state, delta, reason = apply_relationship_event_ex(state, "promise_kept", T0)
    assert delta == 0
    assert reason == "clamped_zero"


def test_legacy_two_tuple_signature_unchanged():
    """旧签名保持两元组（既有测试/demo 零破坏）。"""
    result = apply_relationship_event(_state(), "gift_given", T0)
    assert len(result) == 2
    _new_state, delta = result
    assert delta == 3


def test_store_apply_event_returns_reason(tmp_path):
    store = RelationshipStore("companion.alice", root=str(tmp_path))
    store.load()
    _state, delta, reason = store.apply_event("gift_given")
    assert delta == 3
    assert reason == "scored"
    # 冷却内再发 → cooldown_blocked（用更短的对话冷却窗口强制拦截）。
    _state, delta, reason = store.apply_event(
        "gift_given", cooldown_seconds=10_000
    )
    assert delta == 0
    assert reason == "cooldown_blocked"


def test_mock_chat_turn_records_no_signal_reason(monkeypatch, tmp_path):
    """mock 路径无情感信号 → relationship_reason=no_signal 落盘（绝不缺键报错）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(tmp_path))
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")
    client = TestClient(app)
    response = client.post(
        "/v1/companion/chat",
        json={
            "text": "钓鱼吗",
            "companion_id": "companion.alice",
            "game_state": "conversation",
            "session_id": "reason-1",
        },
    )
    assert response.status_code == 200
    record = json.loads(
        (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert record["relationship_reason"] == "no_signal"
    assert record["relationship_delta"] == 0
