"""v0.2 战术决策 `TacticalDecision` 及 resolve/events 响应信封（草案 §5~§7）。

``decision.status`` 四态：``actionable`` / ``advisory`` / ``not_actionable`` /
``clarification_needed``。``authority`` 标记命令来源（玩家请求或事件策略），
但无论其值是什么，UE 均拥有最终否决权。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.combat_context import CombatContext
from app.schemas.tactical_intent import TacticalIntent

PROTOCOL_VERSION_V02 = "0.2"

DecisionStatus = Literal["actionable", "advisory", "not_actionable", "clarification_needed"]
Authority = Literal["player_requested", "event_policy"]
OrderType = Literal[
    "cast_ability", "hold_ability", "set_priority", "follow", "retreat",
]
ExpiresType = Literal["immediate", "encounter_end", "before_seconds"]


class Expires(BaseModel):
    type: ExpiresType = "encounter_end"
    remaining_seconds: float | None = Field(default=None, ge=0)


class DecisionAction(BaseModel):
    """单个候选动作（v0.2 的 action 信封；order_id 用于 executions 回执关联）。"""

    order_id: str
    agent_id: str
    type: OrderType
    ability_id: str | None = None
    target_id: str | None = None
    priority: int = Field(default=50, ge=0, le=100)
    expires: Expires = Field(default_factory=Expires)
    authority: Authority = "player_requested"


class TacticalDecision(BaseModel):
    decision_id: str
    status: DecisionStatus
    intent_id: str
    action: DecisionAction | None = None
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str = ""


class Observability(BaseModel):
    """排查字段：策略版本与所依据的快照，不参与决策逻辑。"""

    normalized_text: str = ""
    policy_revision: str = ""
    used_snapshot_id: str = ""


class ResolveRequest(BaseModel):
    protocol_version: Literal["0.2"] = PROTOCOL_VERSION_V02
    request_id: str
    intent: TacticalIntent
    combat_context: CombatContext


class TacticalCommandRequest(BaseModel):
    """组合端点 ``/v1/tactical/command`` 请求：文本 + 快照一次到位。

    内部先做 文本 → ``TacticalIntent``（规则 / LLM 后端由 ``AESIR_INTENT_BACKEND``
    决定，LLM 失败回退规则），再走
    resolve 的上下文策略；等价于先调 ``/v1/commands/parse`` 出意图、
    再调 ``/v1/tactical/resolve`` 落地，省一次 UE 往返。
    """

    protocol_version: Literal["0.2"] = PROTOCOL_VERSION_V02
    request_id: str
    text: str = Field(min_length=1)
    combat_context: CombatContext


class ResolveResponse(BaseModel):
    protocol_version: Literal["0.2"] = PROTOCOL_VERSION_V02
    request_id: str
    recognized: bool
    source: str
    decision: TacticalDecision | None = None
    companion_reply: dict | None = None
    observability: Observability | None = None
