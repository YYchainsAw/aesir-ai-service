"""跨域仲裁测试（SDD T046 / FR-024）。六级优先级：
危险自保 > 战斗战术 > 玩家指令 > 剧情事件 > 关系事件 > 日常自主。"""

from __future__ import annotations

from app.services.agency.arbiter import arbitrate
from app.services.agency.behavior_catalog import BehaviorCandidate


def _candidate(
    behavior: str,
    category: str,
    priority: int = 20,
    target_id: str | None = None,
) -> BehaviorCandidate:
    return BehaviorCandidate(
        behavior=behavior,
        category=category,
        priority=priority,
        target_id=target_id,
        trigger_source="test",
        reason_codes=[f"TEST:{behavior}"],
        payload={},
    )


def test_empty_candidates_returns_none() -> None:
    result = arbitrate([])
    assert result.winner is None
    assert "NO_AUTONOMOUS_CANDIDATE" in result.reason_codes


def test_priority_order_between_categories() -> None:
    """六级类目两两抽查：前者压制后者。"""
    order = [
        "danger_self_preserve",
        "combat_tactical",
        "player_command",
        "story_event",
        "relationship_event",
        "routine_autonomy",
    ]
    for higher, lower in zip(order, order[1:]):
        result = arbitrate(
            [_candidate("low", lower, priority=90), _candidate("high", higher, priority=5)]
        )
        assert result.winner is not None
        assert result.winner.behavior == "high", f"{higher} 应压制 {lower}"
        assert any(c.behavior == "low" for c in result.suppressed)


def test_same_category_higher_priority_wins() -> None:
    """同 category 内比 priority 数值。"""
    result = arbitrate(
        [
            _candidate("a", "routine_autonomy", priority=10),
            _candidate("b", "routine_autonomy", priority=30),
        ]
    )
    assert result.winner is not None
    assert result.winner.behavior == "b"


def test_same_category_and_priority_is_deterministic() -> None:
    """priority 相同时按稳定序（字典序）决胜，保证测试确定。"""
    first = arbitrate(
        [_candidate("zzz", "routine_autonomy", priority=20), _candidate("aaa", "routine_autonomy", priority=20)]
    )
    assert first.winner is not None
    assert first.winner.behavior == "aaa"
    # 顺序颠倒结果一致
    second = arbitrate(
        [_candidate("aaa", "routine_autonomy", priority=20), _candidate("zzz", "routine_autonomy", priority=20)]
    )
    assert second.winner is not None
    assert second.winner.behavior == "aaa"


def test_unknown_category_dropped_with_reason() -> None:
    """类目不在 priority_order 六项内 → 丢弃并记录原因（策略文件即法律）。"""
    result = arbitrate([_candidate("weird", "not_a_category")])
    assert result.winner is None
    assert any("not_a_category" in code for code in result.reason_codes)


def test_suppressed_preserved_for_explainability() -> None:
    """被压制的候选保留在 suppressed 中（可解释，章程原则 V）。"""
    result = arbitrate(
        [
            _candidate("alert", "danger_self_preserve", priority=70),
            _candidate("inspect", "routine_autonomy", priority=25),
        ]
    )
    assert result.winner is not None
    assert result.winner.behavior == "alert"
    assert [c.behavior for c in result.suppressed] == ["inspect"]
