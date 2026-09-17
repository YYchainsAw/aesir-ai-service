"""按预算检索与注入（SDD T027 / FR-009 + 模糊印象层）。

合并档案 + 摘要 + 近期短期三层，按重要性优先、同级按时间新者优先排序，
在预算（条数）内截断——避免上下文无限增长。模糊印象单独走
``retrieve_impressions``：按现算权重排序、占固定小份额（不挤占上面的
预算），注入为「对玩家常提话题的印象」而非逐字内容。

任何存储层故障都降级为空记忆（FR-011）：检索失败不能阻塞对话主流程。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app.schemas.memory import MemoryEntry, TopicImpression
from app.config import get_settings
from app.services.memory.topics import impression_weight, looks_like_noise, tier_of

_IMPORTANCE_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


class _SnapshotProvider(Protocol):
    def snapshot(self):
        ...


def retrieve(store: _SnapshotProvider, *, budget: int | None = None) -> list[MemoryEntry]:
    """检索注入预算内的记忆条目；故障时返回空列表（降级，不抛异常）。"""
    if budget is None:
        budget = get_settings().memory_injection_budget
    if budget <= 0:
        return []
    try:
        snapshot = store.snapshot()
    except Exception:  # noqa: BLE001 - 存储层任何故障都降级为无记忆（FR-011）
        return []

    merged = list(snapshot.archive) + list(snapshot.summaries) + list(snapshot.short_term)
    merged.sort(
        key=lambda e: (_IMPORTANCE_ORDER.get(e.importance, 2), e.real_time),
        reverse=True,
    )
    # reverse 后同级内部时间也是新→旧；但重要性序也反了，重新按重要性升序展示注入
    merged.sort(key=lambda e: _IMPORTANCE_ORDER.get(e.importance, 2))
    return merged[:budget]


def retrieve_impressions(
    store: _SnapshotProvider,
    *,
    share: int | None = None,
) -> list[TopicImpression]:
    """检索达到注入阈值的模糊印象，按现算权重降序、截固定份额。

    权重随半衰期衰减：长期不再被提及的主题自然淡出注入。存储层故障
    降级为空列表（FR-011 同语义）。
    """
    if share is None:
        share = get_settings().memory_impression_injection_share
    if share <= 0:
        return []
    try:
        snapshot = store.snapshot()
    except Exception:  # noqa: BLE001 - 存储层任何故障都降级为无记忆
        return []

    now = datetime.now(timezone.utc)
    ranked: list[tuple[float, TopicImpression]] = []
    for impression in snapshot.impressions:
        if looks_like_noise(impression.topic):  # 旧数据里已落的噪声碎片不再注入
            continue
        days_ago = _days_ago(impression.last_seen, now)
        if (
            tier_of(
                impression.mention_count,
                last_seen_days_ago=days_ago,
                salient=impression.salient,
                salience_boost=impression.salience_boost,
            )
            is None
        ):
            continue
        weight = impression_weight(
            mention_count=impression.mention_count,
            last_seen_days_ago=days_ago,
            salient=impression.salient,
            salience_boost=impression.salience_boost,
        )
        ranked.append((weight, impression))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [impression for _, impression in ranked[:share]]


def _days_ago(iso_timestamp: str, now: datetime) -> float:
    """ISO 时间戳距今天数；解析失败按 0 处理（宁可多注入不静默丢失）。"""
    try:
        parsed = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def format_impression_block(
    impressions: list[TopicImpression], display_name: str = "她"
) -> str:
    """把模糊印象格式化为注入 LLM prompt 的文本块（档位化口吻）。

    口吻按档位与近期程度区分：deep（印象很深）> 近期刚聊过（哪怕只提过
    一次）> 久远的模糊印象。指令要求自然带出（近期话题可主动提及拉回），
    绝不逐字背诵、不复述次数。
    """
    if not impressions:
        return ""
    now = datetime.now(timezone.utc)
    lines = [
        f"Fuzzy impressions of topics ({display_name} "
        "does not recall them word for word; weave them in naturally when "
        "relevant, never recite counts; topics talked about recently may be "
        "brought up first as a natural callback; NEVER claim the player said "
        "any specific sentence you were not shown — these are topic-level "
        "memories only, so phrase them vaguely or ask instead of inventing "
        "details):"
    ]
    for impression in impressions:
        days_ago = _days_ago(impression.last_seen, now)
        tier = tier_of(
            impression.mention_count,
            last_seen_days_ago=days_ago,
            salient=impression.salient,
            salience_boost=impression.salience_boost,
        )
        if impression.origin == "companion":
            # 她自己说过的话：措辞必须是「她提过」，绝不能记成玩家说的。
            lines.append(
                f"- {impression.topic} is something {display_name} herself "
                f"brought up recently — her own words, NOT the player's."
            )
            continue
        if tier == "deep":
            lines.append(
                f"- {impression.topic} is something the player often brings up; "
                f"{display_name} has a deep impression of it."
            )
        elif days_ago <= 1.0:
            lines.append(
                f"- {display_name} was talking with the player about "
                f"{impression.topic} recently ({_recency_phrase(days_ago)})."
            )
        else:
            lines.append(
                f"- {display_name} vaguely remembers the player mentioning "
                f"{impression.topic} more than once."
            )
    return "\n".join(lines)


def _recency_phrase(days_ago: float) -> str:
    if days_ago < 0.5:
        return "today"
    return "yesterday or the day before"


def format_memory_block(entries: list[MemoryEntry], display_name: str = "她") -> str:
    """把记忆条目格式化为注入 LLM prompt 的文本块（T028 使用）。"""
    if not entries:
        return ""
    lines = [f"Long-term memories about the player (facts {display_name} remembers; "
             "reference them naturally when relevant, do not recite them):"]
    for entry in entries:
        lines.append(f"- [{entry.source}] {entry.content}")
    return "\n".join(lines)
