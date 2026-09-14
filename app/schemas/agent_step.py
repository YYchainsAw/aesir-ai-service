"""主入口 ``/v1/agent/step`` 的请求/响应（SDD T008 / FR-021）。

心跳与指令统一处理：UE 每个逻辑帧/固定间隔携带世界快照调用本端点；
服务基于快照判断是否需要产出指令（自主行为），或处理玩家文本指令。
系统 MUST NOT 主动向客户端推送——一切产出都经本入口的响应返回。

Phase 2 只跑通骨架（空动作路径，T018）；场景判定、仲裁与指令目录在
Phase 5（T050~T054）接入，对话/记忆在 Phase 3（T028）接入。
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.directives.common import DirectiveEnvelope
from app.schemas.world_context import WorldContext

PROTOCOL_VERSION = "0.3"


class AgentStepRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["0.3"] = PROTOCOL_VERSION
    request_id: UUID
    companion_id: str
    world_context: WorldContext
    text: str | None = Field(default=None, min_length=1, max_length=500, description="玩家文本指令；缺省即纯心跳")
    session_id: str | None = Field(default=None, max_length=128)


class AgentStepObservability(BaseModel):

    model_config = ConfigDict(extra="forbid")
    source: Literal["rule", "llm", "rule_fallback"] = "rule"
    reason_codes: list[str] = Field(default_factory=list)
    policy_revision: str = ""
    used_snapshot_id: str = ""
    degraded: bool = False  # 任一子系统降级时为 true（章程原则 V）


class AgentStepResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["0.3"] = PROTOCOL_VERSION
    request_id: UUID
    companion_id: str
    action: Literal["none", "directive"] = "none"   # none = 空动作轻量返回
    directive: DirectiveEnvelope | None = None
    reply_text: str = ""                             # 无表现块时的简短文本（如澄清请求）
    observability: AgentStepObservability
