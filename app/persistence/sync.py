"""Persistent real-time/offline fact identities and transactional confirmations."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import get_settings
from app.persistence.auth import validate_principal
from app.persistence.database import database_enabled, get_database, parts_hash, read_document, state_version, unavailable, write_document
from app.persistence.schema import documents
from app.persistence.uow import current_uow, use_unit_of_work
from app.scoped.context import RequestScope, use_scope
from app.scoped.errors import ScopeError
from app.scoped.runtime import get_runtime
from app.scoped.storage import memory_epoch, scope_lock
from app.schemas.relationship import RelationshipState
from app.services.relationship.rules import apply_relationship_event_ex, stage_of


FACT_NAMESPACE = "fact-confirmations"


def _save_key(scope):
    if hasattr(scope, "npc"):
        scope = scope.npc
    return tuple(str(value) for value in scope.key[:3])


def get_save_generation(scope):
    """Create immutable save metadata in its own short transaction if absent."""
    key, database = _save_key(scope), get_database()
    for _ in range(2):
        row = database._read("save-generation", key)
        if row is not None:
            try:
                return UUID(row["payload"]["generation"])
            except (KeyError, TypeError, ValueError) as error:
                raise unavailable() from error
        generation = uuid4()
        try:
            with database.engine.begin() as connection:
                connection.execute(insert(documents).values(namespace="save-generation", key_hash=parts_hash(key),
                    key_parts=list(key), scope_parts=list(key), payload={"generation": str(generation)}, version=1))
            return generation
        except IntegrityError:
            continue
        except SQLAlchemyError as error:
            raise unavailable() from error
    raise unavailable()


def fact_key(npc, origin_run_id, origin_encounter_id, event):
    return (*npc.key, str(origin_run_id), str(origin_encounter_id or ""), str(event.event_id))


def fact_fingerprint(event):
    payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lookup_fact(npc, origin_run_id, origin_encounter_id, event, *, origin_memory_epoch=None):
    result = read_document(FACT_NAMESPACE, fact_key(npc, origin_run_id, origin_encounter_id, event))
    if result is not None and (result.get("fingerprint") != fact_fingerprint(event)
            or (origin_memory_epoch is not None and result.get("origin_memory_epoch") != str(origin_memory_epoch))):
        raise ScopeError(409, "EVENT_ID_CONFLICT", "The stable fact identity has different event content or origin epoch")
    return result


def stage_fact_confirmation(npc, origin_run_id, origin_encounter_id, event, result_dict, *, origin_memory_epoch=None, source="ue"):
    unit = current_uow()
    if unit is None:
        raise RuntimeError("Fact confirmation requires an active unit of work")
    old = lookup_fact(npc, origin_run_id, origin_encounter_id, event, origin_memory_epoch=origin_memory_epoch)
    if old is not None:
        return old
    if source != "ue" or set(result_dict) != {"relationship_status", "relationship_delta", "memory_status"}:
        raise ValueError("A fact confirmation contains only declared application results")
    key = fact_key(npc, origin_run_id, origin_encounter_id, event)
    payload = {"event_id": str(event.event_id), "origin_run_id": str(origin_run_id),
        "origin_encounter_id": str(origin_encounter_id) if origin_encounter_id else None,
        "origin_memory_epoch": str(origin_memory_epoch) if origin_memory_epoch else None,
        "source": source, "fingerprint": fact_fingerprint(event),
        "event": event.model_dump(mode="json"), "result": deepcopy(result_dict), "confirmed_version": None}
    write_document(FACT_NAMESPACE, key, payload, scope_parts=npc.key)

    def confirm(connection):
        confirmed = {**payload, "confirmed_version": unit.confirmed_version}
        connection.execute(update(documents).where(documents.c.namespace == FACT_NAMESPACE,
            documents.c.key_hash == parts_hash(key)).values(payload=confirmed))
    unit.add_mutation(confirm)
    return payload


def _require_sql():
    if not database_enabled():
        raise ScopeError(503, "PERSISTENCE_REQUIRED", "Fact sync requires SQL application persistence")


def _relationship(npc):
    raw = read_document("relationship", npc.key)
    state = RelationshipState.model_validate(raw) if raw else RelationshipState(value=get_settings().relationship_initial)
    state.stage = stage_of(state.value)
    return state


def sync_state(npc, principal):
    _require_sql()
    with get_runtime().lock, scope_lock(npc):
        validate_principal(principal, npc)
        generation = get_save_generation(npc)
        epoch = memory_epoch(npc)
        return {"protocol_version": "0.4", "scope": npc.as_dict(), "save_generation": str(generation),
            "memory_epoch": str(epoch), "state_version": state_version(npc.key),
            "relationship": _relationship(npc).model_dump(mode="json")}


def _validate_origin(npc, fact, generation):
    history = read_document("run-history", (*npc.save_key, str(fact.origin_run_id)))
    if history is None:
        raise ScopeError(409, "ORIGIN_RUN_UNKNOWN", "The original run has no persistent binding history")
    if history.get("generation") != str(generation):
        raise ScopeError(409, "SAVE_GENERATION_STALE", "The original run belongs to another save generation")
    if fact.origin_encounter_id is not None:
        encounter = read_document("encounter-history", (*npc.save_key, str(fact.origin_run_id), str(fact.origin_encounter_id)))
        if encounter is None or encounter.get("generation") != str(generation):
            raise ScopeError(409, "ORIGIN_ENCOUNTER_UNKNOWN", "The original encounter has no persistent history for this run")


def _acknowledgement(confirmation, *, duplicate):
    result = confirmation["result"]
    return {"event_id": confirmation["event_id"], "duplicate": duplicate,
        "relationship_status": result["relationship_status"], "relationship_delta": result["relationship_delta"],
        "memory_status": result["memory_status"], "confirmed_version": confirmation["confirmed_version"]}


def sync_facts(npc, principal, request):
    _require_sql()
    if len(request.facts) > getattr(get_settings(), "scope_sync_batch_limit", 50):
        raise ScopeError(422, "SYNC_BATCH_LIMIT", "The fact batch exceeds the configured admission limit")
    from app.services.games.capability_gate import FEATURE_WORLD_EVENTS, require_event_declared
    try:
        for fact in request.facts:
            require_event_declared(fact.event.event_type, FEATURE_WORLD_EVENTS)
    except HTTPException as error:
        raise ScopeError(error.status_code, "BUSINESS_REJECTED", "This game does not declare the requested event") from error
    runtime = get_runtime()
    with runtime.lock, scope_lock(npc):
        validate_principal(principal, npc)
        generation = get_save_generation(npc)
        if generation != request.save_generation:
            raise ScopeError(409, "SAVE_GENERATION_STALE", "The save generation does not match authoritative state")
        epoch = memory_epoch(npc)
        batch_key = (*npc.key, str(request.request_id))
        batch_fingerprint = hashlib.sha256(json.dumps(request.model_dump(mode="json"), ensure_ascii=False,
            allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        batch = read_document("sync-batches", batch_key)
        if batch is not None and batch.get("fingerprint") != batch_fingerprint:
            raise ScopeError(409, "REQUEST_ID_CONFLICT", "The sync request ID is bound to another batch")
        existing = []
        for fact in request.facts:
            _validate_origin(npc, fact, generation)
            existing.append(lookup_fact(npc, fact.origin_run_id, fact.origin_encounter_id, fact.event,
                origin_memory_epoch=fact.origin_memory_epoch))
        current_version = state_version(npc.key)
        if any(item is None for item in existing) and request.expected_state_version != current_version:
            raise ScopeError(409, "STATE_VERSION_CONFLICT", "Pull authoritative state before confirming fresh facts")
        if batch is not None and any(item is None for item in existing):
            raise unavailable()
        if all(item is not None for item in existing):
            if batch is None:
                with use_unit_of_work(npc) as unit:
                    write_document("sync-batches", batch_key, {"fingerprint": batch_fingerprint}, scope_parts=npc.key)
                    validate_principal(principal, npc)
                    unit.commit()
                current_version = unit.confirmed_version
            return {"protocol_version": "0.4", "request_id": str(request.request_id), "scope": npc.as_dict(),
                "save_generation": str(generation), "memory_epoch": str(epoch), "state_version": current_version,
                "acknowledgements": [_acknowledgement(item, duplicate=True) for item in existing]}
        active = runtime.context(npc)
        scope = None
        if active["run_id"] is not None:
            scope = RequestScope(npc, active["run_id"], active["run_id"], active["service_instance_id"],
                active["run_binding_id"], epoch, active["encounter_id"])
        context = use_scope(scope) if scope is not None else nullcontext()
        with context, use_unit_of_work(npc) as unit:
            write_document("sync-batches", batch_key, {"fingerprint": batch_fingerprint}, scope_parts=npc.key)
            for fact, old in zip(request.facts, existing):
                if old is not None:
                    continue
                # The client timestamp remains in the fact. Admission time is
                # used for cooldown/day rules so old batches cannot rewind them.
                relationship, delta, reason = apply_relationship_event_ex(_relationship(npc), fact.event.event_type, None)
                if delta:
                    write_document("relationship", npc.key, relationship.model_dump(mode="json"), scope_parts=npc.key)
                if fact.origin_memory_epoch != epoch:
                    memory_status = "skipped_reset"
                elif scope is None:
                    memory_status = "not_applied_missing_context"
                else:
                    from app.services.memory.experiences import record_world_event_experience
                    recorded = record_world_event_experience(npc.companion_id, fact.event.event_type,
                        game_id=npc.game_id, details=fact.event.details, occurred_at=fact.event.occurred_at,
                        region_id=fact.event.details.get("region_id", ""))
                    memory_status = "recorded" if recorded else "not_applicable"
                stage_fact_confirmation(npc, fact.origin_run_id, fact.origin_encounter_id, fact.event,
                    {"relationship_status": reason, "relationship_delta": delta, "memory_status": memory_status},
                    origin_memory_epoch=fact.origin_memory_epoch, source=fact.source)
            validate_principal(principal, npc)
            if memory_epoch(npc) != epoch:
                raise ScopeError(409, "MEMORY_EPOCH_STALE", "Memory was reset while facts were being confirmed")
            if scope is not None:
                runtime.validate_binding(scope)
            unit.commit()
        confirmations = [lookup_fact(npc, fact.origin_run_id, fact.origin_encounter_id, fact.event) for fact in request.facts]
        return {"protocol_version": "0.4", "request_id": str(request.request_id), "scope": npc.as_dict(),
            "save_generation": str(generation), "memory_epoch": str(epoch), "state_version": unit.confirmed_version,
            "acknowledgements": [_acknowledgement(item, duplicate=old is not None) for item, old in zip(confirmations, existing)]}
