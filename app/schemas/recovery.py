"""Read-only authoritative recovery facts; no executable suggestions."""
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.memory import MemorySnapshot
from app.schemas.relationship import RelationshipState
from app.schemas.scoped import ScopedModel, ScopedNpcScope, ScopedExecutionReceipt
from app.schemas.tactical_execution import ReceiptResult


class RecoveryBase(ScopedModel):
    protocol_version: Literal["0.4"]
    scope: ScopedNpcScope
    service_instance_id: UUID
    state_version: int = Field(ge=0, strict=True)


class RecoveryMemorySnapshot(MemorySnapshot):
    model_config = {"extra": "forbid"}


class RecoveryStateResponse(RecoveryBase):
    save_generation: UUID
    memory_epoch: UUID
    memory: RecoveryMemorySnapshot
    relationship: RelationshipState | None


class RecoveryOperationResponse(RecoveryBase):
    request_id: UUID
    operation: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9-]*$")
    run_id: UUID
    state: Literal["running", "complete", "failed", "unknown", "cancelled"]
    confirmed_version: int | None = Field(default=None, ge=0, strict=True)
    origin_service_instance_id: UUID
    reason_code: str | None = None


class RecoveryDirectiveResponse(RecoveryBase):
    directive_id: UUID
    origin_request_id: UUID
    run_id: UUID
    origin_service_instance_id: UUID
    origin_memory_epoch: UUID
    state: Literal["issued", "accepted", "executed", "rejected", "expired", "cancelled", "unknown"]
    last_result: ReceiptResult | None
    terminal: bool
    sequence: int | None = Field(default=None, ge=0, strict=True)
    receipt_count: int = Field(ge=0, strict=True)


class RecoveryReceiptsRequest(ScopedModel):
    protocol_version: Literal["0.4"]
    request_id: UUID
    save_id: UUID
    companion_id: str
    origin_run_id: UUID
    origin_memory_epoch: UUID
    save_generation: UUID
    expected_state_version: int = Field(ge=0, strict=True)
    receipts: list[ScopedExecutionReceipt] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _associations(self):
        for receipt in self.receipts:
            if receipt.request_id is None or receipt.agent_id != self.companion_id:
                raise ValueError("Historical receipts require the original request and agent")
        return self


class RecoveryReceiptsResponse(RecoveryBase):
    request_id: UUID
    origin_run_id: UUID
    stored: int = Field(ge=0, strict=True)
    duplicate: bool
