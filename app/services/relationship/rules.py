"""关系事件驱动规则（SDD T038 / FR-014、FR-017）。

纯函数层：策略表决定幅度，防刷（同类事件冷却窗口）与每日正向上限由
调用方传入（来自配置，章程原则 I）。未登记事件一律忽略。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.schemas.relationship import RelationshipEventRecord, RelationshipState
from app.services.relationship.policy import RelationshipPolicy, get_policy

# 近期事件留痕上限（超出滚动淘汰最旧；只影响可解释性，不影响计分）
_RECENT_EVENT_LIMIT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def stage_of(value: int, policy: RelationshipPolicy | None = None) -> str:
    """按数值落入的区间返回阶段名（FR-016）。"""
    policy = policy or get_policy()
    for stage in policy.stages:
        if stage.low <= value <= stage.high:
            return stage.name
    # 数值越界（钳制前的防御）：往最靠近的区间归
    return policy.stages[0].name if value < policy.stages[0].low else policy.stages[-1].name


def apply_relationship_event(
    state: RelationshipState,
    event_type: str,
    occurred_at: str | None,
    *,
    policy: RelationshipPolicy | None = None,
    cooldown_seconds: float | None = None,
    daily_cap: int | None = None,
) -> tuple[RelationshipState, int]:
    """应用一条事实事件；返回（新状态, 实际计分值）。

    - 未登记事件 → (原状态, 0)；
    - 冷却窗口内同类型重复 → 不计分（防刷）；
    - 当日正向净变化超上限 → 截断到剩余额度（负向不受限）；
    - 数值最终钳制在策略表边界内。
    """
    policy = policy or get_policy()
    settings = get_settings()
    cooldown = cooldown_seconds if cooldown_seconds is not None else settings.relationship_event_cooldown_seconds
    cap = daily_cap if daily_cap is not None else settings.relationship_daily_cap

    if event_type not in policy.events:
        return state, 0

    moment = _parse(occurred_at) if occurred_at else _now()
    day = moment.date().isoformat()

    # 跨日：重置当日正向额度
    daily_net = state.daily_net if day == state.day else 0

    # 冷却窗口：同类型最近一条在窗口内则不计分
    for record in reversed(state.recent_events):
        if record.event_type == event_type:
            elapsed = (moment - _parse(record.occurred_at)).total_seconds()
            if 0 <= elapsed < cooldown:
                return state, 0
            break  # 只看最近一条同类事件

    delta = policy.events[event_type]
    if delta > 0:
        allowed = max(cap - daily_net, 0)  # 当日剩余正向额度
        if allowed == 0:
            return state, 0
        delta = min(delta, allowed)

    value = max(policy.min, min(policy.max, state.value + delta))
    applied = value - state.value  # 边界钳制可能吃掉部分变化
    if applied == 0:
        return state, 0
    if applied > 0:
        daily_net += applied

    recent = list(state.recent_events)
    recent.append(RelationshipEventRecord(event_type=event_type, occurred_at=moment.isoformat(timespec="seconds").replace("+00:00", "Z"), delta=applied))
    recent = recent[-_RECENT_EVENT_LIMIT:]

    new_state = RelationshipState(
        value=value,
        stage=stage_of(value, policy),
        day=day,
        daily_net=daily_net,
        recent_events=recent,
    )
    return new_state, applied
