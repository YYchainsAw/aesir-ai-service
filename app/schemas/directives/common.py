"""单一指令体系的共享字段（SDD 章程原则 VI / FR-045，T006）。

所有下发指令共用同一信封：唯一标识、目标角色、所属活动域、优先级、有效期、
来源、依据说明与表现块。具体行为类型按活动域在 ``combat.py`` / ``movement.py``
等分文件定义（T049），判别字段挂在本模块声明的联合上。

与 v0.1 ``TacticalOrder`` 的关系：v0.1 端点与格式保持不变；本体系是 v0.3 的
统一信封，``TacticalOrder`` 的语义将迁移并入（见 ue-protocol-contract-v0.1.md
头部「演进方向」）。
"""

from typing import Annotated, Literal, TypeAlias, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

DIRECTIVE_PROTOCOL_VERSION = "0.3"

# 活动域（FR-019，与 data/policy/agency_policy.yaml 的 domains 一致）
DirectiveDomain = Literal["combat", "exploration", "camp", "conversation", "idle"]


# ---------------------------------------------------------------------------
# 有效期判别联合
# ---------------------------------------------------------------------------
class ExpiresImmediate(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["immediate"] = "immediate"


class ExpiresAtEncounterEnd(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["encounter_end"] = "encounter_end"


class ExpiresBeforeSeconds(BaseModel):

    model_config = ConfigDict(extra="forbid")
    type: Literal["before_seconds"] = "before_seconds"
    remaining_seconds: float = Field(ge=0)


DirectiveExpires: TypeAlias = Annotated[
    Union[ExpiresImmediate, ExpiresAtEncounterEnd, ExpiresBeforeSeconds],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# 表现块：台词 + 表现 ID 白名单（人设 YAML 校验）+ 可打断标记
# ---------------------------------------------------------------------------
class DirectivePresentation(BaseModel):
    """NPC 输出的表现层载荷；表现 ID 必须来自角色配置的白名单。"""

    model_config = ConfigDict(extra="forbid")
    reply_text: str = Field(min_length=1, max_length=500)
    emotion_id: str
    gesture_id: str = ""
    facial_expression_id: str = ""
    interruptible: bool = True
    gaze_target_id: str | None = None  # 注视目标（T055）；须为快照中出现过的 ID


# ---------------------------------------------------------------------------
# 统一信封
# ---------------------------------------------------------------------------
class DirectiveEnvelope(BaseModel):
    """一切下发指令的统一信封（FR-040：只允许引用本次上下文出现过的 ID）。"""

    model_config = ConfigDict(extra="forbid")

    directive_id: UUID = Field(default_factory=uuid4)
    agent_id: str                        # 目标角色（如 companion.alice）
    domain: DirectiveDomain              # 所属活动场景
    action_type: str                     # 行为类型；具体取值由各域文件声明（T049）
    priority: int = Field(default=50, ge=0, le=100)
    expires: DirectiveExpires = ExpiresImmediate()
    source: Literal["player_command", "autonomy", "event", "fallback"] = "player_command"
    reason_codes: list[str] = Field(default_factory=list)  # 可解释依据（章程原则 V）
    policy_revision: str = ""             # 产出该指令的策略版本（归因用）
    payload: dict[str, str] = Field(default_factory=dict)  # 域特定参数（扁平字符串，便于 UE 映射）
    presentation: DirectivePresentation | None = None
