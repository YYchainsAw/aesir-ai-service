"""分级记忆存储（SDD T025 / FR-006~FR-008 + 模糊印象层）。

四级存储（短期 / 摘要 / 档案 / 模糊印象）+ 容量淘汰 + 原子落盘 + 单版本备份
+ 按角色分区。模糊印象按主题合并计数、权重随半衰期衰减，见 ``topics.py``。
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
from app.schemas.memory import MemoryEntry, MemorySnapshot, TopicImpression
from app.services.memory.summarizer import summarize_experiences
from app.services.memory.topics import extract_topics as _extract_topics
from app.services.memory.topics import impression_weight as _impression_weight
from app.services.memory.topics import is_blocked_topic as _is_blocked_topic
from app.services.memory.topics import looks_like_noise as _looks_like_noise

# 淘汰序：重要性越低越先淘汰；同级别按时间越旧越先淘汰（FR-008）
_IMPORTANCE_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _days_since(iso_timestamp: str) -> float:
    """ISO 时间戳距今天数；解析失败按 0（宁可高估印象不强算丢失）。"""
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400.0)


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
        impression_limit: int | None = None,
    ) -> None:
        settings = get_settings()
        self.npc_id = npc_id
        self._dir = Path(root or settings.memory_root) / npc_id
        self._path = self._dir / "memory.json"
        self._short_term_limit = short_term_limit if short_term_limit is not None else settings.memory_short_term_limit
        self._summary_limit = summary_limit if summary_limit is not None else settings.memory_summary_limit
        self._archive_limit = archive_limit if archive_limit is not None else settings.memory_archive_limit
        self._impression_limit = impression_limit if impression_limit is not None else settings.memory_impression_limit
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
    def record_mention(
        self, topics: list[str], *, salient: bool = False, salience_boost: float | None = None
    ) -> None:
        """模糊印象：合并同主题计数、刷新权重后落盘；超限淘汰最淡印象。

        正式路径 ``topics`` 由 LLM 顺带返回；空列表直接跳过（如 LLM
        未返回或本轮无显著主题）。黑名单主题（角色自指 / 元语言碎片）
        在合并入口统一过滤。``salient`` 为郑重声明（双通道之一）：
        等效提及加成 + 更长半衰期；主题一旦显著不回退。``salience_boost``
        为按在意值缩放后的加成（声明时定格，见 ``topics.care_scale``）；
        ``None`` 用全局默认。写失败抛 ``MemoryStoreError``，由调用方
        静默降级（与 ``append_short_term`` 同语义）。
        """
        if not topics:
            return
        now = _utc_now_iso()
        with self._lock:
            self._merge_mentions_locked(
                topics, now=now, salient=salient, salience_boost=salience_boost
            )
            self._evict_impressions_locked()
            self._persist_locked()

    def migrate_verbatim_to_impressions(self) -> int:
        """一次性迁移：逐字玩家发言转为主题印象后从短期层移除。

        每条历史发言按一次提及计（频率语义与在线路径一致）。无显著主题的
        条目也一并移出短期层（不再逐字长期保留）。返回迁移的条数。
        """
        with self._lock:
            dialogue = [
                entry
                for entry in self._snapshot.short_term
                if entry.source == "player_statement" and "dialogue" in entry.tags
            ]
            if not dialogue:
                return 0
            self._snapshot.short_term = [
                entry for entry in self._snapshot.short_term if entry not in dialogue
            ]
            for entry in dialogue:
                topics = _extract_topics(entry.content)
                if topics:
                    self._merge_mentions_locked(
                        topics, now=entry.real_time or _utc_now_iso()
                    )
            self._evict_impressions_locked()
            self._persist_locked()
            return len(dialogue)

    def _merge_mentions_locked(
        self,
        topics: list[str],
        *,
        now: str,
        salient: bool = False,
        salience_boost: float | None = None,
    ) -> None:
        """按主题合并计数并刷新权重（调用方须持锁）。

        黑名单主题统一在此过滤——LLM 顺带返回、规则提取、迁移脚本三条
        路径都汇到本入口。显著话题的 ``salience_boost`` 取历史最大值：
        在意加深可以强化，淡化不回退（与 ``salient`` 旗标同一语义）。
        """
        existing = {i.topic: i for i in self._snapshot.impressions}
        for topic in topics:
            if _is_blocked_topic(topic) or _looks_like_noise(topic):
                continue
            effective_boost = salience_boost if salient else None
            prior = existing.get(topic)
            if prior is None:
                impression = TopicImpression(
                    topic=topic,
                    salient=salient,
                    salience_boost=effective_boost,
                    last_seen=now,
                )
                impression.weight = _impression_weight(
                    mention_count=impression.mention_count,
                    last_seen_days_ago=_days_since(impression.last_seen),
                    salient=impression.salient,
                    salience_boost=impression.salience_boost,
                )
                self._snapshot.impressions.append(impression)
                existing[topic] = impression
                continue
            prior.mention_count += 1
            prior.last_seen = now
            if salient:
                prior.salient = True
                if effective_boost is not None:
                    prior.salience_boost = max(
                        effective_boost, prior.salience_boost or 0.0
                    )
            prior.weight = _impression_weight(
                mention_count=prior.mention_count,
                last_seen_days_ago=_days_since(prior.last_seen),
                salient=prior.salient,
                salience_boost=prior.salience_boost,
            )

    def _evict_impressions_locked(self) -> None:
        """超出印象容量时淘汰权重最低的（调用方须持锁）。"""
        limit = self._impression_limit
        overflow = len(self._snapshot.impressions) - limit
        if overflow <= 0:
            return
        by_weight = sorted(
            self._snapshot.impressions,
            key=lambda i: (i.weight, i.last_seen),
        )
        drop = {i.topic for i in by_weight[:overflow]}
        self._snapshot.impressions = [
            i for i in self._snapshot.impressions if i.topic not in drop
        ]

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
