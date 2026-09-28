"""世界事件模型（SDD T009 / Key Entity「世界事件」，FR-032~FR-034）。

客户端在**状态边沿**上报的一次有意义变化（战斗与生活两类），不逐帧上报。
处理结果可被幂等回放：同一 ``companion_id + event_id`` 重复上报时回放首次
结果并标记 ``duplicate: true``（FR-033）。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.tactical_decision import DecisionAction
from app.schemas.world_context import WorldContext

# 事件类型白名单：既有战斗六类（v0.2）+ 生活类首版六类（T060）
WorldEventType = Literal[
    # 战斗类（v0.2 既有；经世界通道上报时复用同一决策表）
    "player_hp_critical",
    "boss_stun_near",
    "boss_stunned",
    "boss_enraged",
    "companion_mp_low",
    "boss_defeated",
    # 生活类（US5 首版 6 类，反应配置见 T060）
    "region_first_entered",
    "weather_changed",
    "gift_given",
    "companion_recovered",
    "player_protected_companion",
    "promise_kept",
]


class WorldEvent(BaseModel):

    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=128)
    event_type: WorldEventType
    occurred_at: str  # ISO-8601 UTC
    sequence: int = Field(ge=0, description="客户端事件序号，单调递增，便于乱序检测")
    details: dict[str, str] = Field(default_factory=dict)  # 事件细节（如 object_id、weather）

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"occurred_at 必须是 ISO-8601 UTC 时间，例如 '2026-09-13T12:00:00Z'，收到：{value!r}"
            ) from exc
        return value


class WorldEventRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["0.3"] = "0.3"
    request_id: str
    companion_id: str
    event: WorldEvent
    world_context: WorldContext


class WorldEventReaction(BaseModel):
    """NPC 对事件的反应（表现 ID 来自角色配置白名单）。"""

    model_config = ConfigDict(extra="forbid")
    reply_text: str
    emotion_id: str
    gesture_id: str = ""
    facial_expression_id: str = ""


class WorldEventObservability(BaseModel):

    model_config = ConfigDict(extra="forbid")
    source: Literal["rule", "llm", "rule_fallback"] = "rule"
    policy_revision: str = ""
    used_snapshot_id: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    # 关系联动留痕（FR-014 / US7 可解释）：未触发关系计分时为空串与 0
    relationship_stage: str = ""
    relationship_stage_display: str = ""
    relationship_delta: int = 0


class WorldEventResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["0.3"] = "0.3"
    request_id: str
    companion_id: str
    event_id: str
    duplicate: bool = False          # 重复上报回放首次结果（FR-033）
    reaction: WorldEventReaction | None = None
    recommendation_text: str | None = None  # 建议展示文本；无建议时为 null
    # 战斗类事件经世界通道上报时复用战斗决策表产出的候选动作；
    # 生活类事件恒为 null（UE 无动作可执行）。
    companion_action: DecisionAction | None = None
    observability: WorldEventObservability
