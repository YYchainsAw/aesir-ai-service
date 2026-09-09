"""v0.2 `POST /v1/combat/events` 的请求/响应模型（草案 §6）。

UE 在状态边沿（Boss 眩晕、玩家血线危急等）上报事件，服务端返回艾莉反应
（台词 + 表现）、对玩家的建议、以及可选的候选动作 ``companion_action``。

动作可为 ``null``：资源不足或技能 CD 时服务仍返回反应与建议，
但绝不虚构可施放动作（与 resolve 同一原则）。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.combat_context import CombatContext
from app.schemas.tactical_decision import DecisionAction

PROTOCOL_VERSION_V02 = "0.2"


def _validate_iso8601_utc(value: str) -> str:
    """协议 §2.1：时间字段必须是 ISO-8601 UTC，非法按 422 拒绝。"""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"时间字段必须是 ISO-8601 UTC，例如 '2026-09-03T12:00:00Z'，收到：{value!r}"
        ) from exc
    return value


# 草案 §6.1：首版固定六类事件
EventType = Literal[
    "player_hp_critical",
    "boss_stun_near",
    "boss_stunned",
    "boss_enraged",
    "companion_mp_low",
    "boss_defeated",
]


class CombatEvent(BaseModel):
    event_id: str
    event_type: EventType
    occurred_at: str  # ISO-8601 UTC
    sequence: int = Field(ge=0)

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: str) -> str:
        return _validate_iso8601_utc(value)


class CombatEventRequest(BaseModel):
    protocol_version: Literal["0.2"] = PROTOCOL_VERSION_V02
    request_id: str
    event: CombatEvent
    combat_context: CombatContext


class EventReaction(BaseModel):
    """艾莉对事件的人设反应（表现字段与聊天响应同构）。"""

    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool = True


class EventRecommendation(BaseModel):
    """给玩家的建议；仅提示，不代表必须执行。"""

    type: str
    target_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    display_text: str


class EventObservability(BaseModel):
    policy_revision: str = ""
    used_snapshot_id: str = ""


class CombatEventResponse(BaseModel):
    protocol_version: Literal["0.2"] = PROTOCOL_VERSION_V02
    request_id: str
    event_id: str
    source: str
    reaction: EventReaction
    recommendation: EventRecommendation | None = None
    companion_action: DecisionAction | None = None
    observability: EventObservability
    # 幂等标记：同一 encounter_id+event_id 的重试回放首次响应时为 true。
    # UE 可据此识别网络重试；回放保持同一 order_id，不会重复下发动作。
    duplicate: bool = False
