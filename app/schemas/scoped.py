"""v0.4 scoped JSON 请求；旧协议模型保持各自的验收边界。"""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.scoped.context import safe_segment
from app.schemas.combat_context import CombatContext, ContextBoss, ContextCompanion, ContextPlayer
from app.schemas.tactical_execution import ReceiptResult
from app.schemas.world_context import WorldContext, WorldInteractable
from app.schemas.world_event import WorldEvent, WorldEventObservability, WorldEventReaction
from app.schemas.agent_step import AgentStepObservability
from app.schemas.directives.common import DirectiveEnvelope

PROTOCOL_VERSION = "0.4"
_COMBAT_EVENTS = frozenset({
    "player_hp_critical", "boss_stun_near", "boss_stunned", "boss_enraged",
    "companion_mp_low", "boss_defeated",
})


def _utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp must be an ISO-8601 UTC datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must include the UTC timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def _uuid_string(value: str) -> str:
    return str(UUID(value))


class ScopedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TimingInput(ScopedModel):
    capture_age_ms: int = Field(ge=0, strict=True)
    request_age_ms: int = Field(ge=0, strict=True)
    max_snapshot_age_ms: int = Field(ge=0, strict=True)
    max_request_age_ms: int = Field(ge=0, strict=True)


class _ControlRequest(ScopedModel):
    protocol_version: Literal["0.4"]
    request_id: UUID
    save_id: UUID
    service_instance_id: UUID


class BindRunRequest(_ControlRequest):
    expected_control_revision: int = Field(ge=0, strict=True)
    expected_run_id: UUID | None
    run_id: UUID


class EndRunRequest(_ControlRequest):
    run_id: UUID
    run_binding_id: UUID
    expected_control_revision: int = Field(ge=0, strict=True)


class EncounterControlRequest(_ControlRequest):
    run_id: UUID
    run_binding_id: UUID
    op: Literal["begin", "end"]
    expected_encounter_revision: int = Field(ge=0, strict=True)
    expected_encounter_id: UUID | None
    encounter_id: UUID | None = None

    @model_validator(mode="after")
    def _operation(self) -> "EncounterControlRequest":
        if self.op == "begin" and self.encounter_id is None:
            raise ValueError("begin requires encounter_id")
        if self.op == "end" and (self.expected_encounter_id is None or self.encounter_id is not None):
            raise ValueError("end requires expected_encounter_id and no new encounter_id")
        return self


class ScopedContextPlayer(ContextPlayer):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ScopedContextCompanion(ContextCompanion):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ScopedContextBoss(ContextBoss):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ScopedCombatContext(CombatContext):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    player: ScopedContextPlayer
    companion: ScopedContextCompanion
    boss: ScopedContextBoss

    _ids = field_validator("encounter_id", "snapshot_id")(_uuid_string)
    _utc_timestamp = field_validator("captured_at")(_utc)


class ScopedWorldInteractable(WorldInteractable):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ScopedWorldContext(WorldContext):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    combat: ScopedCombatContext | None = None
    interactables: list[ScopedWorldInteractable] = Field(default_factory=list)

    _id = field_validator("snapshot_id")(_uuid_string)
    _utc_timestamp = field_validator("captured_at")(_utc)

    @model_validator(mode="after")
    def _combat_snapshot(self) -> "ScopedWorldContext":
        if self.scene == "combat" and self.combat is None:
            raise ValueError("combat scene requires combat context")
        if self.combat is not None:
            if self.scene != "combat":
                raise ValueError("combat context requires combat scene")
            if self.snapshot_id != self.combat.snapshot_id:
                raise ValueError("world and combat snapshot_id must match")
            if self.captured_at != self.combat.captured_at:
                raise ValueError("world and combat captured_at must match")
            if self.player.id != self.combat.player.id:
                raise ValueError("world and combat player must match")
            if self.companion.id != self.combat.companion.id:
                raise ValueError("world and combat companion must match")
        return self


class _NpcRequest(_ControlRequest):
    companion_id: str = Field(min_length=1, max_length=100)
    run_id: UUID
    run_binding_id: UUID
    memory_epoch: UUID
    session_id: UUID | None = None
    encounter_id: UUID | None = None

    _companion = field_validator("companion_id")(safe_segment)

    @model_validator(mode="after")
    def _session(self) -> "_NpcRequest":
        if self.session_id is None:
            self.session_id = self.run_id
        return self


class _RealtimeRequest(_NpcRequest):
    timing: TimingInput

    def _check_world(self, world: ScopedWorldContext | None) -> None:
        if world is None:
            return
        if world.companion.id != self.companion_id:
            raise ValueError("world companion does not match requested companion")
        if self.timing.capture_age_ms < self.timing.request_age_ms:
            raise ValueError("snapshot cannot be captured after the first request")
        if world.combat is not None and str(self.encounter_id) != world.combat.encounter_id:
            raise ValueError("combat encounter must match the request encounter_id")


class ScopedAgentRequest(_RealtimeRequest):
    world_context: ScopedWorldContext
    text: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _context(self) -> "ScopedAgentRequest":
        self._check_world(self.world_context)
        return self


class ScopedChatRequest(_RealtimeRequest):
    text: str = Field(min_length=1, max_length=500)
    game_state: Literal["exploration", "conversation"] = "exploration"
    world_context: ScopedWorldContext | None = None

    @model_validator(mode="after")
    def _context(self) -> "ScopedChatRequest":
        self._check_world(self.world_context)
        return self


class ScopedWorldEvent(WorldEvent):
    event_id: str
    sequence: int = Field(ge=0, strict=True)

    _id = field_validator("event_id")(_uuid_string)
    _utc_timestamp = field_validator("occurred_at")(_utc)


class ScopedWorldEventRequest(_RealtimeRequest):
    event: ScopedWorldEvent
    world_context: ScopedWorldContext

    @model_validator(mode="after")
    def _context(self) -> "ScopedWorldEventRequest":
        self._check_world(self.world_context)
        if self.event.event_type in _COMBAT_EVENTS and self.world_context.combat is None:
            raise ValueError("combat event requires encounter and combat context")
        return self


class ScopedExecutionReceipt(ScopedModel):
    protocol_version: Literal["0.4"]
    order_id: UUID
    result: ReceiptResult
    encounter_id: UUID | None = None
    request_id: UUID | None = None
    reason_code: str = ""
    agent_id: str = ""
    ability_id: str | None = None
    reported_at: str | None = None
    received_at: str | None = None
    policy_revision: str = ""
    sequence: int | None = Field(default=None, ge=0, strict=True)

    @field_validator("reported_at", "received_at")
    @classmethod
    def _timestamps(cls, value: str | None) -> str | None:
        return _utc(value) if value is not None else None


class ScopedExecutionRequest(_NpcRequest):
    receipt: ScopedExecutionReceipt | None = None
    receipts: list[ScopedExecutionReceipt] | None = Field(default=None, min_length=1, max_length=100)

    @property
    def all_receipts(self) -> list[ScopedExecutionReceipt]:
        return [self.receipt] if self.receipt is not None else list(self.receipts or [])

    @model_validator(mode="after")
    def _items(self) -> "ScopedExecutionRequest":
        if (self.receipt is None) == (self.receipts is None):
            raise ValueError("provide exactly one of receipt or receipts")
        for receipt in self.all_receipts:
            if receipt.agent_id and receipt.agent_id != self.companion_id:
                raise ValueError("receipt agent does not match requested companion")
            if receipt.encounter_id != self.encounter_id:
                raise ValueError("receipt encounter does not match request encounter_id")
        return self


class ScopedResetRequest(_NpcRequest):
    pass


class ScopedSaveScope(ScopedModel):
    game_id: str
    player_id: UUID
    save_id: UUID

    _game = field_validator("game_id")(safe_segment)


class ScopedNpcScope(ScopedSaveScope):
    companion_id: str

    _companion = field_validator("companion_id")(safe_segment)


class ScopedTimingResponse(ScopedModel):
    valid_for_ms: int = Field(ge=0, strict=True)


class ScopedResponseBase(ScopedModel):
    protocol_version: Literal["0.4"]
    request_id: UUID
    scope: ScopedNpcScope
    service_instance_id: UUID
    run_id: UUID
    run_binding_id: UUID
    memory_epoch: UUID
    session_id: UUID
    encounter_id: UUID | None = None
    used_snapshot_id: UUID | None = None


class ScopedDirective(DirectiveEnvelope):
    protocol_version: Literal["0.4"]


class ScopedAgentResponse(ScopedResponseBase):
    timing: ScopedTimingResponse
    action: Literal["none", "directive"]
    directive: ScopedDirective | None
    reply_text: str = ""
    observability: AgentStepObservability

    @model_validator(mode="after")
    def _action(self) -> "ScopedAgentResponse":
        if (self.action == "directive") != (self.directive is not None):
            raise ValueError("action and directive must agree")
        if self.directive is not None and self.directive.agent_id != self.scope.companion_id:
            raise ValueError("directive target must match the response scope")
        return self


class ScopedWorldEventResponse(ScopedResponseBase):
    timing: ScopedTimingResponse
    event_id: UUID
    duplicate: bool
    action: Literal["none", "directive"]
    directive: ScopedDirective | None
    reaction: WorldEventReaction | None = None
    recommendation_text: str | None = None
    observability: WorldEventObservability

    @model_validator(mode="after")
    def _action(self) -> "ScopedWorldEventResponse":
        if (self.action == "directive") != (self.directive is not None):
            raise ValueError("action and directive must agree")
        if self.directive is not None and self.directive.agent_id != self.scope.companion_id:
            raise ValueError("directive target must match the response scope")
        return self


class ScopedChatResponse(ScopedResponseBase):
    timing: ScopedTimingResponse
    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool = True
    source: Literal["mock", "llm", "fallback"]
    relationship_stage: str = ""
    relationship_stage_display: str = ""
    relationship_delta: int = 0
    persona_revision: str = ""
    memory_layers: dict[str, int] = Field(default_factory=dict)


class _ScopedControlState(ScopedModel):
    protocol_version: Literal["0.4"]
    scope: ScopedSaveScope
    service_instance_id: UUID
    control_revision: int = Field(ge=0, strict=True)
    run_id: UUID | None
    run_binding_id: UUID | None
    encounter_revision: int = Field(ge=0, strict=True)
    encounter_id: UUID | None

    @model_validator(mode="after")
    def _active_binding(self) -> "_ScopedControlState":
        if (self.run_id is None) != (self.run_binding_id is None):
            raise ValueError("run and binding must both be present or absent")
        if self.encounter_id is not None and self.run_id is None:
            raise ValueError("an encounter requires an active run")
        return self


class ScopedControlResponse(_ScopedControlState):
    request_id: UUID


class ScopedContextResponse(_ScopedControlState):
    scope: ScopedNpcScope
    memory_epoch: UUID


class ScopedExecutionResponse(ScopedResponseBase):
    stored: int = Field(ge=0, strict=True)


class ScopedResetResponse(ScopedResponseBase):
    reset: bool
    cleared_sessions: int = Field(ge=0, strict=True)


class ScopedReadResponseBase(ScopedResponseBase):
    request_id: None = None


class ScopedMemoryEntryView(ScopedModel):
    content: str
    importance: str
    source: str
    real_time: str


class ScopedTopicImpressionView(ScopedModel):
    topic: str
    mention_count: int
    weight: float
    last_seen: str
    origin: str


class ScopedConsoleStateResponse(ScopedReadResponseBase):
    registered_companions: list[str]
    display_name: str
    memory_backend: str
    session_memory_turns: int
    tactical_policy_revision: str
    persona_revision: str
    agency_policy_revision: str
    relationship_stage: str
    relationship_stage_display: str
    relationship_value: float | None
    last_scene: str
    last_emotion_id: str
    last_seen: str
    recent_memory: list[ScopedMemoryEntryView]


class ScopedMemoryViewResponse(ScopedReadResponseBase):
    counts: dict[str, int]
    short_term: list[ScopedMemoryEntryView]
    summaries: list[ScopedMemoryEntryView]
    archive: list[ScopedMemoryEntryView]
    impressions: list[ScopedTopicImpressionView]
