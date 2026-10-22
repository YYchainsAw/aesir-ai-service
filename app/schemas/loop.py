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
    """Observe a known request; the read does not replay its business result."""

    target_request_id: UUID
    operation: LoopOperation
    state: RequestState
    reason_code: str | None = None
    queue_ms: int = Field(ge=0, strict=True)
    processing_ms: int = Field(ge=0, strict=True)
    total_ms: int = Field(ge=0, strict=True)
    upstream_attempts: int = Field(ge=0, strict=True)
    cancel_requested: bool


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
