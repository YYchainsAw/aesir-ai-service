"""双 worker 混沌测试（阶段 0d）。

两个 ``RedisScheduler`` 实例共享同一个 fakeredis client——它们各自有独立
的进程身份 token（``self._token``）和本地持槽标记（``self._owned``），但
Redis 键空间（槽/会话锁/等待队列/排队深度）是共享的。这在单机上模拟了
两个 worker 进程共享同一 Redis 的真实拓扑。

测试场景：
1. 同会话跨 worker 串行：worker A 占槽后，worker B 同会话请求必失败。
2. 租约过期接管：worker A 占槽后崩溃（不 release），短租约过期后 worker B 可接管。
3. 全局槽跨 worker 上限：max_concurrency=2，两个 worker 各占一个，第三个必排队。
4. 排队深度跨 worker：worker A 入队后，worker B 入队时总深度已达上限。
5. 误删保护：worker A 的锁过期后被 worker B 接管，worker A 「醒来」不能误删 B 的锁。
"""
from __future__ import annotations

from uuid import uuid4

import fakeredis
import pytest

from app.scoped.context import NpcScope, RequestScope
from app.scoped.redis_scheduling import RedisScheduler
from app.scoped.scheduling import _Request


def _scope(npc: NpcScope, session_id) -> RequestScope:
    return RequestScope(npc, uuid4(), session_id, uuid4(), uuid4(), uuid4())


def _entry(scope: RequestScope, request_id: str) -> _Request:
    return _Request(scope, "test.op", request_id, 100.0)


def _worker(client, *, max_concurrency=2, queue_limit=16, session_queue_limit=4, lease=30.0):
    """构造一个 worker（RedisScheduler 实例）。"""
    return RedisScheduler(
        client,
        max_generation_concurrency=max_concurrency,
        queue_limit=queue_limit,
        session_queue_limit=session_queue_limit,
        clock=lambda: 100.0,
        lease_seconds=lease,
    )


@pytest.fixture
def client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def npc():
    return NpcScope("aesir", uuid4(), uuid4(), "companion.alice")


# ---------------------------------------------------------------------------
# 1. 同会话跨 worker 串行
# ---------------------------------------------------------------------------


def test_same_session_blocked_across_workers(client, npc):
    """worker A 占槽后，worker B 同会话请求必失败（会话锁跨 worker 生效）。"""
    wa = _worker(client)
    wb = _worker(client)
    scope = _scope(npc, uuid4())  # 同会话
    k1, k2 = ("g", "op", "r1"), ("g", "op", "r2")

    assert wa.try_acquire(k1, _entry(scope, "r1")) is True
    wa.start(k1, _entry(scope, "r1"))

    # worker B：即使还有空闲全局槽，同会话也必须串行
    assert wb.try_acquire(k2, _entry(scope, "r2")) is False


def test_different_sessions_run_across_workers(client, npc):
    """不同会话跨 worker 可并行（会话锁不互相阻塞）。"""
    wa = _worker(client)
    wb = _worker(client)
    scope_a = _scope(npc, uuid4())
    scope_b = _scope(npc, uuid4())

    assert wa.try_acquire(("g", "op", "a"), _entry(scope_a, "a")) is True
    wa.start(("g", "op", "a"), _entry(scope_a, "a"))

    assert wb.try_acquire(("g", "op", "b"), _entry(scope_b, "b")) is True
    wb.start(("g", "op", "b"), _entry(scope_b, "b"))


# ---------------------------------------------------------------------------
# 2. 租约过期接管
# ---------------------------------------------------------------------------


def test_lease_expiry_allows_takeover(client, npc):
    """worker A 占槽后崩溃（不 release），短租约过期后 worker B 同会话可接管。"""
    lease = 1.0  # 短租约加速测试
    wa = _worker(client, lease=lease)
    wb = _worker(client, lease=lease)
    scope = _scope(npc, uuid4())  # 同会话
    e_a = _entry(scope, "a")
    e_b = _entry(scope, "b")

    # worker A 占槽后直接丢弃（模拟崩溃——不调 release）
    assert wa.try_acquire(("g", "op", "a"), e_a) is True

    # 立刻 worker B 同会话：会话锁仍存在
    assert wb.try_acquire(("g", "op", "b"), e_b) is False

    # 等租约过期
    import time
    time.sleep(lease + 0.2)

    # worker B 现在能占槽（会话锁已自动过期）
    assert wb.try_acquire(("g", "op", "b"), e_b) is True


def test_crash_does_not_leak_global_slot(client, npc):
    """worker A 崩溃不释放全局槽，租约过期后槽自动回收。"""
    lease = 1.0
    wa = _worker(client, max_concurrency=1, lease=lease)
    wb = _worker(client, max_concurrency=1, lease=lease)

    scope_a = _scope(npc, uuid4())
    scope_b = _scope(npc, uuid4())

    assert wa.try_acquire(("g", "op", "a"), _entry(scope_a, "a")) is True

    # worker B：唯一全局槽被占
    assert wb.try_acquire(("g", "op", "b"), _entry(scope_b, "b")) is False

    import time
    time.sleep(lease + 0.2)

    # 租约过期后槽回收，worker B 能占
    assert wb.try_acquire(("g", "op", "b"), _entry(scope_b, "b")) is True


# ---------------------------------------------------------------------------
# 3. 全局槽跨 worker 上限
# ---------------------------------------------------------------------------


def test_global_slot_capped_across_workers(client, npc):
    """max_concurrency=2：worker A 占1、worker B 占1，worker A 再请求必失败。"""
    wa = _worker(client, max_concurrency=2)
    wb = _worker(client, max_concurrency=2)

    sa = _scope(npc, uuid4())
    sb = _scope(npc, uuid4())
    sc = _scope(npc, uuid4())

    assert wa.try_acquire(("g", "op", "a"), _entry(sa, "a")) is True
    wa.start(("g", "op", "a"), _entry(sa, "a"))

    assert wb.try_acquire(("g", "op", "b"), _entry(sb, "b")) is True
    wb.start(("g", "op", "b"), _entry(sb, "b"))

    # 第三个（无论哪个 worker）：全局槽已满
    assert wa.try_acquire(("g", "op", "c"), _entry(sc, "c")) is False


# ---------------------------------------------------------------------------
# 4. 排队深度跨 worker
# ---------------------------------------------------------------------------


def test_queue_depth_shared_across_workers(client, npc):
    """排队深度是全局计数：worker A 入队后，worker B 入队时总深度已达上限。"""
    wa = _worker(client, max_concurrency=1, queue_limit=2)
    wb = _worker(client, max_concurrency=1, queue_limit=2)

    # 占掉唯一全局槽
    busy_scope = _scope(npc, uuid4())
    assert wa.try_acquire(("g", "op", "busy"), _entry(busy_scope, "busy")) is True

    # worker A 入队
    scope_a = _scope(npc, uuid4())
    assert wa.try_enqueue(("g", "op", "a"), _entry(scope_a, "a")) is True

    # worker B 入队（不同会话）：总深度 1 < 2，成功
    scope_b = _scope(npc, uuid4())
    assert wb.try_enqueue(("g", "op", "b"), _entry(scope_b, "b")) is True

    # worker B 再入队：总深度 2 >= queue_limit=2，失败
    scope_c = _scope(npc, uuid4())
    assert wb.try_enqueue(("g", "op", "c"), _entry(scope_c, "c")) is False


# ---------------------------------------------------------------------------
# 5. 误删保护
# ---------------------------------------------------------------------------


def test_zombie_worker_cannot_delete_new_owner_lock(client, npc):
    """worker A 锁过期后被 worker B 接管，worker A 「醒来」不能误删 B 的锁。"""
    from app.scoped.redis_scheduling import _enc

    lease = 1.0
    wa = _worker(client, lease=lease)
    wb = _worker(client, lease=lease)

    scope = _scope(npc, uuid4())
    e_a = _entry(scope, "a")
    e_b = _entry(scope, "b")

    # worker A 占会话锁
    assert wa.try_acquire(("g", "op", "a"), e_a) is True

    import time
    time.sleep(lease + 0.2)  # worker A 的锁过期

    # worker B 接管同会话
    assert wb.try_acquire(("g", "op", "b"), e_b) is True

    # worker A 「醒来」尝试释放——_release_if_owner 比对 token，不是自己的锁不删
    wa.release(("g", "op", "a"), e_a)

    # worker B 的锁仍然存在（没被 worker A 误删）
    sess_key = f"aesir:sched:sess:{_enc(scope.session_key)}"
    assert wb.client.get(sess_key) == wb._token


# ---------------------------------------------------------------------------
# 6. FIFO 公平跨 worker
# ---------------------------------------------------------------------------


def test_fifo_fairness_across_workers(client, npc):
    """worker A 先入队，worker B 后入队；释放槽时 A 先占（即使 B 先调用 try_acquire）。"""
    wa = _worker(client, max_concurrency=1, queue_limit=4)
    wb = _worker(client, max_concurrency=1, queue_limit=4)

    # 占掉唯一全局槽
    busy_scope = _scope(npc, uuid4())
    assert wa.try_acquire(("g", "op", "busy"), _entry(busy_scope, "busy")) is True

    # worker A 先入队
    scope_a = _scope(npc, uuid4())
    assert wa.try_enqueue(("g", "op", "a"), _entry(scope_a, "a")) is True

    # worker B 后入队（不同会话）
    scope_b = _scope(npc, uuid4())
    assert wb.try_enqueue(("g", "op", "b"), _entry(scope_b, "b")) is True

    # 释放 busy 槽
    wa.release(("g", "op", "busy"), _entry(busy_scope, "busy"))

    # worker B 先尝试占槽——但 worker A 的请求在队列更前面且会话空闲
    assert wb.try_acquire(("g", "op", "b"), _entry(scope_b, "b")) is False

    # worker A 现在能占（FIFO：更早的会话空闲请求优先）
    assert wa.try_acquire(("g", "op", "a"), _entry(scope_a, "a")) is True
