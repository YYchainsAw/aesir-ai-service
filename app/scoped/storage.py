"""NPC 状态分区、持久记忆代次与最终提交屏障（单 worker）。"""
from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from app.scoped.context import use_scope
from app.config import get_settings
from app.scoped.context import NpcScope, RequestScope, current_scope
from app.scoped.errors import ScopeError
from app.schemas.memory import MemorySnapshot

_locks: dict[tuple[str, ...], RLock] = {}
_locks_guard = RLock()
_validators = []


def unavailable() -> ScopeError:
    return ScopeError(503, "STATE_UNAVAILABLE", "NPC state is unavailable")


def scope_lock(scope: NpcScope) -> RLock:
    with _locks_guard:
        return _locks.setdefault(scope.key, RLock())


def checked_npc(companion_id: str, game_id: str | None = None) -> NpcScope | None:
    scope = current_scope()
    if scope is None:
        return None
    npc = scope.npc
    if companion_id != npc.companion_id or (game_id is not None and game_id != npc.game_id):
        raise ScopeError(409, "SCOPE_MISMATCH", "NPC scope does not match request")
    return npc


def state_directory(root: str | Path, game_id: str, companion_id: str) -> Path:
    npc = checked_npc(companion_id, game_id)
    return Path(root).joinpath(*npc.path_parts) if npc else Path(root) / game_id / companion_id


def runtime_key(companion_id: str):
    npc = checked_npc(companion_id)
    scope = current_scope()
    return ("scoped", *scope.key) if npc else companion_id


def signal_directory(root: str | Path, game_id: str) -> Path:
    scope = current_scope()
    if scope:
        checked_npc(scope.npc.companion_id, game_id)
        return Path(root).joinpath(*scope.npc.path_parts, str(scope.run_id))
    return Path(root) / game_id


def signal_metadata() -> dict[str, str]:
    scope = current_scope()
    if scope is None:
        return {}
    return {**scope.npc.as_dict(), "run_id": str(scope.run_id),
            "session_id": str(scope.session_id), "memory_epoch": str(scope.memory_epoch),
            "service_instance_id": str(scope.service_instance_id),
            "run_binding_id": str(scope.run_binding_id),
            **({"encounter_id": str(scope.encounter_id)} if scope.encounter_id else {})}


def memory_path(scope: NpcScope, root: str | Path | None = None) -> Path:
    return Path(root if root is not None else get_settings().memory_root).joinpath(*scope.path_parts, "memory.json")


def read_memory_document(scope: NpcScope, root: str | Path | None = None) -> tuple[UUID, MemorySnapshot]:
    """现有作用域缺元数据时拒绝服务，绝不从备份复活旧 epoch。调用者持 NPC 锁。"""
    from app.persistence.database import database_enabled, read_document, write_document
    if database_enabled():
        data = read_document("memory", scope.key)
        if data is None:
            data = {"memory_epoch": str(uuid4()), **MemorySnapshot().model_dump(mode="json")}
            write_document("memory", scope.key, data, scope_parts=scope.key)
        try:
            return UUID(data["memory_epoch"]), MemorySnapshot.model_validate(data)
        except (ValueError, TypeError, KeyError) as error:
            raise unavailable() from error
    path = memory_path(scope, root)
    try:
        if not path.exists():
            if path.parent.exists():
                raise unavailable()
            epoch, snapshot = uuid4(), MemorySnapshot()
            write_memory_document(scope, epoch, snapshot, root)
            return epoch, snapshot
        data = json.loads(path.read_text(encoding="utf-8"))
        epoch = UUID(data["memory_epoch"])
        if not {"short_term", "summaries", "archive", "impressions"}.issubset(data):
            raise unavailable()
        snapshot = MemorySnapshot.model_validate(data)
        return epoch, snapshot
    except ScopeError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise unavailable() from error


def write_memory_document(scope: NpcScope, epoch: UUID, snapshot: MemorySnapshot,
                          root: str | Path | None = None) -> None:
    payload = {"memory_epoch": str(epoch), **snapshot.model_dump(mode="json")}
    from app.persistence.database import database_enabled, write_document
    if database_enabled():
        write_document("memory", scope.key, payload, scope_parts=scope.key)
        return
    path = memory_path(scope, root)
    tmp = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as error:
        raise unavailable() from error


def memory_epoch(scope: NpcScope) -> UUID:
    with scope_lock(scope):
        return read_memory_document(scope)[0]


def register_commit_validator(validator) -> None:
    if validator not in _validators:
        _validators.append(validator)


@contextmanager
def commit_guard(scope: RequestScope | None = None):
    scope = scope or current_scope()
    if scope is None:
        yield
        return
    from app.scoped.runtime import get_runtime
    from app.scoped.timing import current_budget
    from app.scoped.requests import check_current
    with get_runtime().guard(scope):
        with scope_lock(scope.npc):
            if memory_epoch(scope.npc) != scope.memory_epoch:
                raise ScopeError(409, "MEMORY_EPOCH_STALE", "Memory was reset; refresh the NPC scope")
            check_current(scope)
            from app.persistence.auth import validate_current_principal
            validate_current_principal(scope)
            for validator in tuple(_validators):
                validator(scope)
            budget = current_budget()
            if budget is not None:
                budget.check()
            yield


def guarded_commit(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        bound_npc = getattr(args[0], "_scope", None) if args else None
        if bound_npc is not None:
            request_scope = current_scope()
            if request_scope is None or request_scope.npc != bound_npc:
                raise ScopeError(409, "SCOPE_MISMATCH", "NPC scope does not match request")
        from app.persistence.database import database_enabled
        from app.persistence.uow import current_uow
        unit = current_uow() if database_enabled() else None
        if unit is not None and function.__name__ in {
            "record_turn_signal", "record_agent_step", "record_event_resolved", "record_observation"
        }:
            from copy import deepcopy
            positional, named = deepcopy(args), deepcopy(kwargs)
            scope = current_scope()
            def diagnostic():
                try:
                    with use_scope(scope):
                        function(*positional, **named)
                except Exception:
                    # The database has committed; observation failure cannot revoke it.
                    pass
            unit.after_commit(diagnostic)
            return None
        with commit_guard():
            return function(*args, **kwargs)
    return guarded


def reset_memory(scope: NpcScope, expected_epoch: UUID) -> dict:
    """epoch 与空记忆单文件原子替换成功后，清该 NPC 所有 run 的会话。"""
    from app.services.memory.store import invalidate_scope
    from app.services.companion.session_memory import clear_scoped_sessions
    with scope_lock(scope):
        if memory_epoch(scope) != UUID(str(expected_epoch)):
            raise ScopeError(409, "MEMORY_EPOCH_STALE", "Memory epoch does not match")
        epoch = uuid4()
        write_memory_document(scope, epoch, MemorySnapshot())
        invalidate_scope(scope)
        cleared = clear_scoped_sessions(scope)
        return {"memory_epoch": epoch, "epoch": epoch, "cleared_sessions": cleared}
