"""有界、进程内执行反馈账本；执行仅为 UE 自报，不推断命中或完成。"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
from threading import RLock
import json
import os
import time

from app.config import get_settings
from app.scoped.context import use_scope
from app.scoped.errors import ScopeError
from app.scoped.storage import commit_guard, signal_directory, signal_metadata

_TERMINAL = frozenset({"executed", "rejected", "expired", "cancelled"})


def _fingerprint(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class Issued:
    binding_id: str
    encounter_id: str | None
    request_id: str
    ability_id: str | None
    memory_epoch: str
    fingerprint: str
    expires_at: float
    state: str = "issued"
    last_result: str | None = None
    sequence: int | None = None
    receipt_count: int = 0
    sequences: dict[int, str] = field(default_factory=dict)
    unsequenced: set[str] = field(default_factory=set)


class DirectiveRegistry:
    def __init__(self, *, max_entries=4096, retention_seconds=300,
                 max_receipts_per_order=64, clock=time.monotonic):
        if max_entries < 1 or retention_seconds <= 0 or max_receipts_per_order < 1:
            raise ValueError("Directive ledger limits must be positive")
        self.lock = RLock()
        self.entries = {}
        self.poisoned_runs = set()
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self.max_receipts_per_order = max_receipts_per_order
        self.clock = clock

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.poisoned_runs.clear()

    def register(self, scope, request_id, directive):
        with use_scope(scope), commit_guard(scope), self.lock:
            self._check_writable(scope)
            now = self.clock()
            # 不确定提交不自动遗忘/重做；占用有界槽位至显式清理或进程退出。
            for key in [k for k, v in self.entries.items()
                        if v.state != "unknown" and v.expires_at <= now]:
                del self.entries[key]
            key = (*scope.key, str(directive["directive_id"]))
            issued = self.entries.get(key)
            fp = _fingerprint(directive)
            if issued is not None:
                self._lookup(scope, directive["directive_id"])
                if issued.request_id != str(request_id) or issued.fingerprint != fp:
                    raise ScopeError(409, "DIRECTIVE_ID_CONFLICT", "Directive ID is already bound to another payload or request")
                if issued.state == "unknown":
                    raise self._unavailable()
                return
            if len(self.entries) >= self.max_entries:
                raise ScopeError(503, "STATE_UNAVAILABLE", "Directive ledger capacity reached")
            self.entries[key] = Issued(
                str(scope.run_binding_id), str(scope.encounter_id) if scope.encounter_id else None,
                str(request_id), directive.get("payload", {}).get("ability_id"),
                str(scope.memory_epoch), fp, now + self.retention_seconds,
            )

    @staticmethod
    def _unavailable():
        return ScopeError(503, "STATE_UNAVAILABLE", "Directive outcome is uncertain; do not automatically resubmit")

    def _check_writable(self, scope):
        if scope.key in self.poisoned_runs:
            raise ScopeError(503, "STATE_UNAVAILABLE", "Receipt log has an uncertain append; manual reconciliation is required")

    def _lookup(self, scope, order_id, *, missing_status=409):
        issued = self.entries.get((*scope.key, str(order_id)))
        if (issued is None or (issued.state != "unknown" and issued.expires_at <= self.clock())
                or issued.binding_id != str(scope.run_binding_id)):
            raise ScopeError(missing_status, "DIRECTIVE_UNKNOWN", "No issued directive matches this scope and binding")
        if issued.memory_epoch != str(scope.memory_epoch):
            raise ScopeError(409, "MEMORY_EPOCH_STALE", "Directive predates the memory reset; do not relabel its receipts")
        encounter_id = str(scope.encounter_id) if scope.encounter_id else None
        if issued.encounter_id != encounter_id:
            raise ScopeError(409, "DIRECTIVE_MISMATCH", "Directive encounter does not match the request scope")
        return issued

    def state(self, scope, order_id):
        """返回最后确认的进程内反馈；unknown 不表示 UE 的执行终态。"""
        with use_scope(scope), commit_guard(scope), self.lock:
            issued = self._lookup(scope, order_id, missing_status=404)
            return {"directive_id": str(order_id), "origin_request_id": issued.request_id,
                    "state": issued.state, "last_result": issued.last_result,
                    "terminal": issued.state in _TERMINAL, "sequence": issued.sequence,
                    "receipt_count": issued.receipt_count}

    def record(self, scope, receipts):
        with use_scope(scope), commit_guard(scope), self.lock:
            self._check_writable(scope)
            staged, records, written_keys = {}, [], set()
            for receipt in receipts:
                key = (*scope.key, str(receipt.order_id))
                original = self._lookup(scope, receipt.order_id)
                if original.state == "unknown":
                    raise self._unavailable()
                encounter_id = str(receipt.encounter_id) if receipt.encounter_id else None
                if (original.encounter_id != encounter_id
                        or (receipt.request_id and str(receipt.request_id) != original.request_id)
                        or (receipt.ability_id and receipt.ability_id != original.ability_id)
                        or (receipt.agent_id and receipt.agent_id != scope.npc.companion_id)):
                    raise ScopeError(409, "DIRECTIVE_MISMATCH", "Receipt association does not match the issued directive")
                issued = staged.setdefault(key, deepcopy(original))
                data = receipt.model_dump(mode="json")
                semantic = {k: v for k, v in data.items() if k != "received_at"}
                fp = _fingerprint(semantic)
                if receipt.sequence is not None:
                    previous = issued.sequences.get(receipt.sequence)
                    if previous is not None:
                        if previous != fp:
                            raise ScopeError(409, "RECEIPT_SEQUENCE_CONFLICT", "Receipt sequence is already bound to different content")
                        continue
                elif fp in issued.unsequenced:
                    continue
                if issued.state in _TERMINAL and receipt.result not in {"accepted", issued.state}:
                    raise ScopeError(409, "RECEIPT_STATE_CONFLICT", "A terminal receipt cannot be replaced by another result")
                if len(issued.sequences) + len(issued.unsequenced) >= self.max_receipts_per_order:
                    raise ScopeError(503, "STATE_UNAVAILABLE", "Directive receipt history capacity reached")
                if receipt.sequence is None:
                    issued.unsequenced.add(fp)
                else:
                    issued.sequences[receipt.sequence] = fp
                # 迟到 accepted 的身份同样有界去重，但不追加，也不改变终态/序号。
                if issued.state in _TERMINAL and receipt.result == "accepted":
                    continue
                issued.state = issued.last_result = receipt.result
                issued.sequence = receipt.sequence
                issued.receipt_count += 1
                records.append({**data, "scope": signal_metadata()})
                written_keys.add(key)
            if records:
                path = signal_directory(get_settings().receipts_dir, scope.npc.game_id) / "scoped-executions.jsonl"
                payload = "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in records)
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # 整批先验证/演算，再一次追加；不根据 reported_at 重排 UE 事实。
                    with path.open("a", encoding="utf-8") as stream:
                        if stream.write(payload) != len(payload):
                            raise OSError("Incomplete receipt append")
                        stream.flush()
                        os.fsync(stream.fileno())
                except OSError as error:
                    # 不自动截断/覆盖可能的残片。每个封锁 run 至少由一个永久
                    # unknown 槽位承载，所以封锁集合也受 max_entries 限制。
                    self.poisoned_runs.add(scope.key)
                    # 部分写入或 fsync 失败后不采纳演算状态；阻止新 request_id 重做。
                    for key in written_keys:
                        self.entries[key].state = "unknown"
                    raise self._unavailable() from error
            self.entries.update(staged)
            return len(records)


registry = DirectiveRegistry()