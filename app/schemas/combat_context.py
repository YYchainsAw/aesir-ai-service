"""v0.2 战斗状态快照 `CombatContext`（草案 §3）。

所有战术落地（``/v1/tactical/resolve``）与自动事件（``/v1/combat/events``）
共享该对象。只描述 UE 观测到的事实：服务端不得修改后当作权威状态。
字段保持小而稳定；高频数据（完整位置向量、逐帧状态、伤害流水）留在 UE，
之后若做 RL 另建低频观测接口，不污染本协议。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Percent = float  # [0, 100]；用 Field 约束在具体字段上


class ContextPlayer(BaseModel):
    id: str
    hp_percent: Percent = Field(ge=0, le=100)
    is_downed: bool = False
    distance_to_boss_m: float = Field(default=0, ge=0)


class ContextCompanion(BaseModel):
    id: str
    hp_percent: Percent = Field(ge=0, le=100)
    mp_percent: Percent = Field(ge=0, le=100)
    current_behavior: str = ""
    ability_states: dict[str, Literal["ready", "cooldown", "unavailable", "blocked"]]


class ContextBoss(BaseModel):
    id: str
    hp_percent: Percent = Field(ge=0, le=100)
    stun_percent: Percent = Field(default=0, ge=0, le=100)
    state_tags: list[str] = Field(default_factory=list)
    stunned_remaining_seconds: float | None = Field(default=None, ge=0)
    phase: int = Field(default=1, ge=1)
    is_enraged: bool = False


class CombatContext(BaseModel):
    """一场 Boss 战的某一时刻快照（UE 生成，低频上传）。"""

    encounter_id: str
    snapshot_id: str
    captured_at: str  # ISO-8601 UTC
    mode: Literal["combat"]
    player: ContextPlayer
    companion: ContextCompanion
    boss: ContextBoss

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: str) -> str:
        """快照时间必须是合法 ISO-8601（协议 §2.1）。

        结构非法按 422 拒绝，避免错误时间戳混入回执/日志后才暴露。
        """
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"captured_at 必须是 ISO-8601 UTC 时间，例如 '2026-09-03T12:00:00Z'，收到：{value!r}"
            ) from exc
        return value


def make_combat_context(
    *,
    player_hp: float,
    companion_hp: float = 83,
    companion_mp: float = 72,
    boss_hp: float = 42,
    boss_state_tags: list[str] | None = None,
    stunned_remaining: float | None = None,
    player_distance: float = 4.5,
    companion_behavior: str = "ranged_attack",
    ability_states: dict[str, str] | None = None,
    encounter_id: str = "encounter.test.001",
) -> CombatContext:
    """构造测试/联调用快照。

    能力目录默认按 v0.2 草案 §3 的示例（治疗/护盾/爆发），其中爆裂、强效治疗
    等可被策略层引用。真实联调时由 UE 上传，不经此函数。
    """
    return CombatContext(
        encounter_id=encounter_id,
        snapshot_id="a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd",
        captured_at="2026-09-03T12:00:00Z",
        mode="combat",
        player=ContextPlayer(
            id="party.player",
            hp_percent=player_hp,
            is_downed=player_hp <= 0,
            distance_to_boss_m=player_distance,
        ),
        companion=ContextCompanion(
            id="companion.alice",
            hp_percent=companion_hp,
            mp_percent=companion_mp,
            current_behavior=companion_behavior,
            ability_states=ability_states
            or {
                "ability.alice.basic_attack": "ready",
                "ability.alice.explosion": "ready",
                "ability.alice.quick_heal": "ready",
                "ability.alice.major_heal": "ready",
                "ability.alice.shield": "ready",
            },
        ),
        boss=ContextBoss(
            id="encounter.primary_hostile",
            hp_percent=boss_hp,
            stun_percent=100 if stunned_remaining else 0,
            state_tags=boss_state_tags or [],
            stunned_remaining_seconds=stunned_remaining,
            phase=2,
            is_enraged=False,
        ),
    )
