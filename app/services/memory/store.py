"""分级记忆存储（SDD T025 / FR-006~FR-008）。

三级存储（短期 / 摘要 / 档案）+ 容量淘汰 + 原子落盘 + 单版本备份 + 按角色分区。
持久化为本地文件 ``data/memory/<npc_id>/memory.json``（不引入数据库，章程原则 VII）。

故障语义（FR-011 / T030 的降级基础）：
- 目录不可写 / 磁盘故障 → 抛 ``MemoryStoreError``，由调用方捕获后降级为无长期
  记忆继续服务；
- 文件损坏 → 隔离为 ``memory.json.corrupt`` 并以空记忆继续（保留现场不覆盖）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from app.config import get_settings
from app.schemas.memory import MemoryEntry, MemorySnapshot
from app.services.memory.summarizer import summarize_experiences

# 淘汰序：重要性越低越先淘汰；同级别按时间越旧越先淘汰（FR-008）
_IMPORTANCE_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


class MemoryStoreError(RuntimeError):
    """记忆存储故障（不可写/IO 失败）；调用方捕获后降级，不得中断玩家流程。"""


class MemoryStore:
    """单个 NPC 的分级记忆存储；线程安全，写穿透落盘。"""

    def __init__(
        self,
        npc_id: str,
        *,
        root: str | None = None,
        short_term_limit: int | None = None,
        summary_limit: int | None = None,
        archive_limit: int | None = None,
    ) -> None:
        settings = get_settings()
        self.npc_id = npc_id
        self._dir = Path(root or settings.memory_root) / npc_id
        self._path = self._dir / "memory.json"
        self._short_term_limit = short_term_limit if short_term_limit is not None else settings.memory_short_term_limit
        self._summary_limit = summary_limit if summary_limit is not None else settings.memory_summary_limit
        self._archive_limit = archive_limit if archive_limit is not None else settings.memory_archive_limit
        self._lock = threading.Lock()
        self._snapshot = MemorySnapshot()

    # -- 读取 ---------------------------------------------------------------
    def load(self) -> None:
        """从磁盘读回；损坏则隔离并清空（降级路径）。"""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as error:
            raise MemoryStoreError(f"记忆文件不可读：{self._path}") from error

        try:
            data = json.loads(raw)
            self._snapshot = MemorySnapshot.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            # 保留损坏现场，隔离后以空记忆继续（FR-018 同思路的保守恢复）
            self._quarantine()
            self._snapshot = MemorySnapshot()

    def snapshot(self) -> MemorySnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    # -- 写入 ---------------------------------------------------------------
    def append_short_term(self, entry: MemoryEntry) -> None:
        """会话内短期上下文：滚动窗口淘汰最旧。"""
        with self._lock:
            self._snapshot.short_term.append(entry)
            self._snapshot.short_term = self._snapshot.short_term[-self._short_term_limit:]
            self._persist_locked()

    def record_experience(self, entries: list[MemoryEntry]) -> None:
        """共同经历：落盘时聚合为摘要条目（T026：事件触发，非逐条写盘）。"""
        if not entries:
            return
        with self._lock:
            self._snapshot.summaries.extend(summarize_experiences(entries))
            self._snapshot.summaries = self._evict(
                self._snapshot.summaries, self._summary_limit
            )
            self._persist_locked()

    def record_fact(self, entry: MemoryEntry) -> None:
        """长期档案：事实与承诺；承诺类（critical）不被淘汰（FR-008）。"""
        with self._lock:
            self._snapshot.archive.append(entry)
            self._snapshot.archive = self._evict(
                self._snapshot.archive, self._archive_limit, protect_promise=True
            )
            self._persist_locked()

    def clear(self) -> None:
        """清空该角色全部记忆（记忆重置，FR-010 / T029）。"""
        with self._lock:
            self._snapshot = MemorySnapshot()
            self._persist_locked()

    # -- 内部 ---------------------------------------------------------------
    @staticmethod
    def _evict(
        entries: list[MemoryEntry], limit: int, *, protect_promise: bool = False
    ) -> list[MemoryEntry]:
        """超限时按（重要性升序，时间升序）淘汰；被保护者不淘汰。"""
        overflow = len(entries) - limit
        if overflow <= 0:
            return entries

        protected: list[MemoryEntry] = []
        candidates: list[MemoryEntry] = []
        for entry in entries:
            if protect_promise and (entry.source == "promise" or entry.importance == "critical"):
                protected.append(entry)
            else:
                candidates.append(entry)

        # 淘汰序：重要性越低越先出列，同级别时间越旧越先出列（FR-008）
        candidates.sort(
            key=lambda e: (-_IMPORTANCE_ORDER.get(e.importance, 2), e.real_time)
        )
        keep = candidates[overflow:] if overflow <= len(candidates) else []
        survivors = {id(entry) for entry in protected + keep}
        return [entry for entry in entries if id(entry) in survivors]

    def _persist_locked(self) -> None:
        """原子写入（tmp + rename）+ 单版本备份（.bak）。调用方须持锁。"""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise MemoryStoreError(f"记忆目录不可创建：{self._dir}") from error

        payload = json.dumps(self._snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            if self._path.exists():
                os.replace(self._path, self._path.with_suffix(".json.bak"))
            os.replace(tmp, self._path)
        except OSError as error:
            raise MemoryStoreError(f"记忆写入失败：{self._path}") from error

    def _quarantine(self) -> None:
        try:
            os.replace(self._path, self._path.with_suffix(".json.corrupt"))
        except OSError:
            pass  # 隔离失败也继续：以空记忆运行（保守降级）


# ---------------------------------------------------------------------------
# 进程级缓存入口：同一角色复用同一实例（写入穿透，无需显式 save）。
# ---------------------------------------------------------------------------
_stores: dict[str, MemoryStore] = {}
_stores_lock = threading.Lock()


def get_memory_store(npc_id: str, *, root: str | None = None) -> MemoryStore:
    """获取（并惰性加载）该角色的记忆存储；测试可传 root 隔离目录。

    缓存按「角色 + 实际根目录」失效：配置的根目录变化（如测试切换
    AESIR_MEMORY_ROOT）时重建实例，避免读写到旧目录。
    """
    effective_root = str(Path(root if root is not None else get_settings().memory_root) / npc_id)
    with _stores_lock:
        store = _stores.get(npc_id)
        if store is None or str(store._dir) != effective_root:
            store = MemoryStore(npc_id, root=root)
            store.load()
            _stores[npc_id] = store
        return store


def reset_memory_stores() -> None:
    """清空实例缓存（仅测试用；磁盘数据不动）。"""
    with _stores_lock:
        _stores.clear()
