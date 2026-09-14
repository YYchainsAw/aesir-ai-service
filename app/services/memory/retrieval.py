"""按预算检索与注入（SDD T027 / FR-009）。

合并档案 + 摘要 + 近期短期三层，按重要性优先、同级按时间新者优先排序，
在预算（条数）内截断——避免上下文无限增长。任何存储层故障都降级为空
记忆（FR-011）：检索失败不能阻塞对话主流程。
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.memory import MemoryEntry
from app.config import get_settings

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


def format_memory_block(entries: list[MemoryEntry], display_name: str = "她") -> str:
    """把记忆条目格式化为注入 LLM prompt 的文本块（T028 使用）。"""
    if not entries:
        return ""
    lines = [f"Long-term memories about the player (facts {display_name} remembers; "
             "reference them naturally when relevant, do not recite them):"]
    for entry in entries:
        lines.append(f"- [{entry.source}] {entry.content}")
    return "\n".join(lines)
