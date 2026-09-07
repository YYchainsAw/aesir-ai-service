"""v0.2 文本语义意图 `TacticalIntent`（草案 §4）。

语义意图表达「玩家想做什么」，不直接承诺施放哪一个技能；由规则/LLM 解析
生成，必须可验证。``parse_confidence`` 是辅助观察字段，不能独自允许危险
动作；低置信度应返回澄清或保守策略。
"""

from typing import Literal

from pydantic import BaseModel, Field

IntentId = Literal[
    "support_heal_player",      # 治疗玩家
    "support_protect_player",   # 给玩家护盾/保命
    "burst_boss",               # 对 Boss 使用爆发输出
    "prepare_burst_on_stun",    # Boss 眩晕时爆发
    "focus_fire_boss",          # 集火 Boss
    "retreat_and_survive",      # 撤离保命
    "follow_player",            # 跟随玩家
]

Strength = Literal["unspecified", "minor", "major"]
ResourceConservation = Literal["normal", "conservative", "aggressive"]
Timing = Literal["immediate", "on_condition", "when_possible"]


class IntentPreferences(BaseModel):
    strength: Strength = "unspecified"
    resource_conservation: ResourceConservation = "normal"


class TacticalIntent(BaseModel):
    intent_id: IntentId
    target_id: str = ""
    timing: Timing = "immediate"
    preferences: IntentPreferences = Field(default_factory=IntentPreferences)
    normalized_text: str = ""
    parse_confidence: float = Field(default=1.0, ge=0, le=1)
