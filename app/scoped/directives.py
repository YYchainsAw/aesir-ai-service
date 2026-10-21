"""进程内已发布指令关联；回执仅记录事实，不推进执行状态机。"""
from dataclasses import dataclass
from threading import RLock
import json
import os
import time

from app.config import get_settings
from app.scoped.errors import ScopeError
from app.scoped.storage import commit_guard, signal_directory, signal_metadata


@dataclass(frozen=True)
class Issued:
    binding_id: str
    encounter_id: str | None
    request_id: str
    ability_id: str | None
    expires_at: float


class DirectiveRegistry:
    def __init__(self, *, max_entries=4096, retention_seconds=300, clock=time.monotonic):
        self.lock = RLock()
        self.entries = {}
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self.clock = clock

    def clear(self):
        with self.lock:
            self.entries.clear()

    def register(self, scope, request_id, directive):
        with commit_guard(scope), self.lock:
            now = self.clock()
            for key in [k for k, v in self.entries.items() if v.expires_at <= now]:
                del self.entries[key]
            key = (*scope.key, str(directive["directive_id"]))
            if key not in self.entries and len(self.entries) >= self.max_entries:
                raise ScopeError(503, "STATE_UNAVAILABLE", "Directive association capacity reached")
            self.entries[key] = Issued(
                str(scope.run_binding_id), str(scope.encounter_id) if scope.encounter_id else None,
                str(request_id), directive.get("payload", {}).get("ability_id"),
                now + self.retention_seconds,
            )

    def record(self, scope, receipts):
        with commit_guard(scope), self.lock:
            for receipt in receipts:
                issued = self.entries.get((*scope.key, str(receipt.order_id)))
                if (issued is None or issued.expires_at <= self.clock()
                        or issued.binding_id != str(scope.run_binding_id)):
                    raise ScopeError(409, "DIRECTIVE_UNKNOWN", "No issued directive matches this scope and binding")
                encounter_id = str(receipt.encounter_id) if receipt.encounter_id else None
                if (issued.encounter_id != encounter_id
                        or (receipt.request_id and str(receipt.request_id) != issued.request_id)
                        or (receipt.ability_id and receipt.ability_id != issued.ability_id)):
                    raise ScopeError(409, "DIRECTIVE_MISMATCH", "Receipt association does not match the issued directive")
            records = [{**receipt.model_dump(mode="json"), "scope": signal_metadata()}
                       for receipt in receipts]
            path = signal_directory(get_settings().receipts_dir, scope.npc.game_id) / "scoped-executions.jsonl"
            # 单批一次追加；失败由外层占位标记 UNKNOWN，不自动重做不确定提交。
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in records))
                stream.flush()
                os.fsync(stream.fileno())
            return len(records)


registry = DirectiveRegistry()
