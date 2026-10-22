"""Durable logical identities; SQL outcome and business state commit together.

Running claims are short transactions. They never hold a connection during LLM
generation. A different process incarnation cannot reclaim an unfinished claim.
"""
from __future__ import annotations

from collections import OrderedDict
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import json
from threading import Condition, RLock
import time

from sqlalchemy import BigInteger, Column, Double, JSON, String, Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import get_database, parts_hash, read_document, write_document, unavailable
from app.persistence.schema import metadata
from app.persistence.uow import current_uow
from app.scoped.context import current_scope
from app.scoped.errors import ScopeError
from app.scoped.idempotency import NotStartedError, fingerprint
from app.scoped.runtime import get_runtime
from app.scoped.timing import use_budget


operations = Table(
    "operation_journal", metadata,
    Column("identity_hash", String(64), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("key_parts", JSON, nullable=False),
    Column("scope_parts", JSON, nullable=False),
    Column("request_id", String(100), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("owner_instance", String(36), nullable=False),
    Column("state", String(16), nullable=False),
    Column("result", JSON, nullable=True),
    Column("error", JSON, nullable=True),
    Column("confirmed_version", BigInteger, nullable=True),
    Column("created_at", Double, nullable=False),
    Column("finished_at", Double, nullable=True),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)


@dataclass
class _Frame:
    store: object
    identity: str
    key: tuple
    request_id: object
    fingerprint: str
    owner: str
    staged: bool = False
    committed: bool = False


_active: ContextVar[_Frame | None] = ContextVar("durable_operation_frame", default=None)


def _unknown(request_id=None):
    return ScopeError(503, "REQUEST_OUTCOME_UNKNOWN", "Durable outcome needs reconciliation; do not execute again.", request_id)


def _json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


class DurableIdempotencyStore:
    """Single-worker SQL journal with persistent, never-auto-pruned identities."""

    def __init__(self, kind="request", *, wait_timeout_seconds=30, max_local_budgets=1024):
        self.kind = kind
        self.wait_timeout_seconds = wait_timeout_seconds
        self.max_local_budgets = max_local_budgets
        self._condition = Condition(RLock())
        self._budgets = OrderedDict()

    def _identity(self, key):
        return parts_hash((self.kind, *(str(value) for value in key)))

    def _read(self, identity):
        try:
            with get_database().engine.connect() as connection:
                return connection.execute(select(operations).where(operations.c.identity_hash == identity)).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise unavailable() from error

    def _notify(self):
        with self._condition:
            self._condition.notify_all()

    def _set_terminal(self, frame, state, error=None):
        try:
            with get_database().engine.begin() as connection:
                connection.execute(update(operations).where(
                    operations.c.identity_hash == frame.identity,
                    operations.c.owner_instance == frame.owner,
                ).values(state=state, error=error, finished_at=time.time()))
        except SQLAlchemyError as database_error:
            raise _unknown(frame.request_id) from database_error
        finally:
            self._notify()

    def _claim(self, key, fp, request_id):
        if self.kind == "request" and read_document("request_cancel", key) is not None:
            raise ScopeError(409, "REQUEST_CANCELLED", "The durable logical request was cancelled.", request_id)
        identity = self._identity(key)
        row = self._read(identity)
        if row is not None:
            return row, False
        scope = current_scope()
        owner = str(get_runtime().service_instance_id)
        values = dict(identity_hash=identity, kind=self.kind, key_parts=list(key),
                      scope_parts=list(scope.npc.key) if scope else list(key[:4]),
                      request_id=str(request_id or key[-1]), fingerprint=fp,
                      owner_instance=owner, state="running", created_at=time.time())
        try:
            with get_database().engine.begin() as connection:
                connection.execute(insert(operations).values(**values))
            return values, True
        except IntegrityError:
            row = self._read(identity)
            if row is None:
                raise unavailable()
            return row, False
        except SQLAlchemyError as error:
            raise unavailable() from error

    def stage(self, frame, result, *, confirmed_state_version=False):
        unit = current_uow()
        if unit is None:
            raise ScopeError(503, "STATE_UNAVAILABLE", "Durable operations require a business unit of work", frame.request_id)
        if frame.staged:
            return
        value = _json_value(result)

        def complete(connection):
            if confirmed_state_version:
                value["state_version"] = unit.confirmed_version
                result["state_version"] = unit.confirmed_version
            changed = connection.execute(update(operations).where(
                operations.c.identity_hash == frame.identity,
                operations.c.owner_instance == frame.owner,
                operations.c.state == "running",
                operations.c.fingerprint == frame.fingerprint,
            ).values(state="complete", result=value, error=None,
                     confirmed_version=unit.confirmed_version, finished_at=time.time()))
            if changed.rowcount != 1:
                raise _unknown(frame.request_id)

        def committed():
            frame.committed = True
            self._notify()

        def rolled_back():
            self._set_terminal(frame, "unknown")

        unit.add_mutation(complete)
        unit.after_commit(committed)
        unit.after_rollback(rolled_back)
        frame.staged = True

    def execute(self, key, payload, operation, *, validate=None, timing=None,
                request_id=None, conflict_code="REQUEST_ID_CONFLICT",
                propagate_not_started=False, on_failure=None, allow_historical_replay=False):
        key = tuple(str(value) for value in key)
        if validate is not None:
            validate()
        fp = fingerprint(payload)
        row, owner = self._claim(key, fp, request_id)
        identity = self._identity(key)
        if tuple(row["key_parts"]) != key or row["kind"] != self.kind or row["fingerprint"] != fp:
            raise ScopeError(409, conflict_code, "The persistent logical ID has different content or binding.", request_id)
        instance = str(get_runtime().service_instance_id)
        if row["owner_instance"] != instance:
            if row["state"] == "running":
                abandoned = _Frame(self, identity, key, request_id, fp, row["owner_instance"])
                self._set_terminal(abandoned, "unknown")
                raise _unknown(request_id)
            if row["state"] == "unknown":
                raise _unknown(request_id)
            if not allow_historical_replay:
                raise ScopeError(409, "SERVER_INSTANCE_CHANGED", "Historical results are available only through recovery queries.", request_id)
        with self._condition:
            budget = self._budgets.get(identity)
            if owner:
                budget = timing
                self._budgets[identity] = budget
                while len(self._budgets) > self.max_local_budgets:
                    self._budgets.popitem(last=False)
            elif budget is not None and timing is not None:
                budget.retry(timing.input)
        if not owner:
            started = time.monotonic()
            while row["state"] == "running":
                if validate is not None:
                    validate()
                if budget is not None:
                    budget.check()
                if time.monotonic() - started >= self.wait_timeout_seconds:
                    raise ScopeError(409, "REQUEST_IN_PROGRESS", "The durable owner is still processing.", request_id)
                with self._condition:
                    self._condition.wait(timeout=0.05)
                row = self._read(identity)
                if row is None:
                    raise ScopeError(409, "REQUEST_NOT_STARTED", "The original request was not admitted; retry the same ID.", request_id)
            if validate is not None:
                validate()
            if budget is not None:
                budget.check()
            elif timing is not None:
                # Losing a local monotonic anchor never gives an old action a new clock.
                raise ScopeError(409, "REQUEST_EXPIRED", "The original replay timing is no longer retained.", request_id)
            if row["state"] == "unknown":
                raise _unknown(request_id)
            if row["error"]:
                saved = row["error"]
                raise ScopeError(saved["status_code"], saved["code"], saved["message"], request_id)
            return deepcopy(row["result"])

        frame = _Frame(self, identity, key, request_id, fp, instance)
        token = _active.set(frame)
        try:
            if budget is not None:
                budget.check()
            with use_budget(budget):
                result = operation()
            if not frame.staged:
                self.stage(frame, result)
            # Nested events return a staged result. The outer request commits it.
            if not frame.committed and current_uow() is None:
                raise _unknown(request_id)
            if validate is not None:
                validate()
            if budget is not None:
                budget.check()
            return deepcopy(result)
        except Exception as error:
            if on_failure is not None:
                try:
                    error = on_failure(error)
                except Exception as callback_error:
                    error = callback_error
            if propagate_not_started and isinstance(error, NotStartedError) and not frame.staged:
                try:
                    with get_database().engine.begin() as connection:
                        connection.execute(delete(operations).where(
                            operations.c.identity_hash == identity,
                            operations.c.owner_instance == instance,
                            operations.c.state == "running",
                        ))
                except SQLAlchemyError as database_error:
                    raise _unknown(request_id) from database_error
                self._notify()
                raise error
            if not frame.committed and not frame.staged and isinstance(error, ScopeError) and error.status_code < 500:
                self._set_terminal(frame, "failed", {"status_code": error.status_code, "code": error.code, "message": error.message})
                raise error
            self._set_terminal(frame, "unknown")
            raise _unknown(request_id) from error
        finally:
            _active.reset(token)

    def clear(self):
        """Only discard volatile replay clocks; persistent identities survive."""
        with self._condition:
            self._budgets.clear()
            self._condition.notify_all()

    def recover(self, npc, run_id, operation, request_id):
        key = (*npc.key, str(run_id), operation, str(request_id))
        row = self._read(self._identity(key))
        if row is None:
            cancelled = read_document("request_cancel", key)
            if cancelled is not None:
                return {"request_id": str(request_id), "operation": operation, "run_id": str(run_id),
                        "state": "cancelled", "confirmed_version": None,
                        "origin_service_instance_id": cancelled["origin_service_instance_id"],
                        "reason_code": "REQUEST_CANCELLED"}
        if row is None or tuple(row["scope_parts"]) != npc.key:
            raise ScopeError(404, "REQUEST_UNKNOWN", "No durable request exists in this scope.", request_id)
        state = row["state"]
        if state == "running" and row["owner_instance"] != str(get_runtime().service_instance_id):
            # Recovery reads report an abandoned owner without mutating SQL.
            state = "unknown"
        return {"request_id": str(request_id), "operation": operation,
                "run_id": str(run_id), "state": state,
                "confirmed_version": row.get("confirmed_version"),
                "origin_service_instance_id": row["owner_instance"],
                "reason_code": row["error"].get("code") if row.get("error") else ("REQUEST_OUTCOME_UNKNOWN" if state == "unknown" else None)}


_requests = DurableIdempotencyStore("request")
_events = DurableIdempotencyStore("event")


def get_durable_request_store():
    return _requests


def get_durable_event_store():
    return _events


def stage_active_result(result, *, confirmed_state_version=False):
    frame = _active.get()
    if frame is None:
        raise unavailable()
    frame.store.stage(frame, result, confirmed_state_version=confirmed_state_version)


def stage_cancel_target(scope, operation, target_request_id):
    """A prearrival cancellation must survive a restart or a new binding."""
    if current_uow() is None:
        raise unavailable()
    key = (*scope.key, operation, str(target_request_id))
    write_document("request_cancel", key, {
        "origin_service_instance_id": str(scope.service_instance_id),
        "origin_run_binding_id": str(scope.run_binding_id),
        "origin_memory_epoch": str(scope.memory_epoch),
    }, scope_parts=scope.npc.key)
