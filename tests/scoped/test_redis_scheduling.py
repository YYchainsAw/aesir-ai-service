"""RedisScheduler（阶段 0b）的本地验证。

用 ``fakeredis``（纯 Python Redis 替身）验证单机单 worker 语义：全局并发槽、
会话串行、排队深度、释放后放行。跨 worker 抢占（NX 裁决）与真实 Redis 行为
留待 0c 影子模式 / 0d 双 worker 混沌测试。
"""
from __future__ import annotations

from uuid import uuid4

import fakeredis
import pytest

from app.scoped.context import NpcScope, RequestScope
from app.scoped.redis_scheduling import RedisScheduler
from app.scoped.requests import RequestCoordinator
from app.scoped.scheduling import _Request


def _scope(npc: NpcScope, session_id) -> RequestScope:
    """同 npc + 同 session_id 即同会话（session_key = (*npc.key, session_id)）。"""
    return RequestScope(npc, uuid4(), session_id, uuid4(), uuid4(), uuid4())


def _scheduler(client, *, max_concurrency=2, queue_limit=16, session_queue_limit=4):
    return RedisScheduler(
        client,
        max_generation_concurrency=max_concurrency,
        queue_limit=queue_limit,
        session_queue_limit=session_queue_limit,
        clock=lambda: 100.0,
    )


def _entry(scope: RequestScope, request_id: str) -> _Request:
    return _Request(scope, "test.op", request_id, 100.0)


@pytest.fixture
def client():
    # decode_responses=True：与生产工厂一致，get/lrange/hget 一律返回 str
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def npc():
    return NpcScope("aesir", uuid4(), uuid4(), "companion.alice")


def test_global_slot_concurrency_is_capped(client, npc):
    sched = _scheduler(client, max_concurrency=2)
    # 三个不同会话 → 都想占全局槽
    k1, k2, k3 = ("g", "op", "r1"), ("g", "op", "r2"), ("g", "op", "r3")
    assert sched.try_acquire(k1, _entry(_scope(npc, uuid4()), "r1")) is True
    assert sched.try_acquire(k2, _entry(_scope(npc, uuid4()), "r2")) is True
    assert sched.try_acquire(k3, _entry(_scope(npc, uuid4()), "r3")) is False


def test_release_frees_slot_for_next(client, npc):
    sched = _scheduler(client, max_concurrency=1)
    k1, k2 = ("g", "op", "r1"), ("g", "op", "r2")
    e1 = _entry(_scope(npc, uuid4()), "r1")
    e2 = _entry(_scope(npc, uuid4()), "r2")
    assert sched.try_acquire(k1, e1) is True
    assert sched.try_acquire(k2, e2) is False  # 唯一槽被占
    sched.release(k1, e1)
    assert sched.try_acquire(k2, e2) is True  # 释放后放行


def test_same_session_runs_serially(client, npc):
    sched = _scheduler(client, max_concurrency=2)
    # session_key = (*npc.key, run_id, session_id)：必须复用同一 scope 才算同会话
    scope = _scope(npc, uuid4())
    k1, k2 = ("g", "op", "r1"), ("g", "op", "r2")
    assert sched.try_acquire(k1, _entry(scope, "r1")) is True
    # 同会话第二个请求：即使还有空闲全局槽(slot:2)，也必须串行
    assert sched.try_acquire(k2, _entry(scope, "r2")) is False


def test_queue_depth_limits(client, npc):
    sched = _scheduler(client, max_concurrency=1, queue_limit=2, session_queue_limit=2)
    # 占掉唯一全局槽（独立会话）
    busy = ("g", "op", "busy")
    assert sched.try_acquire(busy, _entry(_scope(npc, uuid4()), "busy")) is True
    scope = _scope(npc, uuid4())  # q1/q2/q3 同会话
    # 入队：前两个成功
    assert sched.try_enqueue(("g", "op", "q1"), _entry(scope, "q1")) is True
    assert sched.try_enqueue(("g", "op", "q2"), _entry(scope, "q2")) is True
    # 第三个超过总排队上限(2)
    assert sched.try_enqueue(("g", "op", "q3"), _entry(scope, "q3")) is False


def test_dequeue_relieves_session_depth(client, npc):
    sched = _scheduler(client, max_concurrency=1, queue_limit=4, session_queue_limit=1)
    scope = _scope(npc, uuid4())  # 同 run+session 才算同会话
    k = ("g", "op", "q1")
    assert sched.try_enqueue(k, _entry(scope, "q1")) is True
    # 同会话排队数已达 session_queue_limit=1
    assert sched.try_enqueue(("g", "op", "q2"), _entry(scope, "q2")) is False
    sched.dequeue(k)
    # 出队后同会话又能入队
    assert sched.try_enqueue(("g", "op", "q2"), _entry(scope, "q2")) is True


def test_coordinator_runs_end_to_end_with_redis_backend(client, npc):
    """RequestCoordinator 注入 RedisScheduler 后，串行请求应正常完成。"""
    sched = _scheduler(client, max_concurrency=2)
    coordinator = RequestCoordinator(max_generation_concurrency=2, scheduler=sched)
    scope = _scope(npc, uuid4())
    done = []

    def action():
        done.append(1)
        return {"ok": True}

    result = coordinator.execute(scope, "chat.send", "req-1", action)
    assert result == {"ok": True}
    assert done == [1]
    assert coordinator.status(scope, "chat.send", "req-1")["state"] == "completed"


def test_redis_backend_rejected_with_json_storage(monkeypatch):
    """用户拍板的硬边界：coordination_backend=redis + scope_storage_backend=json 启动即拒。"""
    from app.config import Settings
    monkeypatch.setenv("AESIR_COORDINATION_BACKEND", "redis")
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "json")
    with pytest.raises(Exception, match="scope_storage_backend=sql"):
        Settings()


def test_redis_backend_allowed_with_sql_storage(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("AESIR_COORDINATION_BACKEND", "redis")
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    settings = Settings()
    assert settings.coordination_backend == "redis"
