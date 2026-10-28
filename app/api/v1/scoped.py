"""v0.4 JSON 边界：可信归属→显式绑定→预算/去重→共享业务→最终屏障。"""
from dataclasses import dataclass
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from fastapi.responses import JSONResponse

from app.config import get_settings
from app.scoped import async_pool
from app.scoped.context import RequestScope, safe_segment, use_scope
from app.scoped.directives import registry
from app.scoped.errors import ScopeError
from app.scoped.identity import Principal, get_principal, require_permission, resolve_npc_scope
from app.persistence.auth import use_principal, validate_principal, reserve_request_quota
from app.persistence.database import database_enabled, read_document, write_document, state_version
from app.persistence.uow import use_unit_of_work
from app.persistence.journal import (get_durable_request_store, get_durable_event_store, stage_active_result, stage_cancel_target)
from app.schemas.recovery import (RecoveryStateResponse, RecoveryOperationResponse, RecoveryDirectiveResponse,
                                  RecoveryReceiptsRequest, RecoveryReceiptsResponse)
from app.scoped.idempotency import get_request_store, get_event_store
from app.scoped.runtime import get_runtime
from app.scoped.storage import commit_guard, memory_epoch, reset_memory
from app.scoped.timing import TimingBudget, current_budget
from app.scoped.requests import get_coordinator, final_commit
from app.scoped.trace import request_trace
from app.schemas.loop import ScopedCancelRequest, ScopedCancelResponse, ScopedRequestStatusResponse, ScopedDirectiveStateResponse
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
    with use_principal(principal), use_scope(scope), request_trace(scope, operation, request.request_id):
        with commit_guard(scope):
            pass
        budget = TimingBudget(timing, has_snapshot=getattr(request, "world_context", None) is not None) if timing else None

        def validate():
            with commit_guard(scope):
                pass

        def business():
            try:
                if database_enabled():
                    with use_unit_of_work(scope) as unit:
                        result = action(scope)
                        with commit_guard(scope), final_commit():
                            stage_active_result(result)
                            unit.commit()
                        return result
                return action(scope)
            except HTTPException as error:
                code = "HEARTBEAT_RATE_LIMITED" if error.status_code == 429 else "BUSINESS_REJECTED"
                raise ScopeError(error.status_code, code, str(error.detail), request.request_id) from error

        # 阶段 2 v0.5：opt-in 异步提交。仅 chat/agent-step 且 protocol_version="0.5"
        # 进入此分支；其余入口与 "0.4" 请求走同步路径（下方），契约永久保留。
        async_mode = (
            getattr(request, "protocol_version", "0.4") == "0.5"
            and operation in {"chat", "agent-step"}
        )
        if async_mode:
            return _execute_async(
                request, principal, operation, action, scope,
                validate=validate, budget=budget, business=business,
            )

        def invoke():
            reserve_request_quota(principal, scope.npc.game_id)
            if operation in {"chat", "agent-step"}:
                serial = operation == "chat" or request.text is not None
                return get_coordinator().execute(
                    scope, operation, request.request_id, business, serial=serial,
                    budget=current_budget(), validate=validate,
                )
            return business()

        store = get_durable_request_store() if database_enabled() else get_request_store()
        return store.execute(
            (*scope.key, operation, str(request.request_id)), request, invoke,
            validate=validate, timing=budget, request_id=request.request_id,
            propagate_not_started=(operation in {"event", "chat", "agent-step"}),
            on_failure=(
                lambda error: get_coordinator().failure_after_operation(
                    scope, operation, request.request_id, error
                )
            ) if operation in {"chat", "agent-step"} else None,
        )


def _execute_async(request, principal, operation, action, scope, *,
                   validate, budget, business):
    """阶段 2 v0.5：提交线程只做校验/配额/容量准入，立即 202；业务闭包进后台池。

    不做跨进程 work-stealing：闭包只活在接收进程，跨进程只经 Redis 槽位仲裁。
    UE 轮询 ``GET /v1/scoped/requests/{target_request_id}`` 拿终态（completed 时
    ``result`` 与同步响应逐字段相同）。
    """
    reserve_request_quota(principal, scope.npc.game_id)

    key = (*scope.key, operation, str(request.request_id))
    store = get_durable_request_store() if database_enabled() else get_request_store()

    # 容量准入（coordinator 占位入队）：失败抛 NotStartedError -> 503，不登记幂等。
    serial = operation == "chat" or request.text is not None
    queued_state = get_coordinator().submit(
        scope, operation, request.request_id, serial=serial, budget=budget, validate=validate,
    )

    # 幂等账本登记（不等待）：同 request_id 网络重试不重复投递。
    idem_state, replay = store.begin(key, request, timing=budget, request_id=request.request_id)
    if idem_state == "complete":
        # 已完成：直接回放（UE 重试 POST 拿到 200 + 原结果）。
        return replay

    def background_task():
        try:
            result = get_coordinator().run_submitted(
                scope, operation, request.request_id, business,
            )
            store.settle(key, result)
        except Exception as error:  # noqa: BLE001 - 终态已折进 coordinator/journal
            store.settle_failure(key, error)

    # 仅首次登记（accepted）才投递后台。running（同 request_id 网络重试）
    # 时原请求在途，绝不能再投一个闭包——否则两个 worker 会先后占槽把同一
    # 业务 action 跑两遍。重复 POST 直接回 202 当前状态，UE 轮询拿终态。
    if idem_state == "accepted":
        async_pool.submit(background_task)

    # 202 受理信封：不含业务结果；state 只能是 queued/running。
    # _base 读 current_budget() 取 valid_for_ms——提交线程内需先包进 contextvar
    # （后台池跑业务时由 coordinator.run_submitted 自行管理 budget context）。
    from app.scoped.timing import use_budget
    with use_budget(budget):
        envelope = {
            **_base(scope, request.request_id, getattr(request, "world_context", None)),
            "protocol_version": "0.5",
            "state": queued_state,
        }
    return JSONResponse(status_code=202, content=envelope)


def _directive(scope, request, directive):
    if directive is None:
        return None
    data = directive.model_dump(mode="json") if hasattr(directive, "model_dump") else dict(directive)
    data["protocol_version"] = "0.4"
    budget = current_budget()
    expires = data["expires"]
    if budget and expires["type"] == "before_seconds":
        budget.limit_validity(int(expires["remaining_seconds"] * 1000))
    with commit_guard(scope), final_commit():
        registry.register(scope, request.request_id, data)
    return data


@router.get("/context", response_model=ScopedContextResponse)
def context(save_id: UUID, companion_id: str, principal: Principal = Depends(require_permission("npc:use"))):
    npc = resolve_npc_scope(principal, save_id, companion_id)
    with use_principal(principal), get_runtime().lock:
        validate_principal(principal, npc)
        return {"protocol_version": "0.4", "scope": npc.as_dict(),
                **get_runtime().context(npc), "memory_epoch": memory_epoch(npc)}


@router.post("/runs/bind", response_model=ScopedControlResponse)
def bind_run(request: BindRunRequest, principal: Principal = Depends(require_permission("npc:use"))):
    scope = _save(principal, request.save_id)
    with use_principal(principal), get_runtime().lock:
        validate_principal(principal, scope)
        reserve_request_quota(principal, scope.game_id)
        if database_enabled():
            from app.persistence.sync import get_save_generation
            generation = get_save_generation(scope)
            history_key = (*scope.key, str(request.run_id))
            history = read_document("run-history", history_key)
            if history is not None and history["generation"] != str(generation):
                raise ScopeError(409, "SAVE_GENERATION_STALE", "A historical run cannot enter a different save generation")
        result = get_runtime().bind_run(scope, **request.model_dump(exclude={"protocol_version", "save_id"}))
        if database_enabled():
            write_document("run-history", history_key,
                           {"run_id": str(request.run_id), "generation": str(generation)}, scope_parts=scope.key)
        return {"protocol_version": "0.4", "request_id": request.request_id, "scope": scope.as_dict(), **result}


@router.post("/runs/end", response_model=ScopedControlResponse)
def end_run(request: EndRunRequest, principal: Principal = Depends(require_permission("npc:use"))):
    scope = _save(principal, request.save_id)
    with use_principal(principal), get_runtime().lock:
        validate_principal(principal, scope)
        reserve_request_quota(principal, scope.game_id)
        result = get_runtime().end_run(scope, **request.model_dump(exclude={"protocol_version", "save_id"}))
        return {"protocol_version": "0.4", "request_id": request.request_id, "scope": scope.as_dict(), **result}


@router.post("/encounters/control", response_model=ScopedControlResponse)
def control_encounter(request: EncounterControlRequest, principal: Principal = Depends(require_permission("npc:use"))):
    scope = _save(principal, request.save_id)
    with use_principal(principal), get_runtime().lock:
        validate_principal(principal, scope)
        reserve_request_quota(principal, scope.game_id)
        result = get_runtime().control_encounter(scope, **request.model_dump(exclude={"protocol_version", "save_id"}))
        if database_enabled() and request.op == "begin":
            from app.persistence.sync import get_save_generation
            write_document("encounter-history", (*scope.key, str(request.run_id), str(request.encounter_id)),
                           {"run_id": str(request.run_id), "encounter_id": str(request.encounter_id),
                            "generation": str(get_save_generation(scope))}, scope_parts=scope.key)
        return {"protocol_version": "0.4", "request_id": request.request_id, "scope": scope.as_dict(), **result}


@router.post("/agent/step", response_model=ScopedAgentResponse)
def agent_step(request: ScopedAgentRequest, principal: Principal = Depends(require_permission("npc:use"))):
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
def chat(request: ScopedChatRequest, principal: Principal = Depends(require_permission("npc:use"))):
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
def world_event(request: ScopedWorldEventRequest, principal: Principal = Depends(require_permission("npc:use"))):
    from app.api.v1.world import report_world_event
    from app.schemas.world_event import WorldEventRequest

    def run(scope):
        if database_enabled():
            from app.persistence.sync import lookup_fact
            known = lookup_fact(scope.npc, scope.run_id, scope.encounter_id, request.event,
                                origin_memory_epoch=scope.memory_epoch)
            if known is not None:
                return {**_base(scope, request.request_id, request.world_context),
                        "event_id": request.event.event_id, "duplicate": True,
                        "action": "none", "directive": None, "reaction": None,
                        "recommendation_text": None,
                        "observability": {"source": "rule", "used_snapshot_id": request.world_context.snapshot_id,
                                          "reason_codes": ["FACT_ALREADY_CONFIRMED"]}}

        def produce():
            legacy = WorldEventRequest(request_id=str(request.request_id), companion_id=request.companion_id,
                                       event=request.event, world_context=request.world_context)
            response = report_world_event(legacy)
            directive = _directive(scope, request, _event_directive(response))
            output = response.model_dump(mode="json", exclude={"protocol_version", "companion_id", "request_id", "companion_action"})
            if database_enabled():
                from app.persistence.sync import stage_fact_confirmation
                stage_fact_confirmation(scope.npc, scope.run_id, scope.encounter_id, request.event,
                                        {"relationship_status": "processed",
                                         "relationship_delta": response.observability.relationship_delta,
                                         "memory_status": "processed"},
                                        origin_memory_epoch=scope.memory_epoch, source="ue")
            return {**output, "action": "directive" if directive else "none", "directive": directive,
                    "_origin_request_id": str(request.request_id),
                    "_timing": {"valid_for_ms": current_budget().valid_for_ms}}
        payload = request.model_dump(mode="json", exclude={"request_id"})
        event_store = get_durable_event_store() if database_enabled() else get_event_store()
        result = event_store.execute(
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
def execution(request: ScopedExecutionRequest, principal: Principal = Depends(require_permission("npc:use"))):
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
    encounter_id: UUID | None = None, principal: Principal = Depends(require_permission("console:read")),
):
    from app.api.v1.console import console_state, view_memory
    scope = _query_scope(save_id, companion_id, run_id, run_binding_id, service_instance_id,
                         memory_epoch_value, session_id, encounter_id, principal)
    with use_principal(principal), use_scope(scope), commit_guard(scope):
        output = (view_memory if request.url.path.endswith("/memory") else console_state)(companion_id)
        data = output.model_dump(mode="json", exclude={"companion_id"})
        return {**data, **_base(scope)}


@router.post("/console/memory/reset", response_model=ScopedResetResponse)
def memory_reset(request: ScopedResetRequest, principal: Principal = Depends(require_permission("memory:reset"))):
    scope = _scope(request, principal)
    with use_principal(principal), use_scope(scope):
        def apply_reset():
            with commit_guard(scope):
                result = reset_memory(scope.npc, scope.memory_epoch)
                output = {**_base(scope, request.request_id), "memory_epoch": str(result["memory_epoch"]),
                          "reset": True, "cleared_sessions": result["cleared_sessions"]}
                if database_enabled():
                    # The old epoch was checked on guard entry; the staged
                    # replacement intentionally has a new epoch now.
                    stage_active_result(output)
                    from app.persistence.uow import current_uow
                    current_uow().commit()
                return output

        def run():
            reserve_request_quota(principal, scope.npc.game_id)
            if database_enabled():
                with use_unit_of_work(scope):
                    return apply_reset()
            return apply_reset()
        # reset 回放允许请求的旧epoch，但仅可返回本次reset产生且仍为当前的epoch。
        def validate_reset():
            validate_principal(principal, scope)
            get_runtime().validate_binding(scope)

        reset_store = get_durable_request_store() if database_enabled() else get_request_store()
        result = reset_store.execute(
            (*scope.key, "memory-reset", str(request.request_id)), request, run,
            validate=validate_reset, request_id=request.request_id,
        )
        with get_runtime().guard(scope):
            validate_principal(principal, scope)
            if str(memory_epoch(scope.npc)) != result["memory_epoch"]:
                raise ScopeError(409, "MEMORY_EPOCH_STALE", "Another reset superseded the original reset")
        return result



def read_loop_scope(
    save_id: UUID, companion_id: str, run_id: UUID, run_binding_id: UUID, service_instance_id: UUID,
    memory_epoch_value: UUID = Query(alias="memory_epoch"), session_id: UUID | None = None,
    encounter_id: UUID | None = None, principal: Principal = Depends(require_permission("npc:use")),
):
    with use_principal(principal):
        scope = _query_scope(save_id, companion_id, run_id, run_binding_id, service_instance_id,
                             memory_epoch_value, session_id, encounter_id, principal)
        validate_principal(principal, scope)
        return scope


@router.post("/requests/cancel", response_model=ScopedCancelResponse)
async def cancel_request(request: ScopedCancelRequest, principal: Principal = Depends(require_permission("npc:use"))):
    # A short control path stays outside the worker-bound generation queue.
    def cancel(scope):
        with commit_guard(scope):
            state = get_coordinator().cancel(scope, request.operation, request.target_request_id, request.reason_code)
            if database_enabled() and state["cancel_requested"]:
                stage_cancel_target(scope, request.operation, request.target_request_id)
        fields = {key: state[key] for key in ("target_request_id", "operation", "state", "cancel_requested", "reason_code")}
        return {**_base(scope, request.request_id), **fields}
    return _execute(request, principal, "request-cancel", cancel)


@router.get("/requests/{target_request_id}", response_model=ScopedRequestStatusResponse)
async def request_status(target_request_id: UUID, operation: Literal["chat", "agent-step"],
                         scope: RequestScope = Depends(read_loop_scope),
                         principal: Principal = Depends(require_permission("npc:use"))):
    with use_principal(principal), use_scope(scope), commit_guard(scope):
        return {**_base(scope), **get_coordinator().status(scope, operation, target_request_id)}


@router.get("/directives/{directive_id}", response_model=ScopedDirectiveStateResponse)
async def directive_status(directive_id: UUID, scope: RequestScope = Depends(read_loop_scope),
                           principal: Principal = Depends(require_permission("npc:use"))):
    with use_principal(principal), use_scope(scope), commit_guard(scope):
        return {**_base(scope), **registry.state(scope, directive_id)}



def _recovery_npc(principal, save_id, companion_id):
    if not database_enabled():
        raise ScopeError(404, "RECOVERY_UNAVAILABLE", "Persistent recovery is not enabled")
    npc = resolve_npc_scope(principal, save_id, companion_id)
    validate_principal(principal, npc)
    return npc


def _recovery_base(npc):
    return {"protocol_version": "0.4", "scope": npc.as_dict(),
            "service_instance_id": str(get_runtime().service_instance_id),
            "state_version": state_version(npc.key)}


@router.get("/recovery/state", response_model=RecoveryStateResponse)
def recovery_state(save_id: UUID, companion_id: str,
                   principal: Principal = Depends(require_permission("npc:use"))):
    from app.scoped.storage import scope_lock
    with use_principal(principal):
        npc = _recovery_npc(principal, save_id, companion_id)
        with scope_lock(npc):
            validate_principal(principal, npc)
            memory = read_document("memory", npc.key)
            generation = read_document("save-generation", npc.save_key)
            if memory is None or generation is None:
                raise ScopeError(404, "STATE_UNKNOWN", "No authoritative snapshot has been initialized")
            relationship = read_document("relationship", npc.key)
            return {**_recovery_base(npc), "save_generation": generation["generation"],
                    "memory_epoch": memory["memory_epoch"],
                    "memory": {key: value for key, value in memory.items() if key != "memory_epoch"},
                    "relationship": relationship}


@router.get("/recovery/operations/{request_id}", response_model=RecoveryOperationResponse)
def recovery_operation(request_id: UUID, save_id: UUID, companion_id: str, run_id: UUID,
                       operation: str = Query(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9-]*$"),
                       principal: Principal = Depends(require_permission("npc:use"))):
    from app.scoped.storage import scope_lock
    with use_principal(principal):
        npc = _recovery_npc(principal, save_id, companion_id)
        with scope_lock(npc):
            validate_principal(principal, npc)
            result = get_durable_request_store().recover(npc, run_id, operation, request_id)
            return {**_recovery_base(npc), **result}


@router.get("/recovery/directives/{directive_id}", response_model=RecoveryDirectiveResponse)
def recovery_directive(directive_id: UUID, save_id: UUID, companion_id: str, run_id: UUID,
                       principal: Principal = Depends(require_permission("npc:use"))):
    from app.persistence.directives import sql_registry
    from app.scoped.storage import scope_lock
    with use_principal(principal):
        npc = _recovery_npc(principal, save_id, companion_id)
        with scope_lock(npc):
            validate_principal(principal, npc)
            return {**_recovery_base(npc), **sql_registry.recover(npc, run_id, directive_id)}


@router.post("/recovery/receipts", response_model=RecoveryReceiptsResponse)
def archive_receipts(request: RecoveryReceiptsRequest,
                     principal: Principal = Depends(require_permission("npc:use"))):
    from app.persistence.directives import sql_registry
    from app.scoped.storage import scope_lock
    with use_principal(principal):
        npc = _recovery_npc(principal, request.save_id, request.companion_id)

        def validate_archive():
            validate_principal(principal, npc)

        def apply():
            reserve_request_quota(principal, npc.game_id)
            with scope_lock(npc), use_unit_of_work(npc) as unit:
                validate_archive()
                generation = read_document("save-generation", npc.save_key)
                history = read_document("run-history", (*npc.save_key, str(request.origin_run_id)))
                if generation is None or generation["generation"] != str(request.save_generation):
                    raise ScopeError(409, "SAVE_GENERATION_STALE", "The historical receipt save generation is not current")
                if history is None or history["generation"] != str(request.save_generation):
                    raise ScopeError(409, "ORIGIN_RUN_UNKNOWN", "The original run was not registered for this save generation")
                stored, duplicate = sql_registry.archive(
                    npc, request.origin_run_id, request.origin_memory_epoch, request.receipts,
                    expected_state_version=request.expected_state_version,
                )
                output = {**_recovery_base(npc), "request_id": str(request.request_id),
                          "origin_run_id": str(request.origin_run_id), "stored": stored,
                          "duplicate": duplicate}
                validate_archive()
                stage_active_result(output, confirmed_state_version=True)
                unit.commit()
                return output

        return get_durable_request_store().execute(
            (*npc.key, str(request.origin_run_id), "receipt-archive", str(request.request_id)),
            request, apply, validate=validate_archive, request_id=request.request_id,
            allow_historical_replay=True,
        )
