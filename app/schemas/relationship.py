"""关系状态模型（SDD T036 / FR-015~FR-016）。

数值 + 阶段 + 近期事件 + 当日净变化（Key Entity「关系状态」）。阶段由
策略表（relationship_policy.yaml）按数值区间划分，本模型只保存结果，
不持有策略——阶段判定入口见 ``app.services.relationship.rules.stage_of``。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 防御性钳制范围（与策略表/配置一致；策略边界由规则层按 YAML 施加）
_VALUE_BOUNDS = (0, 100)


class RelationshipEventRecord(BaseModel):
    """一条已计分的关系事件留痕（可解释，FR-012 同思路）。"""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    occurred_at: str
    delta: int  # 实际计分值（被冷却/日上限拦截时不会留痕）


class RelationshipState(BaseModel):
    """单个 NPC 对玩家的关系状态快照。

    ``daily_net`` 只累计当日**正向**计分（负向不受正向上限约束），
    跨日由规则层重置。越界数值在构造时即钳制（防手改文件产生非法状态）。
    """

    model_config = ConfigDict(extra="forbid")

    value: int = 20
    stage: str = ""               # 由规则层同步（持久化冗余，加载时重算）
    day: str = ""                 # 当日净变化归属日（YYYY-MM-DD，UTC）
    daily_net: int = 0            # 当日正向净变化（正向上限额度已用值）
    recent_events: list[RelationshipEventRecord] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def _clamp_value(cls, v: int) -> int:
        low, high = _VALUE_BOUNDS
        return max(low, min(high, v))
