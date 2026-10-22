"""Strict additive v0.4 offline fact confirmation; no commands or snapshots."""
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.relationship import RelationshipState
from app.schemas.scoped import ScopedModel, ScopedNpcScope, ScopedWorldEvent

MAX_FACTS = 100
_COMBAT_EVENTS = {"player_hp_critical", "boss_stun_near", "boss_stunned", "boss_enraged", "companion_mp_low", "boss_defeated"}

RelationshipStatus = Literal["processed", "scored", "cooldown_blocked", "daily_cap", "clamped_zero", "unknown_event", "skipped"]
MemoryStatus = Literal["processed", "recorded", "not_applicable", "skipped_reset", "not_applied_missing_context"]


class SyncFact(ScopedModel):
    origin_run_id: UUID
    origin_encounter_id: UUID | None = None
    origin_memory_epoch: UUID
    source: Literal["ue"]
    event: ScopedWorldEvent

    @field_validator("event")
    @classmethod
    def bounded_event(cls, value):
        if len(json.dumps(value.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")) > 16384:
            raise ValueError("Fact event exceeds the sync item limit")
        return value

    @model_validator(mode="after")
    def combat_origin(self):
        if self.event.event_type in _COMBAT_EVENTS and self.origin_encounter_id is None:
            raise ValueError("Combat fact requires its original encounter")
        return self


class SyncFactsRequest(ScopedModel):
    protocol_version: Literal["0.4"]
    request_id: UUID
    save_id: UUID
    companion_id: str
    save_generation: UUID
    expected_state_version: int = Field(ge=0, strict=True)
    facts: list[SyncFact] = Field(min_length=1, max_length=MAX_FACTS)

    @model_validator(mode="after")
    def unique_fact_identities(self):
        identities = [(fact.origin_run_id, fact.origin_encounter_id, fact.event.event_id) for fact in self.facts]
        if len(set(identities)) != len(identities):
            raise ValueError("A sync batch cannot contain repeated fact identities")
        return self


class SyncStateResponse(ScopedModel):
    protocol_version: Literal["0.4"] = "0.4"
    scope: ScopedNpcScope
    save_generation: UUID
    memory_epoch: UUID
    state_version: int = Field(ge=0, strict=True)
    relationship: RelationshipState


class SyncFactAcknowledgement(ScopedModel):
    event_id: UUID
    duplicate: bool
    relationship_status: RelationshipStatus
    relationship_delta: int = Field(strict=True)
    memory_status: MemoryStatus
    confirmed_version: int = Field(ge=0, strict=True)


class SyncFactsResponse(ScopedModel):
    protocol_version: Literal["0.4"] = "0.4"
    request_id: UUID
    scope: ScopedNpcScope
    save_generation: UUID
    memory_epoch: UUID
    state_version: int = Field(ge=0, strict=True)
    acknowledgements: list[SyncFactAcknowledgement]
