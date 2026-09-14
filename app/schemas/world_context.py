"""世界状态快照（SDD T007 / Key Entity「世界状态快照」）。

客户端某一时刻观测到的事实集合：活动场景、世界时间与天气、区域、玩家/NPC
状态、周围可交互对象。是**只读输入**，不承担权威状态职责（章程原则 III）；
UE 仍拥有最终否决权。既有战斗字段经 ``combat`` 内嵌保留（v0.2 ``CombatContext``
不做语义改动），战斗链路照旧消费内嵌快照。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.combat_context import CombatContext

# 活动场景（FR-019，与 agency_policy.yaml / directives.common 一致）
Scene = Literal["combat", "exploration", "camp", "conversation", "idle"]


class WorldTime(BaseModel):

    model_config = ConfigDict(extra="forbid")
    game_clock: str = Field("", description="游戏内时钟，如 '21:30'；缺省时时间驱动行为不启用")
    time_of_day: Literal["morning", "noon", "evening", "night"] = "noon"
    weather: Literal["clear", "rain", "snow", "storm", "fog"] = "clear"


class WorldRegion(BaseModel):

    model_config = ConfigDict(extra="forbid")
    region_id: str
    first_visit: bool = False  # 玩家首次进入该区域（US5 区域事件判定用）


class WorldInteractable(BaseModel):
    """快照中出现过的可交互对象；NPC 自主行为只允许引用这些 object_id（FR-040）。"""

    model_config = ConfigDict(extra="forbid")
    object_id: str
    kind: Literal["item", "npc", "prop", "poi"] = "prop"
    distance_m: float = Field(default=0.0, ge=0)
    notable: bool = False  # 值得注意（US3：靠近看一眼/提醒玩家）


class WorldPlayerState(BaseModel):

    model_config = ConfigDict(extra="forbid")
    id: str
    hp_percent: float = Field(ge=0, le=100)
    is_downed: bool = False


class WorldCompanionState(BaseModel):

    model_config = ConfigDict(extra="forbid")
    id: str
    hp_percent: float = Field(ge=0, le=100)
    mp_percent: float = Field(ge=0, le=100)
    current_behavior: str = ""
    is_casting: bool = False    # 禁打断情形之一（FR-023）


class WorldContext(BaseModel):
    """非战斗/通用场景的世界快照（UE 生成，低频上传，只读）。"""

    snapshot_id: str
    captured_at: str  # ISO-8601 UTC
    scene: Scene
    world_time: WorldTime = WorldTime()
    region: WorldRegion | None = None
    player: WorldPlayerState
    companion: WorldCompanionState
    interactables: list[WorldInteractable] = Field(default_factory=list)
    ui_popup: bool = False                 # 禁打断情形（FR-023）
    cutscene_playing: bool = False         # 禁打断情形（FR-023）
    player_speaking: bool = False          # 禁打断情形（FR-023）
    combat: CombatContext | None = None    # 既有战斗快照原样内嵌；仅 combat 场景携带

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: str) -> str:
        """与 CombatContext 同一约束：非法 ISO-8601 按 422 拒绝（协议 §2.1）。"""
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"captured_at 必须是 ISO-8601 UTC 时间，例如 '2026-09-13T12:00:00Z'，收到：{value!r}"
            ) from exc
        return value
