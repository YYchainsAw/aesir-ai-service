"""Explicit process-bound run and encounter control with revision CAS."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time
from uuid import UUID, uuid4

from app.scoped.errors import ScopeError
from app.scoped.idempotency import IdempotencyStore


@dataclass
class _RunState:
    control_revision: int = 0
    run_id: UUID | None = None
    run_binding_id: UUID | None = None
    encounter_revision: int = 0
    encounter_id: UUID | None = None


class ScopedRuntime:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 service_instance_id: UUID | None = None, max_scopes: int = 4096) -> None:
        self.service_instance_id = service_instance_id or uuid4()
        self.lock = threading.RLock()
        self._states: dict[tuple[str, str, str], _RunState] = {}
        self._controls = IdempotencyStore(clock=clock)
        self.max_scopes = max_scopes

    @staticmethod
    def _key(scope) -> tuple[str, str, str]:
        return scope.key[:3]

    def _state(self, scope) -> _RunState:
        key = self._key(scope)
        if key not in self._states:
            if len(self._states) >= self.max_scopes:
                raise ScopeError(503, "STATE_UNAVAILABLE", "Run state capacity reached.")
            self._states[key] = _RunState()
        return self._states[key]

    def _instance(self, value) -> None:
        if value != self.service_instance_id:
            raise ScopeError(409, "SERVER_INSTANCE_CHANGED", "The service instance changed; obtain fresh context.")

    def _snapshot(self, state: _RunState) -> dict:
        return {"service_instance_id": self.service_instance_id,
                "control_revision": state.control_revision, "run_id": state.run_id,
                "run_binding_id": state.run_binding_id,
                "encounter_revision": state.encounter_revision, "encounter_id": state.encounter_id}

    def context(self, npc_scope) -> dict:
        with self.lock:
            return self._snapshot(self._state(npc_scope))

    def bind_run(self, npc_scope, *, request_id: UUID, service_instance_id: UUID,
                 expected_control_revision: int, expected_run_id: UUID | None,
                 run_id: UUID) -> dict:
        self._instance(service_instance_id)
        payload = {"instance": service_instance_id, "revision": expected_control_revision,
                   "expected_run": expected_run_id, "run": run_id}
        def mutate():
            with self.lock:
                self._instance(service_instance_id)
                state = self._state(npc_scope)
                if state.control_revision != expected_control_revision or state.run_id != expected_run_id:
                    raise ScopeError(409, "RUN_CAS_CONFLICT", "The expected current run/revision no longer matches.")
                state.run_id, state.run_binding_id = run_id, uuid4()
                state.control_revision += 1
                state.encounter_id, state.encounter_revision = None, 0
                return self._snapshot(state)
        result = self._controls.execute(self._key(npc_scope) + ("bind", str(request_id)), payload, mutate,
                                        validate=lambda: self._instance(service_instance_id), request_id=request_id)
        with self.lock:
            state = self._state(npc_scope)
            if (state.run_binding_id != result["run_binding_id"]
                    or state.control_revision != result["control_revision"]):
                raise ScopeError(409, "RUN_BINDING_STALE", "The original binding has since been replaced or ended.")
        return result

    def end_run(self, npc_scope, *, request_id: UUID, service_instance_id: UUID,
                run_id: UUID, run_binding_id: UUID, expected_control_revision: int) -> dict:
        self._instance(service_instance_id)
        payload = {"instance": service_instance_id, "run": run_id, "binding": run_binding_id,
                   "revision": expected_control_revision}
        def mutate():
            with self.lock:
                state = self._state(npc_scope)
                self._validate_values(state, service_instance_id, run_id, run_binding_id)
                if state.control_revision != expected_control_revision:
                    raise ScopeError(409, "RUN_CAS_CONFLICT", "The expected control revision no longer matches.")
                state.run_id = state.run_binding_id = state.encounter_id = None
                state.control_revision += 1
                state.encounter_revision += 1
                return self._snapshot(state)
        result = self._controls.execute(self._key(npc_scope) + ("end", str(request_id)), payload, mutate,
                                        validate=lambda: self._instance(service_instance_id), request_id=request_id)
        with self.lock:
            if self._state(npc_scope).control_revision != result["control_revision"]:
                raise ScopeError(409, "RUN_CAS_CONFLICT", "The closed run is no longer the current control state.")
        return result

    def _validate_values(self, state, service_instance_id, run_id, run_binding_id):
        self._instance(service_instance_id)
        if state.run_id is None or state.run_id != run_id or state.run_binding_id != run_binding_id:
            raise ScopeError(409, "RUN_BINDING_STALE", "This run is not the active binding.")

    def control_encounter(self, npc_scope, *, request_id: UUID, service_instance_id: UUID,
                          run_id: UUID, run_binding_id: UUID, op: str,
                          expected_encounter_revision: int,
                          expected_encounter_id: UUID | None, encounter_id: UUID | None = None) -> dict:
        self._instance(service_instance_id)
        payload = {"instance": service_instance_id, "run": run_id, "binding": run_binding_id,
                   "op": op, "revision": expected_encounter_revision,
                   "expected_encounter": expected_encounter_id, "encounter": encounter_id}
        def validate():
            with self.lock:
                self._validate_values(self._state(npc_scope), service_instance_id, run_id, run_binding_id)
        def mutate():
            with self.lock:
                state = self._state(npc_scope)
                self._validate_values(state, service_instance_id, run_id, run_binding_id)
                if (state.encounter_revision != expected_encounter_revision
                        or state.encounter_id != expected_encounter_id):
                    raise ScopeError(409, "ENCOUNTER_CAS_CONFLICT", "The encounter revision/current ID changed.")
                if op == "begin" and encounter_id is not None:
                    state.encounter_id = encounter_id
                elif op == "end" and state.encounter_id is not None:
                    state.encounter_id = None
                else:
                    raise ScopeError(422, "INVALID_SCOPE_OR_TIMING", "Invalid encounter control operation.")
                state.encounter_revision += 1
                return self._snapshot(state)
        result = self._controls.execute(self._key(npc_scope) + ("encounter", str(request_id)), payload,
                                        mutate, validate=validate, request_id=request_id)
        with self.lock:
            if self._state(npc_scope).encounter_revision != result["encounter_revision"]:
                raise ScopeError(409, "ENCOUNTER_CAS_CONFLICT", "The original encounter control state has changed.")
        return result

    def validate_binding(self, request_scope) -> None:
        with self.lock:
            state = self._state(request_scope.npc)
            self._validate_values(state, request_scope.service_instance_id,
                                  request_scope.run_id, request_scope.run_binding_id)
            if request_scope.encounter_id is not None and state.encounter_id != request_scope.encounter_id:
                raise ScopeError(409, "ENCOUNTER_INACTIVE", "This encounter is not active in the current binding.")

    @contextmanager
    def guard(self, request_scope) -> Iterator[None]:
        with self.lock:
            self.validate_binding(request_scope)
            yield


_runtime = ScopedRuntime()


def get_runtime() -> ScopedRuntime:
    return _runtime


def reset_runtime() -> ScopedRuntime:
    global _runtime
    _runtime = ScopedRuntime()
    return _runtime
