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

    本签名保持两元组不变（既有测试/demo 依赖）；拦截原因的可区分性由
    :func:`apply_relationship_event_ex` 提供（T38 / SC-004 埋点数据源）。
    """
    new_state, delta, _reason = apply_relationship_event_ex(
        state,
        event_type,
        occurred_at,
        policy=policy,
        cooldown_seconds=cooldown_seconds,
        daily_cap=daily_cap,
    )
    return new_state, delta


def apply_relationship_event_ex(
    state: RelationshipState,
    event_type: str,
    occurred_at: str | None,
    *,
    policy: RelationshipPolicy | None = None,
    cooldown_seconds: float | None = None,
    daily_cap: int | None = None,
) -> tuple[RelationshipState, int, str]:
    """同 :func:`apply_relationship_event`，额外返回拦截原因（T38 / SC-004）。

    reason ∈ ``scored``（正常计分）/ ``unknown_event``（未登记）/
    ``cooldown_blocked``（冷却窗口拦截）/ ``daily_cap``（当日正向上限耗尽）/
    ``clamped_zero``（边界钳制吃掉全部变化）。四种「delta=0」从此可区分。
    """
    policy = policy or get_policy()
    settings = get_settings()
    cooldown = cooldown_seconds if cooldown_seconds is not None else settings.relationship_event_cooldown_seconds
    cap = daily_cap if daily_cap is not None else settings.relationship_daily_cap

    if event_type not in policy.events:
        return state, 0, "unknown_event"

    moment = _parse(occurred_at) if occurred_at else _now()
    day = moment.date().isoformat()

    # 跨日：重置当日正向额度
    daily_net = state.daily_net if day == state.day else 0

    # 冷却窗口：同类型最近一次计分在窗口内则不计分。
    # 查独立的 last_event_at（不扫 recent_events）——recent_events 只保留最近
    # 20 条用于可解释性展示，高频交互会挤出旧记录，扫它会导致冷却判定漂移（CODE-08）。
    last_at = state.last_event_at.get(event_type)
    if last_at is not None:
        elapsed = (moment - _parse(last_at)).total_seconds()
        # elapsed < 0：客户端时钟回拨/重放旧事件，旧于上次计分--视为重复，
        # 不得绕过冷却（否则旧 occurred_at 可反复计分并把冷却基准回拨）。
        if elapsed < 0 or elapsed < cooldown:
            return state, 0, "cooldown_blocked"

    delta = policy.events[event_type]
    if delta > 0:
        allowed = max(cap - daily_net, 0)  # 当日剩余正向额度
        if allowed == 0:
            return state, 0, "daily_cap"
        delta = min(delta, allowed)

    value = max(policy.min, min(policy.max, state.value + delta))
    applied = value - state.value  # 边界钳制可能吃掉部分变化
    if applied == 0:
        return state, 0, "clamped_zero"
    if applied > 0:
        daily_net += applied

    recent = list(state.recent_events)
    recent.append(RelationshipEventRecord(event_type=event_type, occurred_at=moment.isoformat(timespec="seconds").replace("+00:00", "Z"), delta=applied))
    recent = recent[-_RECENT_EVENT_LIMIT:]

    # 更新该类事件最近计分时间戳（冷却判定依据）。
    last_event_at = dict(state.last_event_at)
    last_event_at[event_type] = moment.isoformat(timespec="seconds").replace("+00:00", "Z")

    new_state = RelationshipState(
        value=value,
        stage=stage_of(value, policy),
        day=day,
        daily_net=daily_net,
        recent_events=recent,
        last_event_at=last_event_at,
    )
    return new_state, applied, "scored"
