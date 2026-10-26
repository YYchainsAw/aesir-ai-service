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

from sqlalchemy import (BigInteger, Column, Double, Index, JSON, String, Table,
                        delete, insert, select, update)
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
    # Operational indexes: recovery scans running rows by (state, owner_instance)
    # and the status-fallback / cleanup paths look rows up by request_id and age.
    # scope_parts/key_parts remain JSON and are intentionally left unindexed (see
    # docs/design/database DB-GAP); adding a JSON generated-column index requires a
    # real MySQL environment because SQLite lacks JSON_UNQUOTE.
    Index("ix_operation_journal_state_created", "state", "created_at"),
    Index("ix_operation_journal_request_id", "request_id"),
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

    # 阶段 1：coordinator.status() 内存 miss 时的跨进程 fallback。
    # 与 recover() 的区别：recover() 是 /recovery/operations 端点的权威查询（含
    # confirmed_version / origin_service_instance_id）；read_status 把 journal
    # row 折成 coordinator._record() 的同形状字段，供 status 端点在非粘性部署
    # 下读到别的 worker 完成的请求。
    _STATE_TO_COORDINATOR = {
        "running": "running", "complete": "completed", "failed": "failed",
        "unknown": "unknown", "cancelled": "cancelled",
    }

    def read_status(self, scope, operation, request_id) -> dict | None:
        """内存 miss 时读 journal；journal 也没有则返回 None（真正 404）。

        不抛 404——由调用方（coordinator.status）在 None 时统一抛。
        scope 不匹配仍抛 409（与内存 _same_scope 同语义）。
        """
        npc = scope.npc
        key = (*npc.key, str(scope.run_id), operation, str(request_id))
        row = self._read(self._identity(key))
        if row is None:
            cancelled = read_document("request_cancel", key)
            if cancelled is None:
                return None
            return {
                "target_request_id": str(request_id), "operation": operation,
                "state": "cancelled", "reason_code": "REQUEST_CANCELLED",
                "queue_ms": 0, "processing_ms": 0, "total_ms": 0,
                "upstream_attempts": 0, "cancel_requested": True,
            }
        if tuple(row["scope_parts"]) != npc.key:
            raise ScopeError(409, "REQUEST_ID_CONFLICT",
                             "The logical ID is bound to another request scope.", request_id)
        state = row["state"]
        if state == "running" and row["owner_instance"] != str(get_runtime().service_instance_id):
            # 别的 worker 还在跑：本进程不知道它的进度，报 unknown（与 recover 同口径）。
            state = "unknown"
        finished_at = row.get("finished_at")
        total_ms = int((finished_at - row["created_at"]) * 1000) if finished_at else 0
        error = row.get("error")
        return {
            "target_request_id": str(request_id), "operation": operation,
            "state": self._STATE_TO_COORDINATOR.get(state, state),
            "reason_code": error.get("code") if error else ("REQUEST_OUTCOME_UNKNOWN" if state == "unknown" else None),
            # journal 不存 started_at，无法区分排队/处理耗时；只给总耗时。
            "queue_ms": 0, "processing_ms": 0, "total_ms": max(0, total_ms),
            "upstream_attempts": 0,
            "cancel_requested": state == "cancelled",
        }


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
