"""经历摘要器（SDD T026 / FR-007）。

摘要在**落盘时**生成：把一批经历条目聚合为少量 summary 级记忆（按来源与
游戏日期分组），事件触发写入，而非逐条写盘——控制摘要层容量与 prompt 预算。
"""

from __future__ import annotations

from collections import defaultdict

from app.schemas.memory import MemoryEntry

# 分组键：来源 × 游戏日期（缺省按真实日期）
_GROUP_KEY_SEPARATOR = "\x1f"


def summarize_experiences(entries: list[MemoryEntry]) -> list[MemoryEntry]:
    """把一批经历聚合为按 (source, 日期) 分组的摘要条目。

    摘要的重要性取组内最高（共同击败强敌 → high），保证检索排序不失真。
    """
    groups: dict[str, list[MemoryEntry]] = defaultdict(list)
    for entry in entries:
        date = (entry.game_time or entry.real_time)[:10]
        groups[f"{entry.source}{_GROUP_KEY_SEPARATOR}{date}"].append(entry)

    summaries: list[MemoryEntry] = []
    for key, group in groups.items():
        source, date = key.split(_GROUP_KEY_SEPARATOR, 1)
        highest = _RANK_IMPORTANCE[max(
            (_IMPORTANCE_RANK[e.importance] for e in group),
            default=_IMPORTANCE_RANK["normal"],
        )]
        contents = [e.content.rstrip("。.") for e in group]
        summaries.append(
            MemoryEntry(
                content=f"{date} {'；'.join(contents)}。",
                importance=highest,
                source="summary",
                game_time=group[0].game_time,
                real_time=group[0].real_time,
                tags=[source],
            )
        )
    return summaries


_IMPORTANCE_RANK = {"critical": 3, "high": 2, "normal": 1, "low": 0}
_RANK_IMPORTANCE = {rank: name for name, rank in _IMPORTANCE_RANK.items()}
