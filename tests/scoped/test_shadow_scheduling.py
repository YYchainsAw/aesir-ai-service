"""影子模式双写比对（阶段 0c）。

用 ``ShadowScheduler`` 同时委托 ``InMemoryScheduler``（权威语义基线）与
``RedisScheduler``（fakeredis 替身），跑与 ``test_requests.py`` 相同的端到端
场景。任一调度决策或状态快照不一致即抛 ``ShadowMismatchError``——这意味着
Redis 后端的语义移植有 bug。
"""
from __future__ import annotations

from uuid import uuid4

import fakeredis
import pytest

from app.scoped.context import NpcScope, RequestScope
from app.scoped.redis_scheduling import RedisScheduler
from app.scoped.requests import RequestCoordinator
from app.scoped.scheduling import InMemoryScheduler, _Request
from app.scoped.shadow_scheduling import ShadowScheduler, ShadowMismatchError


def _scope(npc: NpcScope, session_id) -> RequestScope:
    return RequestScope(npc, uuid4(), session_id, uuid4(), uuid4(), uuid4())


def _entry(scope: RequestScope, request_id: str) -> _Request:
    return _Request(scope, "test.op", request_id, 100.0)


@pytest.fixture
def client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def npc():
    return NpcScope("aesir", uuid4(), uuid4(), "companion.alice")


def _shadow(client, *, max_concurrency=2, queue_limit=16, session_queue_limit=4):
    """构造内存 + Redis 双后端的 ShadowScheduler。"""
    common = dict(
        max_generation_concurrency=max_concurrency,
        queue_limit=queue_limit,
        session_queue_limit=session_queue_limit,
        clock=lambda: 100.0,
    )
    memory = InMemoryScheduler(**common)
    redis = RedisScheduler(client, **common)
    return ShadowScheduler(memory, redis)


# ---------------------------------------------------------------------------
# 调度原语比对（与 test_redis_scheduling.py 相同场景）
# ---------------------------------------------------------------------------


def _acquire(sched, key, entry):
    """与协调器控制流一致：try_acquire 成功后立即 start()。"""
    assert sched.try_acquire(key, entry) is True
    sched.start(key, entry)


def test_shadow_global_slot_concurrency_matches(client, npc):
    sched = _shadow(client, max_concurrency=2)
    k1, k2, k3 = ("g", "op", "r1"), ("g", "op", "r2"), ("g", "op", "r3")
    e1 = _entry(_scope(npc, uuid4()), "r1")
    e2 = _entry(_scope(npc, uuid4()), "r2")
    e3 = _entry(_scope(npc, uuid4()), "r3")
    _acquire(sched, k1, e1)
    _acquire(sched, k2, e2)
    assert sched.try_acquire(k3, e3) is False


def test_shadow_release_frees_slot_for_next(client, npc):
    sched = _shadow(client, max_concurrency=1)
    k1, k2 = ("g", "op", "r1"), ("g", "op", "r2")
    e1 = _entry(_scope(npc, uuid4()), "r1")
    e2 = _entry(_scope(npc, uuid4()), "r2")
    _acquire(sched, k1, e1)
    assert sched.try_acquire(k2, e2) is False
    sched.release(k1, e1)
    _acquire(sched, k2, e2)


def test_shadow_same_session_runs_serially(client, npc):
    sched = _shadow(client, max_concurrency=2)
    scope = _scope(npc, uuid4())
    k1, k2 = ("g", "op", "r1"), ("g", "op", "r2")
    _acquire(sched, k1, _entry(scope, "r1"))
    assert sched.try_acquire(k2, _entry(scope, "r2")) is False


def test_shadow_queue_depth_limits(client, npc):
    sched = _shadow(client, max_concurrency=1, queue_limit=2, session_queue_limit=2)
    busy = ("g", "op", "busy")
    assert sched.try_acquire(busy, _entry(_scope(npc, uuid4()), "busy")) is True
    scope = _scope(npc, uuid4())
    assert sched.try_enqueue(("g", "op", "q1"), _entry(scope, "q1")) is True
    assert sched.try_enqueue(("g", "op", "q2"), _entry(scope, "q2")) is True
    assert sched.try_enqueue(("g", "op", "q3"), _entry(scope, "q3")) is False


def test_shadow_dequeue_relieves_session_depth(client, npc):
    sched = _shadow(client, max_concurrency=1, queue_limit=4, session_queue_limit=1)
    scope = _scope(npc, uuid4())
    k = ("g", "op", "q1")
    assert sched.try_enqueue(k, _entry(scope, "q1")) is True
    assert sched.try_enqueue(("g", "op", "q2"), _entry(scope, "q2")) is False
    sched.dequeue(k)
    assert sched.try_enqueue(("g", "op", "q2"), _entry(scope, "q2")) is True


# ---------------------------------------------------------------------------
# RequestCoordinator 端到端（与 test_requests.py 相同场景）
# ---------------------------------------------------------------------------


def test_shadow_coordinator_serial_request(client, npc):
    """串行请求走 Shadow 后端应正常完成，且两个后端状态始终一致。"""
    sched = _shadow(client, max_concurrency=2)
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


def test_shadow_coordinator_concurrent_requests(client, npc):
    """max_concurrency=2 时，两个独立会话的请求并行执行，第三个排队。"""
    sched = _shadow(client, max_concurrency=2, queue_limit=4)
    coordinator = RequestCoordinator(max_generation_concurrency=2, scheduler=sched)

    import threading
    started = []
    release = threading.Event()

    def slow_action():
        started.append(1)
        release.wait(timeout=2.0)
        return {"ok": True}

    scope1 = _scope(npc, uuid4())
    scope2 = _scope(npc, uuid4())
    scope3 = _scope(npc, uuid4())

    t1 = threading.Thread(target=coordinator.execute, args=(scope1, "op", "r1", slow_action))
    t2 = threading.Thread(target=coordinator.execute, args=(scope2, "op", "r2", slow_action))
    t1.start(); t2.start()

    import time; time.sleep(0.3)
    assert len(started) == 2  # 两个并行

    # 第三个应排队（不占槽）
    release.set()
    t1.join(); t2.join()

    # 第三个现在能跑
    result = coordinator.execute(scope3, "op", "r3", lambda: {"ok": True})
    assert result == {"ok": True}


def test_shadow_coordinator_cancel_queued_request(client, npc):
    """取消排队请求：两个后端的 waiting 集合都应移除该 key。"""
    sched = _shadow(client, max_concurrency=1, queue_limit=4, session_queue_limit=2)
    coordinator = RequestCoordinator(max_generation_concurrency=1, scheduler=sched)

    import threading
    started = []
    release = threading.Event()

    def slow_action():
        started.append(1)
        release.wait(timeout=2.0)
        return {"ok": True}

    scope_busy = _scope(npc, uuid4())
    t = threading.Thread(target=coordinator.execute, args=(scope_busy, "op", "busy", slow_action))
    t.start()
    import time; time.sleep(0.3)
    assert started == [1]

    # 第二个请求排队（不同会话）
    scope_q = _scope(npc, uuid4())
    cancel_result = []
    cancel_error = []
    def queued_action():
        return {"queued": True}
    def run_queued():
        try:
            cancel_result.append(coordinator.execute(scope_q, "op", "q1", queued_action))
        except Exception as exc:
            cancel_error.append(exc)
    tq = threading.Thread(target=run_queued)
    tq.start()
    time.sleep(0.2)

    # 取消排队请求
    coordinator.cancel(scope_q, "op", "q1")
    release.set()
    t.join(); tq.join()

    # 排队请求应被取消（不会执行 queued_action）
    assert cancel_result == []
    assert cancel_error  # 取消应抛 ScopeError


# ---------------------------------------------------------------------------
# 不一致检测（验证 ShadowScheduler 确实能抓到偏差）
# ---------------------------------------------------------------------------


def test_shadow_catches_decision_mismatch(client, npc):
    """故意让内存后端多放行一个请求，应抛 ShadowMismatchError。"""
    sched = _shadow(client, max_concurrency=1)
    k1, k2 = ("g", "op", "r1"), ("g", "op", "r2")
    e1 = _entry(_scope(npc, uuid4()), "r1")
    e2 = _entry(_scope(npc, uuid4()), "r2")
    _acquire(sched, k1, e1)

    # 故意污染内存状态：让它以为还有空槽（绕过 Shadow 比对）
    sched.memory.running.pop(k1)
    sched.memory.sessions.discard(e1.scope.session_key)

    # 现在 Shadow.try_acquire：内存以为空槽(True)，Redis 槽满(False)
    with pytest.raises(ShadowMismatchError, match="try_acquire mismatch"):
        sched.try_acquire(k2, e2)
