"""跨域仲裁（SDD T052 / FR-024）。

六级优先级（高 → 低）：危险自保 > 战斗战术 > 玩家指令 > 剧情事件 >
关系事件 > 日常自主。类目顺序来自 ``agency_policy.yaml``（策略文件即法律），
未知类目直接丢弃并记录原因；被压制的候选保留在 ``suppressed`` 供可解释
（章程原则 V）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.services.agency.behavior_catalog import AgencyPolicy, BehaviorCandidate, get_agency_policy


@dataclass(frozen=True)
class ArbiterResult:
    winner: BehaviorCandidate | None
    suppressed: list[BehaviorCandidate] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


def arbitrate(
    candidates: Sequence[BehaviorCandidate], policy: AgencyPolicy | None = None
) -> ArbiterResult:
    """从候选中选出唯一胜者；空输入或全部非法时 winner=None。"""
    if policy is None:
        policy = get_agency_policy()
    order = policy.arbiter.priority_order
    rank = {category: index for index, category in enumerate(order)}

    valid: list[BehaviorCandidate] = []
    dropped: list[str] = []
    for candidate in candidates:
        if candidate.category not in rank:
            dropped.append(candidate.category)
            continue
        valid.append(candidate)

    if dropped:
        duplicate_note = sorted(set(dropped))
        reason = [f"UNKNOWN_CATEGORY:{category}" for category in duplicate_note]
    else:
        reason = []

    if not valid:
        return ArbiterResult(
            winner=None, suppressed=[], reason_codes=["NO_AUTONOMOUS_CANDIDATE", *reason]
        )

    # 类目优先级 → 数值优先级 → 稳定序（字典序），保证结果确定
    ranked = sorted(valid, key=lambda c: (rank[c.category], -c.priority, c.behavior))
    winner, *suppressed = ranked
    return ArbiterResult(winner=winner, suppressed=suppressed, reason_codes=reason)
