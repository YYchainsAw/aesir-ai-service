"""Tactical order schemas shared by API routes and services.

契约为《docs/UE5-协议格式契约-v0.1.md》：``order`` 按 ``intent`` 判别，
``when``/``then``/``expires`` 各按 ``type`` 判别。所有 ID 来自请求
``context`` 的能力目录，杜绝显示名/硬编码出协议。``ParseCommandResponse``
携带 ``request_id``(回显) 与生成的 ``order_id``，便于跨端日志关联；同时
保留 ``source``(后端来源) 与 ``companion_reply``(队友确认回应，人设配置生成)。
"""

from typing import Annotated, Literal, TypeAlias, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "0.1"

# ---------------------------------------------------------------------------
# 请求：携带玩家文本与 UE 能力目录
# ---------------------------------------------------------------------------
class ContextAgent(BaseModel):

    model_config = ConfigDict(extra="forbid")
    id: str
    ability_ids: list[str]


class ParseCommandContext(BaseModel):

    model_config = ConfigDict(extra="forbid")
    catalog_revision: str = "dev-001"
    locale: str = "zh-CN"
    agents: list[ContextAgent]
    target_selectors: list[str]
    state_tags: list[str]


class ParseCommandRequest(BaseModel):
    protocol_version: Literal["0.1"] = PROTOCOL_VERSION
    request_id: UUID
    text: str = Field(min_length=1, max_length=500, description="玩家自然语言指令")
    context: ParseCommandContext


# 默认上下文：供遗留 /parse-command 在缺省 context 时回填，
# 保持旧客户端（只传 text）仍可用。
DEFAULT_CONTEXT = ParseCommandContext(
    catalog_revision="dev-001",
    locale="zh-CN",
    agents=[
        ContextAgent(
            id="companion.alice",
            ability_ids=["ability.alice.explosion", "ability.alice.basic_attack"],
        )
    ],
    target_selectors=["encounter.primary_hostile", "party.player"],
    state_tags=["state.stunned", "state.phase_two"],
)

# ---------------------------------------------------------------------------
# 引用对象：允许 then.target 引用已解析的 when.subject（契约 §7.2）
# ---------------------------------------------------------------------------
class TargetRef(BaseModel):

    model_config = ConfigDict(extra="forbid")
    ref: Literal["when.subject"]


# ---------------------------------------------------------------------------
# when 判别联合（v0.1 只交付 state_entered）
# ---------------------------------------------------------------------------
class WhenStateEntered(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["state_entered"] = "state_entered"
    subject: str
    tag: str


When: TypeAlias = Annotated[WhenStateEntered, Field(discriminator="type")]

# ---------------------------------------------------------------------------
# then 判别联合（与既有动作词表一比一映射）
# ---------------------------------------------------------------------------
class CastAbilityAction(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["cast_ability"] = "cast_ability"
    ability_id: str
    target: str | TargetRef


class HoldAbilityAction(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["hold_ability"] = "hold_ability"
    ability_id: str
    active: bool = True


class SetPriorityAction(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["set_priority"] = "set_priority"
    mode: Literal["basic_attack_first", "ability_first"] = "basic_attack_first"


class FollowAction(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["follow"] = "follow"
    target: str
    keep_distance: bool = True


class RetreatAction(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["retreat"] = "retreat"


Then: TypeAlias = Annotated[
    Union[
        CastAbilityAction,
        HoldAbilityAction,
        SetPriorityAction,
        FollowAction,
        RetreatAction,
    ],
    Field(discriminator="type"),
]

# ---------------------------------------------------------------------------
# expires 判别联合（v0.1 只交付 encounter_end）
# ---------------------------------------------------------------------------
class ExpiresEnd(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["encounter_end"] = "encounter_end"


Expires: TypeAlias = Annotated[ExpiresEnd, Field(discriminator="type")]

# ---------------------------------------------------------------------------
# order 判别联合（按 intent）
# ---------------------------------------------------------------------------
class _OrderBase(BaseModel):

    model_config = ConfigDict(extra="forbid")
    order_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    priority: int = Field(50, ge=0, le=100)
    expires: Expires = ExpiresEnd()


class ConditionalCast(_OrderBase):
    """1. 艾莉，等 Boss 眩晕时使用爆裂魔法。"""

    intent: Literal["conditional_cast"] = "conditional_cast"
    when: WhenStateEntered
    then: CastAbilityAction


class HoldAbility(_OrderBase):
    """2. 艾莉，保留爆裂魔法。"""

    intent: Literal["hold_ability"] = "hold_ability"
    when: None = None
    then: HoldAbilityAction


class PrioritizeAttack(_OrderBase):
    """3. 艾莉，优先普通攻击。"""

    intent: Literal["prioritize_attack"] = "prioritize_attack"
    when: None = None
    then: SetPriorityAction


class FollowKeepDistance(_OrderBase):
    """4. 艾莉，跟随我并保持距离。"""

    intent: Literal["follow_keep_distance"] = "follow_keep_distance"
    when: None = None
    then: FollowAction


class Retreat(_OrderBase):
    """5. 艾莉，撤退并优先保命。"""

    intent: Literal["retreat"] = "retreat"
    when: None = None
    then: RetreatAction


TacticalOrder: TypeAlias = Annotated[
    Union[
        ConditionalCast,
        HoldAbility,
        PrioritizeAttack,
        FollowKeepDistance,
        Retreat,
    ],
    Field(discriminator="intent"),
]

# ---------------------------------------------------------------------------
# 响应
# ---------------------------------------------------------------------------
class ParseCommandResponse(BaseModel):
    """契约响应。``extra=forbid`` 拒绝 LLM 或调用方传入的未声明字段。"""

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["0.1"] = PROTOCOL_VERSION
    request_id: UUID | None = None  # 回显客户端 request_id；遗留/直接调用缺省时可为空。
    recognized: bool
    message: str
    order: TacticalOrder | None = None
    source: Literal["rule", "llm", "rule_fallback"] = "rule"
    companion_reply: "TacticalAcknowledgement | None" = None


class TacticalAcknowledgement(BaseModel):

    model_config = ConfigDict(extra="forbid")
    """队友对已接受战术命令的短回应，由人设配置生成。"""

    reply_text: str
    emotion_id: str