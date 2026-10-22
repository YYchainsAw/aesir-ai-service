"""Request-local staging; connections exist only during reads or final commit."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import logging

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import canonical_parts, checked_namespace, conflict, get_database, json_copy, parts_hash, unavailable
from app.persistence.schema import documents, state_versions
from app.scoped.errors import ScopeError

_active = ContextVar("scoped_sql_unit_of_work", default=None)
_logger = logging.getLogger(__name__)
_DELETE = object()


def _scope_parts(scope):
    if hasattr(scope, "npc"):
        return canonical_parts(scope.npc.key)
    if hasattr(scope, "key"):
        return canonical_parts(scope.key)
    return canonical_parts(scope)


@dataclass
class Change:
    namespace: str
    key: tuple
    scope: tuple
    expected_version: int | None
    payload: object


class UnitOfWork:
    def __init__(self, scope, *, database=None):
        self.scope_parts = _scope_parts(scope)
        self.database = database or get_database()
        self.read_versions = {}
        self.changes = {}
        self.mutations = []
        self.commit_hooks = []
        self.rollback_hooks = []
        self.confirmed_version = None
        self.committed = False
        self.closed = False

    def _open(self):
        if self.closed:
            raise RuntimeError("Unit of work is already closed")

    def _key(self, namespace, key):
        return checked_namespace(namespace), canonical_parts(key)

    def read_document(self, namespace, key):
        self._open()
        identity = self._key(namespace, key)
        change = self.changes.get(identity)
        if change is not None:
            return None if change.payload is _DELETE else deepcopy(change.payload)
        row = self.database._read(*identity)
        self.read_versions[identity] = row["version"] if row else None
        return deepcopy(row["payload"]) if row else None

    def write_document(self, namespace, key, payload, *, scope_parts=()):
        self._stage(namespace, key, json_copy(payload), scope_parts)

    def delete_document(self, namespace, key, *, scope_parts=()):
        self._stage(namespace, key, _DELETE, scope_parts)

    def _stage(self, namespace, key, payload, scope_parts):
        self._open()
        identity, scope = self._key(namespace, key), canonical_parts(scope_parts)
        if scope and self.scope_parts and scope != self.scope_parts:
            raise ScopeError(409, "SCOPE_MISMATCH", "Document scope differs from transaction scope")
        if identity not in self.read_versions:
            self.read_document(*identity)
        original = self.changes.get(identity)
        expected = original.expected_version if original else self.read_versions[identity]
        self.changes[identity] = Change(*identity, scope, expected, payload)

    def overlay_listing(self, namespace, prefix, found):
        for change in self.changes.values():
            if change.namespace != namespace or change.scope[:len(prefix)] != prefix:
                continue
            if change.payload is _DELETE:
                found.pop(change.key, None)
            else:
                found[change.key] = deepcopy(change.payload)

    def add_mutation(self, function):
        self._open()
        self.mutations.append(function)

    def after_commit(self, function):
        self._open()
        self.commit_hooks.append(function)

    def after_rollback(self, function):
        self._open()
        self.rollback_hooks.append(function)

    def commit(self):
        self._open()
        try:
            with self.database.engine.begin() as connection:
                for change in self.changes.values():
                    identity = (documents.c.namespace == change.namespace, documents.c.key_hash == parts_hash(change.key))
                    if change.payload is _DELETE:
                        if change.expected_version is not None:
                            result = connection.execute(delete(documents).where(*identity, documents.c.version == change.expected_version))
                            if result.rowcount != 1:
                                raise conflict()
                        continue
                    values = dict(key_parts=list(change.key), scope_parts=list(change.scope), payload=change.payload)
                    if change.expected_version is None:
                        connection.execute(insert(documents).values(namespace=change.namespace, key_hash=parts_hash(change.key), version=1, **values))
                    else:
                        result = connection.execute(update(documents).where(*identity, documents.c.version == change.expected_version).values(version=change.expected_version + 1, **values))
                        if result.rowcount != 1:
                            raise conflict()
                if self.changes or self.mutations:
                    key = parts_hash(self.scope_parts)
                    row = connection.execute(select(state_versions).where(state_versions.c.scope_hash == key).with_for_update()).mappings().one_or_none()
                    if row is None:
                        version = 1
                        connection.execute(insert(state_versions).values(scope_hash=key, scope_parts=list(self.scope_parts), version=version))
                    else:
                        if tuple(row["scope_parts"]) != self.scope_parts:
                            raise unavailable()
                        version = row["version"] + 1
                        result = connection.execute(update(state_versions).where(state_versions.c.scope_hash == key, state_versions.c.version == row["version"]).values(version=version))
                        if result.rowcount != 1:
                            raise conflict()
                    self.confirmed_version = version
                else:
                    self.confirmed_version = connection.execute(select(state_versions.c.version).where(state_versions.c.scope_hash == parts_hash(self.scope_parts))).scalar_one_or_none() or 0
                for mutation in self.mutations:
                    mutation(connection)
            self.committed = self.closed = True
        except IntegrityError as error:
            self.rollback()
            raise conflict() from error
        except SQLAlchemyError as error:
            self.rollback()
            raise unavailable() from error
        except Exception:
            self.rollback()
            raise
        # Database has committed. Hook failures cannot turn it into a rollback.
        try:
            for function in self.commit_hooks:
                function()
        except Exception as error:
            raise ScopeError(503, "REQUEST_OUTCOME_UNKNOWN", "SQL commit succeeded but local finalization failed") from error
        return self.confirmed_version

    def rollback(self):
        if self.closed:
            return
        self.closed = True
        self.changes.clear()
        for function in reversed(self.rollback_hooks):
            try:
                function()
            except Exception:
                _logger.warning("SQL rollback cache invalidation failed")


def current_uow():
    unit = _active.get()
    # Commit hooks operate against confirmed SQL state, never a closed overlay.
    return unit if unit is not None and not unit.closed else None


@contextmanager
def use_unit_of_work(scope, *, database=None):
    existing = current_uow()
    if existing is not None:
        if existing.scope_parts != _scope_parts(scope):
            raise ScopeError(409, "SCOPE_MISMATCH", "Nested SQL scope differs from current transaction")
        yield existing
        return
    unit = UnitOfWork(scope, database=database)
    token = _active.set(unit)
    try:
        yield unit
    finally:
        if not unit.closed:
            unit.rollback()
        _active.reset(token)


def after_commit(function):
    unit = current_uow()
    if unit is None:
        function()
    else:
        unit.after_commit(function)


def after_rollback(function):
    unit = current_uow()
    if unit is not None:
        unit.after_rollback(function)
