"""路由解析一次的不可变归属，以及同步/异步调用链共享的请求上下文。"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import re
from typing import Iterator
from uuid import UUID

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def safe_segment(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_SEGMENT.fullmatch(value) or ".." in value:
        raise ValueError("Invalid scope path segment")
    return value


@dataclass(frozen=True)
class NpcScope:
    game_id: str
    player_id: UUID
    save_id: UUID
    companion_id: str

    def __post_init__(self) -> None:
        safe_segment(self.game_id)
        safe_segment(self.companion_id)
        object.__setattr__(self, "player_id", UUID(str(self.player_id)))
        object.__setattr__(self, "save_id", UUID(str(self.save_id)))

    @property
    def key(self) -> tuple[str, str, str, str]:
        return self.game_id, str(self.player_id), str(self.save_id), self.companion_id

    @property
    def path_parts(self) -> tuple[str, str, str, str]:
        return self.key

    @property
    def save_key(self) -> tuple[str, str, str]:
        return self.key[:3]

    def as_dict(self) -> dict[str, str]:
        return dict(zip(("game_id", "player_id", "save_id", "companion_id"), self.key))


@dataclass(frozen=True)
class RequestScope:
    npc: NpcScope
    run_id: UUID
    session_id: UUID
    service_instance_id: UUID
    run_binding_id: UUID
    memory_epoch: UUID
    encounter_id: UUID | None = None

    def __post_init__(self) -> None:
        for name in ("run_id", "session_id", "service_instance_id", "run_binding_id", "memory_epoch"):
            object.__setattr__(self, name, UUID(str(getattr(self, name))))
        if self.encounter_id is not None:
            object.__setattr__(self, "encounter_id", UUID(str(self.encounter_id)))

    @property
    def key(self) -> tuple[str, ...]:
        return (*self.npc.key, str(self.run_id))

    @property
    def session_key(self) -> tuple[str, ...]:
        return (*self.key, str(self.session_id))


_scope: ContextVar[RequestScope | None] = ContextVar("npc_request_scope", default=None)


def current_scope() -> RequestScope | None:
    return _scope.get()


@contextmanager
def use_scope(scope: RequestScope) -> Iterator[RequestScope]:
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)
