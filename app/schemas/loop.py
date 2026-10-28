"""Additive v0.4 request control and read-only execution-loop views."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.scoped import _NpcRequest, ScopedReadResponseBase, ScopedResponseBase
from app.schemas.tactical_execution import ReceiptResult

LoopOperation = Literal["chat", "agent-step"]
RequestState = Literal[
    "queued", "running", "completed", "cancelled", "expired", "failed", "unknown",
]
DirectiveState = Literal[
    "issued", "accepted", "executed", "rejected", "expired", "cancelled", "unknown",
]


class ScopedCancelRequest(_NpcRequest):
    """Cancel a known logical request without changing its original payload."""

    target_request_id: UUID
    operation: LoopOperation
    reason_code: Literal["USER_CANCELLED", "SUPERSEDED"] = "USER_CANCELLED"


class ScopedCancelResponse(ScopedResponseBase):
    target_request_id: UUID
    operation: LoopOperation
    state: RequestState
    cancel_requested: bool
    reason_code: str | None = None


class ScopedRequestStatusResponse(ScopedReadResponseBase):
    """Observe a known request; ``result`` replays the business payload only when state=completed.

    异步化契约 v0.5（阶段 2 第一步）：同步模式下 UE 已从 POST 拿到结果；
    异步模式下轮询本端点，completed 时 ``result`` 与原同步响应逐字段相同。
    queued/running/failed/cancelled/unknown 时为 None。

    ``completed_at`` 是阶段 2 v0.5 预留的 UTC 墙钟（ISO8601）：默认 None，
    开 ``AESIR_SCOPE_ASYNC_COMPLETED_AT=true`` 后 completed 时填值，供 UE 算
    "提交→完成"端到端延迟（SC-011 采样）。其余状态恒为 None。
    """

    target_request_id: UUID
    operation: LoopOperation
    state: RequestState
    reason_code: str | None = None
    queue_ms: int = Field(ge=0, strict=True)
    processing_ms: int = Field(ge=0, strict=True)
    total_ms: int = Field(ge=0, strict=True)
    upstream_attempts: int = Field(ge=0, strict=True)
    cancel_requested: bool
    result: dict | None = None
    completed_at: str | None = None


class ScopedDirectiveStateResponse(ScopedReadResponseBase):
    """Observe a published directive without returning an executable payload.

    unknown means an uncertain receipt write for a known published directive.
    A completely unknown directive ID is a route-level 404 DIRECTIVE_UNKNOWN;
    it must not be represented by inventing an origin request association.
    """

    directive_id: UUID
    origin_request_id: UUID
    state: DirectiveState
    last_result: ReceiptResult | None = None
    terminal: bool
    sequence: int | None = Field(default=None, ge=0, strict=True)
    receipt_count: int = Field(ge=0, strict=True)
