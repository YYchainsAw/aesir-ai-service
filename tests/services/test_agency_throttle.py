"""自主行为节流与去重测试（SDD T047 / FR-022、FR-023）。

覆盖：同触发源去重窗口、单周期次数上限、跨角色隔离、并发安全、reset。
节流状态进程内（不落盘），测试通过 reset 保证用例独立。
"""

from __future__ import annotations

import threading

from app.services.agency.behavior_catalog import BehaviorCandidate
from app.services.agency.throttle import (
    AutonomousThrottle,
    get_throttle,
    reset_throttle,
)


def _candidate(behavior: str = "inspect", target_id: str | None = "object.campfire.001",
               trigger_source: str = "notable_object") -> BehaviorCandidate:
    return BehaviorCandidate(
        behavior=behavior,
        category="routine_autonomy",
        priority=25,
        target_id=target_id,
        trigger_source=trigger_source,
        reason_codes=[],
        payload={},
    )


def _throttle() -> AutonomousThrottle:
    return AutonomousThrottle(dedup_window_seconds=300, max_per_window=3, window_seconds=300)


def test_same_trigger_key_deduped_within_window() -> None:
    """同 (behavior, target, trigger_source) 在窗口内重复 → 拒绝。"""
    throttle = _throttle()
    first = throttle.admit("companion.alice", _candidate(), now=1000.0)
    assert first.allowed
    second = throttle.admit("companion.alice", _candidate(), now=1100.0)
    assert not second.allowed
    assert "DEDUP_WINDOW" in second.reason_codes


def test_dedup_window_expires() -> None:
    """窗口过后同一触发源放行（注入 now）。"""
    throttle = _throttle()
    assert throttle.admit("companion.alice", _candidate(), now=1000.0).allowed
    again = throttle.admit("companion.alice", _candidate(), now=1300.0)
    assert again.allowed


def test_different_trigger_source_not_deduped() -> None:
    """同一行为同一目标、不同触发原因不算重复。"""
    throttle = _throttle()
    assert throttle.admit("companion.alice", _candidate(), now=1000.0).allowed
    other = _candidate(trigger_source="night_rest")
    assert throttle.admit("companion.alice", other, now=1000.5).allowed


def test_max_per_window_exceeded() -> None:
    """窗口内不同 key 的第 4 个候选 → MAX_PER_WINDOW_EXCEEDED。"""
    throttle = _throttle()
    for i in range(3):
        candidate = _candidate(target_id=f"object.item.{i}")
        assert throttle.admit("companion.alice", candidate, now=1000.0 + i).allowed
    fourth = throttle.admit(
        "companion.alice", _candidate(target_id="object.item.9"), now=1003.0
    )
    assert not fourth.allowed
    assert "MAX_PER_WINDOW_EXCEEDED" in fourth.reason_codes


def test_companion_isolation() -> None:
    """不同 companion_id 互不影响。"""
    throttle = _throttle()
    assert throttle.admit("companion.alice", _candidate(), now=1000.0).allowed
    assert throttle.admit("companion.bob", _candidate(), now=1000.0).allowed


def test_concurrent_admit_is_thread_safe() -> None:
    """多线程 admit 不崩且不丢锁（与心跳限流同款 Lock 模式）。"""
    throttle = _throttle()
    errors: list[Exception] = []

    def _worker(index: int) -> None:
        try:
            for i in range(50):
                throttle.admit(
                    "companion.alice",
                    _candidate(target_id=f"object.item.{index}-{i}"),
                    now=1000.0 + i,
                )
        except Exception as exc:  # pragma: no cover - 失败才记录
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_reset_clears_state() -> None:
    throttle = _throttle()
    assert throttle.admit("companion.alice", _candidate(), now=1000.0).allowed
    throttle.reset()
    assert throttle.admit("companion.alice", _candidate(), now=1000.5).allowed


def test_module_level_singleton_accessible_and_resettable() -> None:
    """get_throttle() 单例可用，reset_throttle() 供测试隔离。"""
    throttle = get_throttle()
    assert throttle is get_throttle()
    reset_throttle()
    assert get_throttle().admit("companion.alice", _candidate()).allowed
    reset_throttle()
