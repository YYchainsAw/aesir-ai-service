"""SQL-backed directive facts and receipt identities, staged in the request UoW."""
from copy import deepcopy
import time

from app.persistence.database import read_document, write_document, state_version
from app.persistence.uow import current_uow
from app.scoped.context import use_scope
from app.scoped.directives import _fingerprint
from app.scoped.errors import ScopeError
from app.scoped.storage import commit_guard

_TERMINAL = frozenset({"executed", "rejected", "expired", "cancelled"})


class SQLDirectiveRegistry:
    def __init__(self, *, retention_seconds=300, max_receipts_per_order=64, clock=time.time):
        self.retention_seconds = retention_seconds
        self.max_receipts_per_order = max_receipts_per_order
        self.clock = clock

    def clear(self):
        """No volatile cache; clearing a runtime never deletes SQL facts."""

    def _write(self, scope, key, payload):
        if current_uow() is None:
            raise ScopeError(503, "STATE_UNAVAILABLE", "Directive changes require a business transaction")
        write_document("directive", key, payload, scope_parts=scope.npc.key)

    def _lookup(self, scope, order_id, *, missing_status=409):
        data = read_document("directive", (*scope.key, str(order_id)))
        if (data is None or data["binding_id"] != str(scope.run_binding_id)
                or (data["state"] != "unknown" and data["expires_at"] <= self.clock())):
            raise ScopeError(missing_status, "DIRECTIVE_UNKNOWN", "No issued directive matches this scope and binding")
        if data["memory_epoch"] != str(scope.memory_epoch):
            raise ScopeError(409, "MEMORY_EPOCH_STALE", "The directive predates the memory reset")
        encounter = str(scope.encounter_id) if scope.encounter_id else None
        if data["encounter_id"] != encounter:
            raise ScopeError(409, "DIRECTIVE_MISMATCH", "Directive encounter does not match request scope")
        return data

    @staticmethod
    def _view(order_id, data):
        return dict(directive_id=str(order_id), origin_request_id=data["request_id"],
                    state=data["state"], last_result=data["last_result"],
                    terminal=data["state"] in _TERMINAL, sequence=data["sequence"],
                    receipt_count=data["receipt_count"])

    def register(self, scope, request_id, directive):
        with use_scope(scope), commit_guard(scope):
            key = (*scope.key, str(directive["directive_id"]))
            existing = read_document("directive", key)
            fp = _fingerprint(directive)
            if existing is not None:
                if existing["request_id"] != str(request_id) or existing["fingerprint"] != fp:
                    raise ScopeError(409, "DIRECTIVE_ID_CONFLICT", "The directive ID is already bound to different content")
                self._lookup(scope, directive["directive_id"])
                if existing["state"] == "unknown":
                    raise ScopeError(503, "STATE_UNAVAILABLE", "Directive outcome requires reconciliation")
                return
            self._write(scope, key, {
                "binding_id": str(scope.run_binding_id),
                "service_instance_id": str(scope.service_instance_id),
                "session_id": str(scope.session_id),
                "encounter_id": str(scope.encounter_id) if scope.encounter_id else None,
                "request_id": str(request_id),
                "ability_id": directive.get("payload", {}).get("ability_id"),
                "memory_epoch": str(scope.memory_epoch), "fingerprint": fp,
                "expires_at": self.clock() + self.retention_seconds,
                "state": "issued", "last_result": None, "sequence": None,
                "receipt_count": 0, "sequences": {}, "unsequenced": [],
            })

    def state(self, scope, order_id):
        with use_scope(scope), commit_guard(scope):
            return self._view(order_id, self._lookup(scope, order_id, missing_status=404))

    def recover(self, npc, run_id, order_id):
        """Historical facts survive expiry/rebind, but contain no executable payload."""
        data = read_document("directive", (*npc.key, str(run_id), str(order_id)))
        if data is None:
            raise ScopeError(404, "DIRECTIVE_UNKNOWN", "No historical directive exists in this scope")
        return {**self._view(order_id, data), "run_id": str(run_id),
                "origin_service_instance_id": data["service_instance_id"],
                "origin_memory_epoch": data["memory_epoch"]}

    def _prepare(self, npc, run_id, receipts, lookup, *, strict_association=False):
        staged, originals, records, new_identities = {}, {}, [], 0
        for receipt in receipts:
            key = (*npc.key, str(run_id), str(receipt.order_id))
            original = lookup(receipt)
            if original["state"] == "unknown":
                raise ScopeError(503, "STATE_UNAVAILABLE", "Directive outcome requires reconciliation")
            encounter = str(receipt.encounter_id) if receipt.encounter_id else None
            if (original["encounter_id"] != encounter
                    or (receipt.request_id and str(receipt.request_id) != original["request_id"])
                    or (receipt.ability_id and receipt.ability_id != original["ability_id"])
                    or (receipt.agent_id and receipt.agent_id != npc.companion_id)):
                raise ScopeError(409, "DIRECTIVE_MISMATCH", "Receipt association does not match the issued directive")
            if strict_association and (str(receipt.request_id) != original["request_id"]
                    or receipt.agent_id != npc.companion_id or receipt.ability_id != original["ability_id"]):
                raise ScopeError(409, "DIRECTIVE_MISMATCH", "Historical receipt must preserve the original association")
            originals.setdefault(key, original)
            data = staged.setdefault(key, deepcopy(original))
            value = receipt.model_dump(mode="json")
            fp = _fingerprint({k: v for k, v in value.items() if k != "received_at"})
            sequence = str(receipt.sequence) if receipt.sequence is not None else None
            if sequence is not None and sequence in data["sequences"]:
                if data["sequences"][sequence] != fp:
                    raise ScopeError(409, "RECEIPT_SEQUENCE_CONFLICT", "The sequence already has different content")
                continue
            if sequence is None and fp in data["unsequenced"]:
                continue
            if data["state"] in _TERMINAL and receipt.result not in {"accepted", data["state"]}:
                raise ScopeError(409, "RECEIPT_STATE_CONFLICT", "A terminal result cannot be replaced")
            if len(data["sequences"]) + len(data["unsequenced"]) >= self.max_receipts_per_order:
                raise ScopeError(503, "STATE_UNAVAILABLE", "Directive receipt identity capacity reached")
            new_identities += 1
            if sequence is None:
                data["unsequenced"].append(fp)
            else:
                data["sequences"][sequence] = fp
            if data["state"] in _TERMINAL and receipt.result == "accepted":
                continue
            data.update(state=receipt.result, last_result=receipt.result,
                        sequence=receipt.sequence, receipt_count=data["receipt_count"] + 1)
            metadata = {**npc.as_dict(), "run_id": str(run_id),
                        "memory_epoch": original["memory_epoch"],
                        "service_instance_id": original["service_instance_id"],
                        "run_binding_id": original["binding_id"],
                        "session_id": original.get("session_id"),
                        "encounter_id": original["encounter_id"]}
            records.append((key, "s:" + sequence if sequence is not None else "f:" + fp,
                            {**value, "scope": metadata}))
        changed = {key: value for key, value in staged.items() if value != originals[key]}
        return changed, records, new_identities

    def _persist_prepared(self, npc, staged, records):
        if current_uow() is None:
            raise ScopeError(503, "STATE_UNAVAILABLE", "Receipt changes require a business transaction")
        for key, data in staged.items():
            write_document("directive", key, data, scope_parts=npc.key)
        for key, identity, value in records:
            write_document("receipt", (*key, identity), value, scope_parts=npc.key)

    def record(self, scope, receipts):
        with use_scope(scope), commit_guard(scope):
            staged, records, _ = self._prepare(scope.npc, scope.run_id, receipts,
                                               lambda receipt: self._lookup(scope, receipt.order_id))
            self._persist_prepared(scope.npc, staged, records)
            return len(records)

    def archive(self, npc, origin_run_id, origin_memory_epoch, receipts, *, expected_state_version):
        """Archive known historical UE reports, without current-world execution.

        The caller holds the NPC lock and revalidates ownership before commit.
        Original binding/expiry are preserved as history, never reactivated.
        """
        def original(receipt):
            data = read_document("directive", (*npc.key, str(origin_run_id), str(receipt.order_id)))
            if data is None:
                raise ScopeError(409, "DIRECTIVE_UNKNOWN", "No original directive exists for this historical receipt")
            if data["memory_epoch"] != str(origin_memory_epoch):
                raise ScopeError(409, "MEMORY_EPOCH_STALE", "Receipt epoch differs from the original directive")
            return data

        staged, records, new_identities = self._prepare(npc, origin_run_id, receipts, original,
                                                        strict_association=True)
        if new_identities and state_version(npc.key) != expected_state_version:
            raise ScopeError(409, "STATE_VERSION_CONFLICT", "Refresh authoritative state before adding new receipts")
        self._persist_prepared(npc, staged, records)
        return len(records), new_identities == 0


sql_registry = SQLDirectiveRegistry()
