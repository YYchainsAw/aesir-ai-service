"""v0.4 JSON 边界：可信归属→显式绑定→预算/去重→共享业务→最终屏障。"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import get_settings
from app.scoped.context import RequestScope, safe_segment, use_scope
from app.scoped.directives import registry
from app.scoped.errors import ScopeError
from app.scoped.identity import Principal, get_principal, resolve_npc_scope
from app.scoped.idempotency import get_request_store, get_event_store
from app.scoped.runtime import get_runtime
from app.scoped.storage import commit_guard, memory_epoch, reset_memory
from app.scoped.timing import TimingBudget, current_budget
from app.schemas.scoped import (
    BindRunRequest, EndRunRequest, EncounterControlRequest, ScopedAgentRequest,
    ScopedChatRequest, ScopedWorldEventRequest, ScopedExecutionRequest, ScopedResetRequest,
    ScopedContextResponse, ScopedControlResponse, ScopedAgentResponse,
    ScopedChatResponse, ScopedWorldEventResponse, ScopedExecutionResponse, ScopedResetResponse, ScopedConsoleStateResponse, ScopedMemoryViewResponse,
)

router = APIRouter(prefix="/v1/scoped", tags=["scoped-v0.4"])


@dataclass(frozen=True)
class _SaveScope:
    game_id: str
    player_id: UUID
    save_id: UUID

    @property
    def key(self):
        return self.game_id, str(self.player_id), str(self.save_id)

    def as_dict(self):
        return dict(zip(("game_id", "player_id", "save_id"), self.key))


def _save(principal, save_id):
    if save_id not in principal.save_ids:
        raise ScopeError(403, "SCOPE_FORBIDDEN", "The save is not owned by this player")
    try:
        game_id = safe_segment(get_settings().game_id)
    except ValueError as error:
        raise ScopeError(503, "STATE_UNAVAILABLE", "Invalid configured game identity") from error
    return _SaveScope(game_id, principal.player_id, save_id)


def _scope(request, principal):
    npc = resolve_npc_scope(principal, request.save_id, request.companion_id)
    return RequestScope(npc, request.run_id, request.session_id,
                        request.service_instance_id, request.run_binding_id,
                        request.memory_epoch, request.encounter_id)


def _base(scope, request_id=None, world=None):
    result = {
        "protocol_version": "0.4", "scope": scope.npc.as_dict(),
        "service_instance_id": str(scope.service_instance_id), "run_id": str(scope.run_id),
        "run_binding_id": str(scope.run_binding_id), "memory_epoch": str(scope.memory_epoch),
        "session_id": str(scope.session_id),
        "encounter_id": str(scope.encounter_id) if scope.encounter_id else None,
        "used_snapshot_id": world.snapshot_id if world else None,
    }
    if request_id is not None:
        result["request_id"] = str(request_id)
    budget = current_budget()
    if budget:
        result["timing"] = {"valid_for_ms": budget.valid_for_ms}
    return result


def _execute(request, principal, operation, action):
    scope = _scope(request, principal)
    timing = getattr(request, "timing", None)
    # 初次校验发生在占位前；最终校验在各副作用以及缓存回放前再次进行。
    with use_scope(scope):
        with commit_guard(scope):
            pass
        budget = TimingBudget(timing, has_snapshot=getattr(request, "world_context", None) is not None) if timing else None

        def validate():
            with commit_guard(scope):
                pass

        def invoke():
            try:
                return action(scope)
            except HTTPException as error:
                code = "HEARTBEAT_RATE_LIMITED" if error.status_code == 429 else "BUSINESS_REJECTED"
                raise ScopeError(error.status_code, code, str(error.detail), request.request_id) from error

        return get_request_store().execute(
            (*scope.key, operation, str(request.request_id)), request, invoke,
            validate=validate, timing=budget, request_id=request.request_id,
            propagate_not_started=(operation == "event"),
        )


def _directive(scope, request, directive):
    if directive is None:
        return None
    data = directive.model_dump(mode="json") if hasattr(directive, "model_dump") else dict(directive)
    data["protocol_version"] = "0.4"
    budget = current_budget()
    expires = data["expires"]
    if budget and expires["type"] == "before_seconds":
        budget.limit_validity(int(expires["remaining_seconds"] * 1000))
    registry.register(scope, request.request_id, data)
    return data


@router.get("/context", response_model=ScopedContextResponse)
def context(save_id: UUID, companion_id: str, principal: Principal = Depends(get_principal)):
    npc = resolve_npc_scope(principal, save_id, companion_id)
    with get_runtime().lock:
        return {"protocol_version": "0.4", "scope": npc.as_dict(),
                **get_runtime().context(npc), "memory_epoch": memory_epoch(npc)}


@router.post("/runs/bind", response_model=ScopedControlResponse)
def bind_run(request: BindRunRequest, principal: Principal = Depends(get_principal)):
    scope = _save(principal, request.save_id)
    result = get_runtime().bind_run(scope, **request.model_dump(exclude={"protocol_version", "save_id"}))
    return {"protocol_version": "0.4", "request_id": request.request_id, "scope": scope.as_dict(), **result}


@router.post("/runs/end", response_model=ScopedControlResponse)
def end_run(request: EndRunRequest, principal: Principal = Depends(get_principal)):
    scope = _save(principal, request.save_id)
    result = get_runtime().end_run(scope, **request.model_dump(exclude={"protocol_version", "save_id"}))
    return {"protocol_version": "0.4", "request_id": request.request_id, "scope": scope.as_dict(), **result}


@router.post("/encounters/control", response_model=ScopedControlResponse)
def control_encounter(request: EncounterControlRequest, principal: Principal = Depends(get_principal)):
    scope = _save(principal, request.save_id)
    result = get_runtime().control_encounter(scope, **request.model_dump(exclude={"protocol_version", "save_id"}))
    return {"protocol_version": "0.4", "request_id": request.request_id, "scope": scope.as_dict(), **result}


@router.post("/agent/step", response_model=ScopedAgentResponse)
def agent_step(request: ScopedAgentRequest, principal: Principal = Depends(get_principal)):
    from app.api.v1.agent import agent_step as legacy_step
    from app.schemas.agent_step import AgentStepRequest

    def run(scope):
        legacy = AgentStepRequest(request_id=request.request_id, companion_id=request.companion_id,
                                  world_context=request.world_context, text=request.text,
                                  session_id=str(request.session_id))
        output = legacy_step(legacy).model_dump(mode="json")
        directive = _directive(scope, request, output.pop("directive"))
        output.pop("protocol_version")
        output.pop("companion_id")
        return {**output, **_base(scope, request.request_id, request.world_context), "directive": directive}
    return _execute(request, principal, "agent-step", run)


@router.post("/companion/chat", response_model=ScopedChatResponse)
def chat(request: ScopedChatRequest, principal: Principal = Depends(get_principal)):
    from app.schemas.companion_dialogue import CompanionDialogueRequest
    from app.services.companion.dialogue_service import create_dialogue_reply

    def run(scope):
        legacy = CompanionDialogueRequest(companion_id=request.companion_id, text=request.text,
                                          game_state=request.game_state, session_id=str(request.session_id),
                                          world_context=request.world_context)
        output = create_dialogue_reply(legacy).model_dump(mode="json")
        output.pop("protocol_version", None)
        output.pop("companion_id", None)
        return {**output, **_base(scope, request.request_id, request.world_context)}
    return _execute(request, principal, "chat", run)


def _event_directive(response):
    from app.schemas.directives.common import DirectiveEnvelope
    from app.api.v1.agent import _COMBAT_ACTION_TYPE
    action = response.companion_action
    if action is None or action.type not in ("cast_ability", "follow", "retreat"):
        return None
    kind = action.type if action.type in ("follow", "retreat") else _COMBAT_ACTION_TYPE.get((action.ability_id or "").rsplit(".", 1)[-1], "")
    # 未有同义映射的旧建议仅保留reaction，绝不编造新动作。
    if not kind:
        return None
    expires = action.expires.model_dump(exclude_none=True)
    return DirectiveEnvelope(
        directive_id=UUID(action.order_id), agent_id=action.agent_id, domain="combat",
        action_type=kind, priority=action.priority, expires=expires, source="event",
        reason_codes=response.observability.reason_codes,
        policy_revision=response.observability.policy_revision,
        payload={k: v for k, v in {"ability_id": action.ability_id, "target_id": action.target_id}.items() if v},
    )


@router.post("/combat/events", response_model=ScopedWorldEventResponse)
@router.post("/world/events", response_model=ScopedWorldEventResponse)
def world_event(request: ScopedWorldEventRequest, principal: Principal = Depends(get_principal)):
    from app.api.v1.world import report_world_event
    from app.schemas.world_event import WorldEventRequest

    def run(scope):
        def produce():
            legacy = WorldEventRequest(request_id=str(request.request_id), companion_id=request.companion_id,
                                       event=request.event, world_context=request.world_context)
            response = report_world_event(legacy)
            directive = _directive(scope, request, _event_directive(response))
            output = response.model_dump(mode="json", exclude={"protocol_version", "companion_id", "request_id", "companion_action"})
            return {**output, "action": "directive" if directive else "none", "directive": directive,
                    "_origin_request_id": str(request.request_id),
                    "_timing": {"valid_for_ms": current_budget().valid_for_ms}}
        payload = request.model_dump(mode="json", exclude={"request_id"})
        result = get_event_store().execute(
            (*scope.key, str(scope.encounter_id or ""), request.event.event_id), payload, produce,
            validate=lambda: _validate(scope), timing=current_budget(), request_id=request.request_id,
            conflict_code="EVENT_ID_CONFLICT",
        )
        origin = result.pop("_origin_request_id")
        original_timing = result.pop("_timing")
        if origin != str(request.request_id):
            # A new logical request has no first-send clock for the old directive.
            # Replay the fact, never give the original action a fresh clock.
            result.update(action="none", directive=None, duplicate=True)
            result["observability"]["reason_codes"].append("EVENT_ALREADY_PROCESSED")
        return {**result, **_base(scope, request.request_id, request.world_context), "timing": original_timing}
    return _execute(request, principal, "event", run)


def _validate(scope):
    with commit_guard(scope):
        pass


@router.post("/tactical/executions", status_code=202, response_model=ScopedExecutionResponse)
def execution(request: ScopedExecutionRequest, principal: Principal = Depends(get_principal)):
    def run(scope):
        return {**_base(scope, request.request_id), "stored": registry.record(scope, request.all_receipts)}
    return _execute(request, principal, "executions", run)


def _query_scope(save_id, companion_id, run_id, run_binding_id, service_instance_id,
                 memory_epoch_value, session_id, encounter_id, principal):
    npc = resolve_npc_scope(principal, save_id, companion_id)
    return RequestScope(npc, run_id, session_id or run_id, service_instance_id, run_binding_id,
                        memory_epoch_value, encounter_id)


@router.get("/console/state", response_model=ScopedConsoleStateResponse)
@router.get("/console/memory", response_model=ScopedMemoryViewResponse)
def console_view(
    request: Request, save_id: UUID, companion_id: str, run_id: UUID, run_binding_id: UUID, service_instance_id: UUID,
    memory_epoch_value: UUID = Query(alias="memory_epoch"), session_id: UUID | None = None,
    encounter_id: UUID | None = None, principal: Principal = Depends(get_principal),
):
    from app.api.v1.console import console_state, view_memory
    scope = _query_scope(save_id, companion_id, run_id, run_binding_id, service_instance_id,
                         memory_epoch_value, session_id, encounter_id, principal)
    with use_scope(scope), commit_guard(scope):
        output = (view_memory if request.url.path.endswith("/memory") else console_state)(companion_id)
        data = output.model_dump(mode="json", exclude={"companion_id"})
        return {**data, **_base(scope)}


@router.post("/console/memory/reset", response_model=ScopedResetResponse)
def memory_reset(request: ScopedResetRequest, principal: Principal = Depends(get_principal)):
    scope = _scope(request, principal)
    with use_scope(scope):
        def run():
            with commit_guard(scope):
                result = reset_memory(scope.npc, scope.memory_epoch)
                return {**_base(scope, request.request_id), "memory_epoch": str(result["memory_epoch"]),
                        "reset": True, "cleared_sessions": result["cleared_sessions"]}
        # reset 回放允许请求的旧epoch，但仅可返回本次reset产生且仍为当前的epoch。
        result = get_request_store().execute(
            (*scope.key, "memory-reset", str(request.request_id)), request, run,
            validate=lambda: get_runtime().validate_binding(scope), request_id=request.request_id,
        )
        with get_runtime().guard(scope):
            if str(memory_epoch(scope.npc)) != result["memory_epoch"]:
                raise ScopeError(409, "MEMORY_EPOCH_STALE", "Another reset superseded the original reset")
        return result
