"""Console transport models shared by legacy/scoped adapters."""
from pydantic import BaseModel, ConfigDict, Field

class MemoryEntryView(BaseModel):
    """调试视图：单条长期记忆的精简字段。"""

    model_config = ConfigDict(extra="forbid")
    content: str
    importance: str
    source: str
    real_time: str


class ConsoleStateResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    registered_companions: list[str]
    companion_id: str
    display_name: str
    memory_backend: str          # 当前记忆后端说明（长期记忆 T025 落地后更新）
    session_memory_turns: int    # 会话记忆窗口配置
    tactical_policy_revision: str
    # ---- US7（T077）调试视图：场景 / 情绪 / 关系 / 记忆 / 版本 ----
    persona_revision: str                 # 人设 YAML 的 profile_version
    agency_policy_revision: str           # 自主行为策略版本
    relationship_stage: str               # 关系阶段（体系故障为空字符串）
    relationship_stage_display: str       # FIX-05：关系阶段中文展示名
    relationship_value: float | None      # 关系数值（同上为 None）
    last_scene: str                      # 最近一次快照的活动场景（重启后为空）
    last_emotion_id: str                  # 最近一次输出表现的表情 ID（同上）
    last_seen: str                        # 最近一次观测时间 ISO-8601 UTC（重启后为空）
    recent_memory: list[MemoryEntryView]  # 近期记忆摘要（按重要性取前 5）


class MemoryResetRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    companion_id: str = Field(min_length=1)


class MemoryResetResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    companion_id: str
    reset: bool
    cleared_sessions: int       # 实际清除的会话分区数（含 0：无会话也是成功）


class TopicImpressionView(BaseModel):
    """调试视图：单条模糊印象（主题 × 提及频率）。"""

    model_config = ConfigDict(extra="forbid")
    topic: str
    mention_count: int
    weight: float
    last_seen: str
    origin: str


class MemoryViewResponse(BaseModel):
    """长期记忆全量视图（GET /v1/console/memory），含模糊印象层。"""

    model_config = ConfigDict(extra="forbid")
    companion_id: str
    counts: dict[str, int]           # short_term / summaries / archive / impressions 各层条数
    short_term: list[MemoryEntryView]
    summaries: list[MemoryEntryView]
    archive: list[MemoryEntryView]
    impressions: list[TopicImpressionView]
