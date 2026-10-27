"""阶段 2 v0.5：进程内后台执行池（chat/agent-step 异步提交的执行端）。

提交线程只做校验/配额/容量准入后立即返回 202；业务闭包（含 LLM 生成）
投递到本池执行。**不做跨进程 work-stealing**：闭包只活在接收进程内，
跨进程只通过 Redis 槽位仲裁并发上限（由 RequestCoordinator.scheduler 承担）。

池大小与全局生成槽解耦：池 >= 全局槽 × 预期 worker 数即可，真正的并发
上限仍由 scheduler 裁决，池只是提供等待的线程载体。
"""
from __future__ import annotations

import contextvars
import queue
import threading
from collections.abc import Callable
from typing import Any

from app.config import get_settings

# 守护线程池：进程退出时随主进程收尾，未完成任务由 journal 保留为 queued
# （UE 轮询到 unknown/超时后以新 request_id 重发），不强行等待。
_pool: queue.Queue[tuple[contextvars.Context, Callable[[], Any]]] | None = None
_workers: list[threading.Thread] = []
_start_lock = threading.Lock()


def _worker() -> None:
    assert _pool is not None
    while True:
        ctx, task = _pool.get()
        try:
            # 提交线程的 use_scope/use_principal/use_budget 都是 contextvar；
            # 池 worker 是常驻线程，不会自动继承请求上下文——必须在捕获到的
            # context 里跑业务，否则 commit_guard / 预算检查 / 归属校验全部失效。
            ctx.run(task)
        except Exception:
            # 任务内部（idempotency store + coordinator.run_submitted）已把业务
            # 错误折进请求状态（failed/expired/unknown）并落 journal；这里吞掉
            # 异常只是防止单个任务崩掉整个 worker 线程。
            pass
        finally:
            _pool.task_done()


def get_pool() -> queue.Queue[tuple[contextvars.Context, Callable[[], Any]]]:
    """惰性建池：首次 submit 时按配置起守护线程（默认池大小 8）。"""
    global _pool
    with _start_lock:
        if _pool is not None:
            return _pool
        size = max(4, getattr(get_settings(), "scope_async_pool_size", 8))
        _pool = queue.Queue()
        for _ in range(size):
            thread = threading.Thread(target=_worker, name="aesir-async-pool", daemon=True)
            thread.start()
            _workers.append(thread)
        return _pool


def submit(task: Callable[[], Any]) -> None:
    """把一个已完成校验/准入的业务闭包投递到后台执行。

    捕获提交时刻的 context（含 scope/principal/budget），后台在同一上下文里跑。
    """
    ctx = contextvars.copy_context()
    get_pool().put((ctx, task))
