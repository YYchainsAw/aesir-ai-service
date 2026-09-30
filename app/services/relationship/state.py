"""关系状态持久化（SDD T037 / FR-015、FR-018）。

按角色分区落盘 ``data/relationship/<game_id>/<npc_id>/relationship.json``，原子写入
+ 单版本备份 + 损坏隔离——与 Phase 3 记忆存储同一套故障语义：

- 主文件损坏 → 先尝试恢复 ``.bak``，再不行隔离为 ``.corrupt`` 并回退初值
  （FR-018：回退初值后服务仍可用，不中断玩家流程）；
- 目录不可写 → 抛 ``RelationshipStoreError``，由调用方降级。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from app.config import get_settings
from app.schemas.relationship import RelationshipState
from app.services.relationship.rules import apply_relationship_event, stage_of


_DEFAULT_GAME_ID = "aesir"


class RelationshipStoreError(RuntimeError):
    """关系存储故障（不可写/IO 失败）；调用方捕获后降级，不得中断玩家流程。"""


class RelationshipStore:
    """单个 NPC 的关系状态存储；线程安全，写穿透落盘。"""

    def __init__(
        self,
        npc_id: str,
        *,
        game_id: str = _DEFAULT_GAME_ID,
        root: str | None = None,
    ) -> None:
        settings = get_settings()
        self.npc_id = npc_id
        self.game_id = game_id
        # 多游戏隔离：路径为 <relationship_root>/<game_id>/<npc_id>（S1）
        self._dir = Path(root or settings.relationship_root) / game_id / npc_id
        self._path = self._dir / "relationship.json"
        self._lock = threading.Lock()
        self._state = RelationshipState(value=settings.relationship_initial, stage="")

    # -- 读取 ---------------------------------------------------------------
    def load(self) -> None:
        """从磁盘读回；损坏先回退备份，再不行隔离并回退初值（降级路径）。"""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._fallback_to_backup_or_initial()
            return
        except OSError as error:
            raise RelationshipStoreError(f"关系文件不可读：{self._path}") from error

        try:
            data = json.loads(raw)
            state = RelationshipState.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            # 保留损坏现场（.corrupt），尝试备份，否则回退初值
            self._quarantine()
            self._fallback_to_backup_or_initial()
            return
        self._set(state)

    def state(self) -> RelationshipState:
        with self._lock:
            return self._state.model_copy(deep=True)

    # -- 写入 ---------------------------------------------------------------
    def apply_event(
        self,
        event_type: str,
        occurred_at: str | None = None,
        *,
        cooldown_seconds: float | None = None,
    ) -> tuple[RelationshipState, int]:
        """计分一条事实事件并落盘；返回（新状态快照, 实际计分值）。

        ``cooldown_seconds`` 覆盖默认冷却窗口（对话信号用更严的窗口：
        对话每轮都发生，60 秒拦不住连点刷分）。
        """
        with self._lock:
            new_state, delta = apply_relationship_event(
                self._state, event_type, occurred_at, cooldown_seconds=cooldown_seconds
            )
            if delta != 0:
                self._set(new_state)
                self._persist_locked()
            return new_state.model_copy(deep=True), delta

    def reset(self) -> None:
        """关系重置（调试/新周目）：回初值并清空留痕。"""
        with self._lock:
            self._set(RelationshipState(value=get_settings().relationship_initial, stage=""))
            self._persist_locked()

    # -- 内部 ---------------------------------------------------------------
    def _set(self, state: RelationshipState) -> None:
        """采纳状态并重算阶段（阶段是持久化冗余，加载/写入时同步）。"""
        state.stage = stage_of(state.value)
        self._state = state

    def _persist_locked(self) -> None:
        """原子写入（tmp + rename）+ 单版本备份（.bak）。调用方须持锁。"""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise RelationshipStoreError(f"关系目录不可创建：{self._dir}") from error

        payload = json.dumps(self._state.model_dump(mode="json"), ensure_ascii=False, indent=2)
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            if self._path.exists():
                os.replace(self._path, self._path.with_suffix(".json.bak"))
            os.replace(tmp, self._path)
        except OSError as error:
            raise RelationshipStoreError(f"关系写入失败：{self._path}") from error

    def _quarantine(self) -> None:
        try:
            os.replace(self._path, self._path.with_suffix(".json.corrupt"))
        except OSError:
            pass  # 隔离失败也继续：回退初值运行（保守降级）

    def _fallback_to_backup_or_initial(self) -> None:
        """主文件缺失/损坏后：备份可用则恢复备份，否则回退初值。"""
        bak = self._path.with_suffix(".json.bak")
        if bak.exists():
            try:
                state = RelationshipState.model_validate(json.loads(bak.read_text(encoding="utf-8")))
                self._set(state)
                return
            except (OSError, json.JSONDecodeError, ValueError):
                pass  # 备份也坏 → 回退初值
        self._set(RelationshipState(value=get_settings().relationship_initial, stage=""))


# ---------------------------------------------------------------------------
# 进程级缓存入口：同一角色复用同一实例（与 MemoryStore 同思路）。
# ---------------------------------------------------------------------------
_stores: dict[str, RelationshipStore] = {}
_stores_lock = threading.Lock()


def get_relationship_store(
    npc_id: str, *, game_id: str = _DEFAULT_GAME_ID, root: str | None = None
) -> RelationshipStore:
    """获取（并惰性加载）该角色的关系存储；测试可传 root 隔离目录。

    缓存按「角色 + game_id + 实际根目录」失效：配置根目录变化时重建实例。
    """
    effective_root = str(
        Path(root if root is not None else get_settings().relationship_root)
        / game_id
        / npc_id
    )
    cache_key = (npc_id, game_id, root)
    with _stores_lock:
        store = _stores.get(cache_key)
        if store is None or str(store._dir) != effective_root:
            store = RelationshipStore(npc_id, game_id=game_id, root=root)
            store.load()
            _stores[cache_key] = store
        return store


def reset_relationship_stores() -> None:
    """清空实例缓存（仅测试用；磁盘数据不动）。"""
    with _stores_lock:
        _stores.clear()
