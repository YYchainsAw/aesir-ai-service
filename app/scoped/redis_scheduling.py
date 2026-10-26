"""Redis 易失调度后端（阶段 0b）。

把 ``InMemoryScheduler`` 的单进程语义搬到一个共享 Redis 上，使多个 worker
进程共享同一套「全局生成槽 / 会话串行 / 排队深度」判定。

设计取舍（0b 单机单 worker 可跑通为目标）：

- **不用 Lua**：fakeredis（本地测试替身）不支持 EVAL；更重要的是，全局槽与会话
  锁都能用 ``SET key token NX EX <lease>`` 这条**原子命令**表达——NX 本身就是
  占槽的原子 backstop，跨 worker 的抢占由它裁决，无需 Lua。
- **租约 TTL**：每个槽 / 会话锁都带 ``lease_seconds``。worker 崩溃后锁自动过期，
  其它 worker 可接管，避免死锁。0b 单 worker 下请求远短于租约，不会误抢。
- **``exclusive()`` 退化为进程内 RLock**：0b 只有一个 worker 进程，竞争来自进程
  内线程（anyio 线程池），这把锁串行它们对 ``_entries`` 与多步占槽的访问。
  跨 worker 的真正互斥由 Redis NX 承担（0d 双 worker 混沌测试验证）。
- **``wait()`` 退化为 50ms 轮询**：协调器控制流本就每 50ms 复检一次槽位，
  ``notify_all()`` 因此是空操作。Pub/Sub 提前唤醒是后续优化，不影响正确性。

边界（与 ``scheduling.py`` 一致）：调度态只管「谁先跑、并发几个、同会话是否
串行」；请求注册表 / 结果 / 取消 tombstone 仍在 ``RequestCoordinator``，SQL
模式下其权威版本由 journal 承担。
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import threading
import time
from uuid import uuid4

from app.scoped.scheduling import _Request


def _enc(part) -> str:
    """把 tuple / str 调度键确定性编码为 Redis 标量（分隔符不会出现在键内）。"""
    if isinstance(part, (tuple, list)):
        return "\x1f".join(_enc(p) for p in part)
    return str(part)


class RedisScheduler:
    """``SchedulerBackend`` 的 Redis 实现。

    ``client`` 可注入：生产传 ``redis.Redis.from_url(url)``，测试传
    ``fakeredis.FakeStrictRedis()``。键统一加 ``prefix`` 前缀，避免与同实例
    其它业务撞键。
    """

    def __init__(self, client, *, max_generation_concurrency: int, queue_limit: int,
                 session_queue_limit: int, clock: Callable[[], float],
                 lease_seconds: float = 30.0, prefix: str = "aesir:sched") -> None:
        self.client = client
        self.max_generation_concurrency = max_generation_concurrency
        self.queue_limit = queue_limit
        self.session_queue_limit = session_queue_limit
        self.clock = clock
        self.lease_seconds = lease_seconds
        self._lock = threading.RLock()
        # 本进程身份标签：占槽 / 占会话锁的值。释放时比对它，避免误删他人锁。
        self._token = uuid4().hex
        # 本进程当前持槽标记（owns_running_slot 用）。
        self._owned: set[tuple] = set()
        self._owned_slot: dict[tuple, int] = {}
        # Redis 键名。
        self._waiting = f"{prefix}:waiting"          # LIST，LINDEX 0 = 最早到达
        self._wait_session = f"{prefix}:wait_session"  # HASH encoded_key -> session
        self._queue_depth = f"{prefix}:queue_depth"    # HASH session -> 排队数
        self._prefix = prefix

    # -- 键名 -------------------------------------------------------------
    def _slot(self, index: int) -> str:
        return f"{self._prefix}:slot:{index}"

    def _sess(self, session_enc: str) -> str:
        return f"{self._prefix}:sess:{session_enc}"

    # -- SchedulerBackend -------------------------------------------------
    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._lock:
            yield

    def owns_running_slot(self, key: tuple, entry: _Request) -> bool:
        return key in self._owned

    def try_enqueue(self, key: tuple, entry: _Request) -> bool:
        if self.client.llen(self._waiting) >= self.queue_limit:
            return False
        sess = _enc(entry.scope.session_key)
        depth = int(self.client.hget(self._queue_depth, sess) or 0)
        if depth >= self.session_queue_limit:
            return False
        ek = _enc(key)
        self.client.rpush(self._waiting, ek)
        self.client.hset(self._wait_session, ek, sess)
        self.client.hincrby(self._queue_depth, sess, 1)
        return True

    def dequeue(self, key: tuple) -> None:
        ek = _enc(key)
        self.client.lrem(self._waiting, 0, ek)
        sess = self.client.hget(self._wait_session, ek)
        if sess is not None:
            self.client.hincrby(self._queue_depth, sess, -1)
            self.client.hdel(self._wait_session, ek)

    def try_acquire(self, key: tuple, entry: _Request) -> bool:
        sess = _enc(entry.scope.session_key)
        ek = _enc(key)
        # 1. 会话串行闸门：我的会话已被（任何 worker）锁住就不占槽。
        if self.client.exists(self._sess(sess)):
            return False
        # 2. FIFO 公平：等待队列里，「会话空闲的最早请求」必须是我。
        #    会话是否空闲 = 该会话锁是否存在（NX 锁即事实来源，不另维护集合）。
        waiters = self.client.lrange(self._waiting, 0, -1)
        for w in waiters:
            if w == ek:
                break  # 我在队列里，且前面没有会话空闲的更早请求
            w_sess = self.client.hget(self._wait_session, w)
            if w_sess and not self.client.exists(self._sess(w_sess)):
                return False  # 更早的、会话空闲的请求排在我前面
        # 3. 原子占槽：先占会话锁（NX），再占一个全局槽（NX）。任一失败即回滚。
        if not self.client.set(self._sess(sess), self._token, nx=True, ex=int(self.lease_seconds)):
            return False  # 会话锁被抢
        slot_index = None
        for i in range(1, self.max_generation_concurrency + 1):
            if self.client.set(self._slot(i), self._token, nx=True, ex=int(self.lease_seconds)):
                slot_index = i
                break
        if slot_index is None:
            self._release_if_owner(self._sess(sess))
            return False  # 全局槽全满
        # 4. 成功：把自己移出等待队列，登记本进程持槽。
        self.client.lrem(self._waiting, 0, ek)
        self.client.hdel(self._wait_session, ek)
        self.client.hincrby(self._queue_depth, sess, -1)
        self._owned.add(key)
        self._owned_slot[key] = slot_index
        return True

    def start(self, key: tuple, entry: _Request) -> None:
        # try_acquire 已原子占完槽与会话锁；start 仅登记本进程持槽标记。
        self._owned.add(key)

    def release(self, key: tuple, entry: _Request) -> None:
        self._owned.discard(key)
        sess = _enc(entry.scope.session_key)
        slot_index = self._owned_slot.pop(key, None)
        if slot_index is not None:
            self._release_if_owner(self._slot(slot_index))
        self._release_if_owner(self._sess(sess))

    def wait(self, timeout: float) -> None:
        # 协调器每 50ms 复检一次；轮询即可，Pub/Sub 提前唤醒留作优化。
        # 必须在等待期间释放进程内 RLock，否则同进程其它线程无法进入 exclusive()。
        self._lock.release()
        try:
            time.sleep(timeout)
        finally:
            self._lock.acquire()

    def notify_all(self) -> None:
        # 轮询模型下无需主动唤醒。
        pass

    # -- 内部 -------------------------------------------------------------
    def _release_if_owner(self, key: str) -> None:
        """仅当锁仍归本进程时删除（避免租约过期后误删他人接管的锁）。"""
        if self.client.get(key) == self._token:
            self.client.delete(key)
