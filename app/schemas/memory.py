"""记忆条目与档案模型（SDD T024 / FR-006~FR-012）。

四条分级（FR-007 + 模糊印象层）：
- 短期上下文：会话内的对话轮次，滚动窗口；
- 经历摘要：跨会话的共同经历，落盘时聚合生成（T026，非逐条）；
- 长期档案：事实与承诺，容量淘汰时承诺类优先保留（FR-008）；
- 模糊印象：主题 × 提及频率——不逐字记对话，反复提起的话题印象加深
  （weight 随半衰期衰减），达到阈值才注入 prompt。
"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

MemoryImportance = Literal["low", "normal", "high", "critical"]
MemorySource = Literal["player_statement", "shared_experience", "promise", "observation", "summary"]


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class MemoryEntry(BaseModel):
    """一条可持久化的记忆（Key Entity「记忆条目」）。

    ``game_time`` 为游戏内时间、``real_time`` 为真实时间（双时间戳，SDD Key
    Entities）；来源与发生时间可追溯（FR-012）。
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: UUID = Field(default_factory=uuid4)
    content: str = Field(min_length=1, max_length=2000)
    importance: MemoryImportance = "normal"
    source: MemorySource = "player_statement"
    game_time: str = ""
    real_time: str = Field(default_factory=_utc_now_iso)
    tags: list[str] = Field(default_factory=list)


class TopicImpression(BaseModel):
    """模糊印象：她对一个主题的记忆强度（提及频率驱动，非逐字）。

    ``weight`` 为展示方便的冗余快照（检索时按 ``mention_count`` +
    ``last_seen`` 现算，见 ``topics.impression_weight``），落盘时刷新。
    """

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=32)
    mention_count: int = Field(default=1, ge=1)
    first_seen: str = Field(default_factory=_utc_now_iso)
    last_seen: str = Field(default_factory=_utc_now_iso)
    weight: float = Field(default=1.0, ge=0.0)


class MemorySnapshot(BaseModel):
    """一次读取到的记忆全量视图（检索按预算压缩注入，FR-009）。

    ``impressions`` 为模糊印象层：旧 ``memory.json`` 无此字段时默认空列表，
    向后兼容。
    """

    short_term: list[MemoryEntry] = Field(default_factory=list)
    summaries: list[MemoryEntry] = Field(default_factory=list)
    archive: list[MemoryEntry] = Field(default_factory=list)
    impressions: list[TopicImpression] = Field(default_factory=list)
