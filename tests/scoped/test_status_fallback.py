"""阶段 1：coordinator.status() 内存 miss 时的跨进程 fallback。

多 worker 非粘性部署下，请求可能在 worker A 完成、status 打到 worker B。
coordinator._entries 是进程内存，worker B 查不到 → 以前直接 404。
现在注入 status_fallback 回调（SQL 模式为 journal.read_status），内存 miss
时走它查持久层。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.scoped.context import NpcScope, RequestScope
from app.scoped.requests import RequestCoordinator
from app.scoped.errors import ScopeError


def _scope(npc: NpcScope, session_id) -> RequestScope:
    return RequestScope(npc, uuid4(), session_id, uuid4(), uuid4(), uuid4())


@pytest.fixture
def npc():
    return NpcScope("aesir", uuid4(), uuid4(), "companion.alice")


def test_status_memory_hit_skips_fallback(npc):
    """内存命中时不调 fallback（避免每次 status 都打一次数据库）。"""
    scope = _scope(npc, uuid4())
    fallback_calls = []

    def fallback(s, op, rid):
        fallback_calls.append(rid)
        return {"target_request_id": rid, "operation": op, "state": "completed",
                "reason_code": None, "queue_ms": 0, "processing_ms": 0,
                "total_ms": 10, "upstream_attempts": 0, "cancel_requested": False}

    coordinator = RequestCoordinator(status_fallback=fallback)
    result = coordinator.execute(scope, "chat", "req-1", lambda: {"ok": True})
    assert result == {"ok": True}

    record = coordinator.status(scope, "chat", "req-1")
    assert record["state"] == "completed"
    assert fallback_calls == []  # 内存命中，没调 fallback


def test_status_memory_miss_falls_back_to_journal(npc):
    """内存 miss 时 fallback 返回的记录原样给调用方。"""
    scope = _scope(npc, uuid4())
    journal_record = {
        "target_request_id": "req-other", "operation": "chat",
        "state": "completed", "reason_code": None,
        "queue_ms": 12, "processing_ms": 34, "total_ms": 46,
        "upstream_attempts": 0, "cancel_requested": False,
    }

    def fallback(s, op, rid):
        return dict(journal_record)

    coordinator = RequestCoordinator(status_fallback=fallback)
    record = coordinator.status(scope, "chat", "req-other")
    assert record["state"] == "completed"
    assert record["total_ms"] == 46
    assert record["target_request_id"] == "req-other"


def test_status_memory_miss_and_journal_unknown_raises_404(npc):
    """内存 miss 且 journal 也没有 → 真正 404（与原行为一致）。"""
    scope = _scope(npc, uuid4())

    def fallback(s, op, rid):
        return None

    coordinator = RequestCoordinator(status_fallback=fallback)
    with pytest.raises(ScopeError) as exc:
        coordinator.status(scope, "chat", "never-existed")
    assert exc.value.status_code == 404
    assert exc.value.code == "REQUEST_UNKNOWN"


def test_status_fallback_unset_keeps_classic_404(npc):
    """没注入 fallback（memory 模式）时行为完全不变：miss 直接 404。"""
    scope = _scope(npc, uuid4())
    coordinator = RequestCoordinator()  # 无 status_fallback
    with pytest.raises(ScopeError) as exc:
        coordinator.status(scope, "chat", "never-existed")
    assert exc.value.status_code == 404
