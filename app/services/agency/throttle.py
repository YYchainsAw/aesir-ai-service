"""自主行为节流、去重与窗口上限（SDD T053 / FR-022）。

进程内状态、不落盘：去重语义窗口（默认 300s）远小于进程生命周期，
丢失最坏结果是重复一次自主行为（UE 拥有最终否决权，章程原则 III），
非数据完整性问题；与关系计分（事实数据）不同，无需持久化与损坏隔离。

实现模式与 ``app/api/v1/agent.py`` 心跳限流一致：OrderedDict + Lock +
有界容量。键 = (companion_id, behavior, target_id, trigger_source)——同一
行为对不同目标、同一目标不同触发原因都不算重复。

## 配置生效口径（CODE-08① / T20）

``get_throttle()`` 模块级单例在**首次调用时**从策略 YAML 读一次参数并固化，
进程运行期**不做热更新**——改 ``data/policy/`` 下的节流配置后需**重启进程**才生效。
这是有意的边界（本服务不引入配置热更新平台，见 T20 范围），不是缺陷。
测试隔离用 ``reset_throttle()`` 清空单例，使下一次 ``get_throttle()`` 重读策略。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from app.scoped.storage import runtime_key, guarded_commit

from app.services.agency.behavior_catalog import BehaviorCandidate, get_agency_policy


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    reason_codes: list[str] = field(default_factory=list)


class AutonomousThrottle:
    """按角色分区的去重窗口 + 单周期次数上限。"""

    _MAX_TRACKED = 1024  # 有界缓存防长会话膨胀（与 event_policy 同一做法）

    def __init__(self, *, dedup_window_seconds: float, max_per_window: int, window_seconds: float) -> None:
        self._dedup_window = dedup_window_seconds
        self._max_per_window = max_per_window
        self._window = window_seconds
        self._seen: "OrderedDict[tuple[str, str, str, str], float]" = OrderedDict()
        self._lock = threading.Lock()

    @guarded_commit
    def admit(
        self, companion_id: str, candidate: BehaviorCandidate, now: float | None = None
    ) -> ThrottleDecision:
        """判定候选是否放行；放行同时登记（占用窗口计数）。"""
        if now is None:
            now = time.monotonic()
        companion_key = runtime_key(companion_id)
        key = (
            companion_key,
            candidate.behavior,
            candidate.target_id or "-",
            candidate.trigger_source,
        )
        with self._lock:
            self._evict(now)
            last = self._seen.get(key)
            if last is not None and (now - last) < self._dedup_window:
                return ThrottleDecision(False, ["DEDUP_WINDOW"])
            # 窗口内该角色已放行的不同键数量（去重窗口与计数窗口同长）
            admitted_in_window = sum(
                1 for (cid, *_), ts in self._seen.items()
                if cid == companion_key and (now - ts) < self._window
            )
            if admitted_in_window >= self._max_per_window:
                return ThrottleDecision(False, ["MAX_PER_WINDOW_EXCEEDED"])
            self._seen[key] = now
            if len(self._seen) > self._MAX_TRACKED:
                self._seen.popitem(last=False)
        return ThrottleDecision(True, [])

    def reset(self) -> None:
        """清空全部状态（仅测试用）。"""
        with self._lock:
            self._seen.clear()

    def _evict(self, now: float) -> None:
        """惰性清理过期键（无锁内额外开销地保持有界）。"""
        expired = [k for k, ts in self._seen.items() if (now - ts) >= max(self._dedup_window, self._window)]
        for key in expired:
            del self._seen[key]


_throttle: AutonomousThrottle | None = None


def get_throttle() -> AutonomousThrottle:
    """模块级单例；参数取自策略 YAML。"""
    global _throttle
    if _throttle is None:
        policy = get_agency_policy().throttle
        _throttle = AutonomousThrottle(
            dedup_window_seconds=policy.dedup_window_seconds,
            max_per_window=policy.max_per_window,
            window_seconds=policy.dedup_window_seconds,
        )
    return _throttle


def reset_throttle() -> None:
    """清空单例（测试隔离用）。"""
    global _throttle
    if _throttle is not None:
        _throttle.reset()
    _throttle = None
