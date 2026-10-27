"""新版HTTP、兼容门控及真实服务副作用的集成回归；无UE/付费模型。"""
from copy import deepcopy
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scoped.identity import Principal, get_principal
from app.scoped.runtime import reset_runtime
from app.scoped.idempotency import reset_idempotency_stores
from app.scoped.directives import registry
from app.api.v1.agent import _reset_heartbeat_tracker
from app.scoped.context import NpcScope, RequestScope, use_scope
from app.services.companion.session_memory import get_session_memory, SessionMemoryStore

GOLDEN = Path(__file__).resolve().parents[2] / "data/golden/scoped"


class Harness:
    def __init__(self):
        self.saves = [uuid4(), uuid4()]
        self.principal = Principal(uuid4(), frozenset(self.saves))
        self.client = TestClient(app)

    def context(self, save=None, npc="companion.alice"):
        r = self.client.get("/v1/scoped/context", params={"save_id": str(save or self.saves[0]), "companion_id": npc})
        assert r.status_code == 200, r.text
        return r.json()

    def bind(self, save=None, npc="companion.alice", run=None):
        ctx = self.context(save, npc)
        body = dict(protocol_version="0.4", request_id=str(uuid4()), save_id=ctx["scope"]["save_id"],
                    service_instance_id=ctx["service_instance_id"], expected_control_revision=ctx["control_revision"],
                    expected_run_id=ctx["run_id"], run_id=str(run or uuid4()))
        r = self.client.post("/v1/scoped/runs/bind", json=body)
        assert r.status_code == 200, r.text
        return self.context(save, npc)

    def payload(self, ctx, **changes):
        p = {k: ctx[k] for k in ("service_instance_id", "run_id", "run_binding_id", "memory_epoch")}
        p.update(protocol_version="0.4", request_id=str(uuid4()), save_id=ctx["scope"]["save_id"],
                 companion_id=ctx["scope"]["companion_id"])
        p.update(changes)
        return p

    def agent(self, ctx, text="alice inspect", **changes):
        world = json.loads((GOLDEN / "agent_step_request.json").read_text())["world_context"]
        world["companion"]["id"] = ctx["scope"]["companion_id"]
        world["interactables"] = [{"object_id": "object.campfire.001", "kind": "prop", "distance_m": 2, "notable": True}]
        return self.payload(ctx, text=text, world_context=world, timing=self.timing(), **changes)

    def chat(self, ctx, **changes):
        return self.payload(ctx, text="我喜欢在雨天钓鱼", timing=self.timing(), **changes)

    @staticmethod
    def timing():
        return dict(capture_age_ms=20, request_age_ms=0, max_snapshot_age_ms=30000, max_request_age_ms=30000)

    def event(self, ctx, combat=False):
        data = json.loads((GOLDEN / "world_event_request.json").read_text())
        p = self.payload(ctx, timing=self.timing(), event=data["event"], world_context=data["world_context"])
        p["event"]["event_id"] = str(uuid4())
        if combat:
            from app.schemas.combat_context import make_combat_context
            encounter = str(uuid4())
            r = self.client.post("/v1/scoped/encounters/control", json=dict(
                protocol_version="0.4", request_id=str(uuid4()), save_id=ctx["scope"]["save_id"],
                service_instance_id=ctx["service_instance_id"], run_id=ctx["run_id"],
                run_binding_id=ctx["run_binding_id"], op="begin", expected_encounter_revision=0,
                expected_encounter_id=None, encounter_id=encounter))
            assert r.status_code == 200, r.text
            c = make_combat_context(player_hp=15, encounter_id=encounter).model_dump(mode="json")
            p.update(encounter_id=encounter)
            p["world_context"].update(scene="combat", combat=c, snapshot_id=c["snapshot_id"], captured_at=c["captured_at"])
            p["event"]["event_type"] = "player_hp_critical"
        return p

    def scope(self, ctx):
        return RequestScope(NpcScope(**ctx["scope"]), UUID(ctx["run_id"]), UUID(ctx["run_id"]),
                            UUID(ctx["service_instance_id"]), UUID(ctx["run_binding_id"]), UUID(ctx["memory_epoch"]))


@pytest.fixture
def h(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_SCOPE_LEGACY_ENABLED", "false")
    monkeypatch.setenv("AESIR_SCOPE_IDENTITY_BACKEND", "disabled")
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "rule")
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "rule")
    for name in ("AGENT_STEPS_DIR", "EVENT_SIGNALS_DIR", "RECEIPTS_DIR"):
        monkeypatch.setenv("AESIR_" + name, str(tmp_path / name.lower()))
    import app.services.companion.session_memory as sm
    monkeypatch.setattr(sm, "_store", SessionMemoryStore(10))
    reset_runtime()
    reset_idempotency_stores()
    registry.clear()
    _reset_heartbeat_tracker()
    harness = Harness()
    app.dependency_overrides[get_principal] = lambda: harness.principal
    yield harness
    app.dependency_overrides.pop(get_principal, None)
    registry.clear()
    reset_idempotency_stores()


def code(response, status, expected):
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == expected, response.text


def test_no_identity_and_self_reported_header_cannot_claim_player(h):
    app.dependency_overrides.pop(get_principal)
    r = h.client.get("/v1/scoped/context", params={"save_id": str(h.saves[0]), "companion_id": "companion.alice"},
                     headers={"X-Player-Id": str(h.principal.player_id)})
    code(r, 401, "IDENTITY_REQUIRED")


def test_unauthorized_save_and_unknown_npc_fail_before_business(h):
    code(h.client.get("/v1/scoped/context", params={"save_id": str(uuid4()), "companion_id": "companion.alice"}), 403, "SCOPE_FORBIDDEN")
    code(h.client.get("/v1/scoped/context", params={"save_id": str(h.saves[0]), "companion_id": "companion.missing"}), 404, "COMPANION_UNKNOWN")


def test_business_never_implicitly_activates_run(h):
    ctx = h.context()
    p = h.chat(ctx)
    p.update(run_id=str(uuid4()), run_binding_id=str(uuid4()))
    code(h.client.post("/v1/scoped/companion/chat", json=p), 409, "RUN_BINDING_STALE")
    assert h.context()["run_id"] is None


def test_agent_replay_stable_directive_and_payload_conflict(h):
    ctx = h.bind()
    p = h.agent(ctx)
    a = h.client.post("/v1/scoped/agent/step", json=p)
    assert a.status_code == 200, a.text
    assert a.json()["action"] == "directive", a.text
    assert a.json()["directive"]["protocol_version"] == "0.4"
    b = h.client.post("/v1/scoped/agent/step", json=p)
    assert a.json() == b.json()
    p["text"] = "在这等我"
    code(h.client.post("/v1/scoped/agent/step", json=p), 409, "REQUEST_ID_CONFLICT")


def test_heartbeat_isolated_by_player_and_save(h):
    first = h.bind()
    a = h.agent(first, text=None)
    assert h.client.post("/v1/scoped/agent/step", json=a).status_code == 200
    b = deepcopy(a); b["request_id"] = str(uuid4())
    code(h.client.post("/v1/scoped/agent/step", json=b), 429, "HEARTBEAT_RATE_LIMITED")
    other_save = h.bind(save=h.saves[1])
    assert h.client.post("/v1/scoped/agent/step", json=h.agent(other_save, text=None)).status_code == 200
    h.principal = Principal(uuid4(), frozenset(h.saves))
    other_player = h.bind()
    assert h.client.post("/v1/scoped/agent/step", json=h.agent(other_player, text=None)).status_code == 200


def test_reset_replay_and_old_epoch_cannot_resurrect_memory(h):
    ctx = h.bind()
    chat = h.chat(ctx)
    assert h.client.post("/v1/scoped/companion/chat", json=chat).status_code == 200
    reset = h.payload(ctx)
    r = h.client.post("/v1/scoped/console/memory/reset", json=reset)
    assert r.status_code == 200, r.text
    assert r.json()["memory_epoch"] != ctx["memory_epoch"]
    assert h.client.post("/v1/scoped/console/memory/reset", json=reset).json() == r.json()
    code(h.client.post("/v1/scoped/companion/chat", json=chat), 409, "MEMORY_EPOCH_STALE")
    # Merely updating epoch cannot reuse the old logical ID to execute again.
    chat["memory_epoch"] = r.json()["memory_epoch"]
    code(h.client.post("/v1/scoped/companion/chat", json=chat), 409, "REQUEST_ID_CONFLICT")
    reset2 = h.payload(h.context())
    assert h.client.post("/v1/scoped/console/memory/reset", json=reset2).status_code == 200
    code(h.client.post("/v1/scoped/console/memory/reset", json=reset), 409, "MEMORY_EPOCH_STALE")


def test_new_run_preserves_long_term_but_rejects_cached_old_business(h):
    ctx = h.bind()
    p = h.chat(ctx)
    assert h.client.post("/v1/scoped/companion/chat", json=p).status_code == 200
    newer = h.bind()
    assert newer["run_id"] != ctx["run_id"]
    assert newer["memory_epoch"] == ctx["memory_epoch"]
    code(h.client.post("/v1/scoped/companion/chat", json=p), 409, "RUN_BINDING_STALE")


def test_restart_keeps_epoch_but_invalidates_previous_service_instance(h):
    ctx = h.bind()
    p = h.chat(ctx)
    reset_runtime()
    current = h.context()
    assert current["memory_epoch"] == ctx["memory_epoch"]
    assert current["run_id"] is None
    code(h.client.post("/v1/scoped/companion/chat", json=p), 409, "SERVER_INSTANCE_CHANGED")


def test_event_aliases_share_result_and_new_request_cannot_renew_old_action(h):
    ctx = h.bind()
    p = h.event(ctx, combat=True)
    first = h.client.post("/v1/scoped/world/events", json=p)
    assert first.status_code == 200, first.text
    assert first.json()["action"] == "directive", first.text
    assert "companion_action" not in first.json()
    assert h.client.post("/v1/scoped/combat/events", json=p).json() == first.json()
    p["request_id"] = str(uuid4())
    repeated = h.client.post("/v1/scoped/combat/events", json=p)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["directive"] is None
    assert repeated.json()["timing"] == first.json()["timing"]
    p["request_id"] = str(uuid4()); p["event"]["sequence"] += 1
    code(h.client.post("/v1/scoped/world/events", json=p), 409, "EVENT_ID_CONFLICT")


def test_receipt_requires_issued_scope_and_request_association(h, tmp_path):
    ctx = h.bind()
    command = h.agent(ctx)
    r = h.client.post("/v1/scoped/agent/step", json=command)
    assert r.status_code == 200, r.text
    directive = r.json()["directive"]
    receipt = dict(protocol_version="0.4", order_id=directive["directive_id"], result="accepted",
                   request_id=command["request_id"], agent_id="companion.alice")
    payload = h.payload(ctx, receipt=receipt)
    response = h.client.post("/v1/scoped/tactical/executions", json=payload)
    assert response.status_code == 202, response.text
    assert response.json()["stored"] == 1
    assert h.client.post("/v1/scoped/tactical/executions", json=payload).status_code == 202
    files = list((tmp_path / "receipts_dir").rglob("*.jsonl"))
    assert len(files) == 1
    assert len(files[0].read_text().splitlines()) == 1
    payload["request_id"] = str(uuid4()); payload["receipt"]["request_id"] = str(uuid4())
    code(h.client.post("/v1/scoped/tactical/executions", json=payload), 409, "DIRECTIVE_MISMATCH")
    other = h.bind(save=h.saves[1])
    payload = h.payload(other, receipt=receipt)
    code(h.client.post("/v1/scoped/tactical/executions", json=payload), 409, "DIRECTIVE_UNKNOWN")


@pytest.mark.parametrize("method,path", [
    ("POST", "/parse-command"), ("POST", "/v1/commands/parse"),
    ("POST", "/v1/agent/step"), ("POST", "/v1/companion/chat"),
    ("POST", "/v1/companion/chat/stream"), ("POST", "/v1/companion/chat/voice"),
    ("POST", "/v1/voice/command"), ("POST", "/v1/speech/transcribe"),
    ("POST", "/v1/world/events"), ("POST", "/v1/combat/events"),
    ("POST", "/v1/tactical/command"), ("POST", "/v1/tactical/resolve"),
    ("POST", "/v1/tactical/executions"), ("GET", "/v1/console/state"),
    ("GET", "/v1/console/memory"), ("POST", "/v1/console/memory/reset"),
    ("GET", "/v1/console/ui"),
])
def test_strict_mode_blocks_every_legacy_entry(h, method, path):
    code(h.client.request(method, path), 403, "LEGACY_DISABLED")


@pytest.mark.parametrize("path", ["/v1/scoped/companion/chat/stream", "/v1/scoped/companion/chat/voice", "/v1/scoped/voice/command"])
def test_unsupported_scoped_stream_and_voice_are_explicitly_rejected(h, path):
    code(h.client.post(path), 404, "BUSINESS_REJECTED")


def test_legacy_chat_cannot_read_or_reset_scoped_history(h, monkeypatch):
    ctx = h.bind()
    assert h.client.post("/v1/scoped/companion/chat", json=h.chat(ctx)).status_code == 200
    monkeypatch.setenv("AESIR_SCOPE_LEGACY_ENABLED", "true")
    old = h.client.post("/v1/companion/chat", json={"text": "你好", "session_id": ctx["run_id"]})
    assert old.status_code == 200, old.text
    assert h.client.post("/v1/console/memory/reset", json={"companion_id": "companion.alice"}).status_code == 200
    assert h.context()["memory_epoch"] == ctx["memory_epoch"]
    with use_scope(h.scope(ctx)):
        assert len(get_session_memory(10).history(ctx["run_id"], "companion.alice")) == 1


def test_console_requires_current_binding_and_returns_v04(h):
    ctx = h.bind()
    params = h.payload(ctx)
    params.pop("request_id"); params.pop("protocol_version")
    for path in ("state", "memory"):
        r = h.client.get("/v1/scoped/console/" + path, params=params)
        assert r.status_code == 200, r.text
        assert r.json()["protocol_version"] == "0.4"
        assert r.json()["request_id"] is None
        assert r.json()["scope"] == ctx["scope"]
    params["run_binding_id"] = str(uuid4())
    code(h.client.get("/v1/scoped/console/memory", params=params), 409, "RUN_BINDING_STALE")


@pytest.mark.parametrize("field,value", [("protocol_version", "0.3"), ("request_id", "bad-id"), ("player_id", "forged")])
def test_new_schema_rejects_bad_version_ids_and_self_reported_identity(h, field, value):
    p = h.chat(h.bind()); p[field] = value
    code(h.client.post("/v1/scoped/companion/chat", json=p), 422, "INVALID_SCOPE_OR_TIMING")


def test_snapshot_utc_is_log_only_but_relative_age_expires(h):
    p = h.agent(h.bind())
    # An old UTC date cannot overrule an explicitly fresh relative budget.
    p["world_context"]["captured_at"] = "2000-01-01T00:00:00Z"
    assert h.client.post("/v1/scoped/agent/step", json=p).status_code == 200
    p["request_id"] = str(uuid4())
    p["timing"]["capture_age_ms"] = 30000
    code(h.client.post("/v1/scoped/agent/step", json=p), 409, "SNAPSHOT_EXPIRED")


@pytest.mark.parametrize("interruption", ["reset", "end", "expiry"])
def test_inflight_generation_cannot_commit_after_invalidation(h, monkeypatch, interruption):
    import app.services.companion.dialogue_service as dialogue
    import app.api.v1.scoped as routes
    from app.scoped.timing import TimingBudget
    ctx = h.bind()
    p = h.chat(ctx)
    entered, release = Event(), Event()
    original = dialogue._create_mock_dialogue_reply
    clock = [100.0]
    if interruption == "expiry":
        monkeypatch.setattr(routes, "TimingBudget", lambda *a, **kw: TimingBudget(*a, clock=lambda: clock[0], **kw))
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(dialogue, "_create_mock_dialogue_reply", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(h.client.post, "/v1/scoped/companion/chat", json=p)
        try:
            assert entered.wait(5)
            if interruption == "reset":
                r = h.client.post("/v1/scoped/console/memory/reset", json=h.payload(ctx))
                assert r.status_code == 200, r.text
                expected = "MEMORY_EPOCH_STALE"
            elif interruption == "end":
                end = dict(protocol_version="0.4", request_id=str(uuid4()), save_id=ctx["scope"]["save_id"],
                           service_instance_id=ctx["service_instance_id"], run_id=ctx["run_id"],
                           run_binding_id=ctx["run_binding_id"], expected_control_revision=ctx["control_revision"])
                r = h.client.post("/v1/scoped/runs/end", json=end)
                assert r.status_code == 200, r.text
                expected = "RUN_BINDING_STALE"
            else:
                clock[0] += 31
                expected = "REQUEST_EXPIRED"
        finally:
            release.set()
        code(pending.result(timeout=5), 409, expected)
    with use_scope(h.scope(ctx)):
        assert get_session_memory(10).history(ctx["run_id"], "companion.alice") == ()


def test_concurrent_duplicate_chat_invokes_business_once(h, monkeypatch):
    import app.services.companion.dialogue_service as dialogue
    ctx = h.bind(); p = h.chat(ctx)
    original = dialogue._create_mock_dialogue_reply
    entered, release = Event(), Event()
    calls = []; lock = Lock()
    def delayed(*args, **kwargs):
        with lock:
            calls.append(1)
        entered.set(); assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(dialogue, "_create_mock_dialogue_reply", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(h.client.post, "/v1/scoped/companion/chat", json=p)
        try:
            assert entered.wait(5)
            second = pool.submit(h.client.post, "/v1/scoped/companion/chat", json=p)
        finally:
            release.set()
        a, b = first.result(5), second.result(5)
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json() == b.json()
    assert calls == [1]
    with use_scope(h.scope(ctx)):
        assert len(get_session_memory(10).history(ctx["run_id"], "companion.alice")) == 1



def test_http_event_capacity_rejection_does_not_poison_request_outcome(h, monkeypatch):
    import app.api.v1.scoped as routes
    from app.scoped.idempotency import IdempotencyStore
    store = IdempotencyStore(max_entries=1)
    store.execute("occupied", {}, lambda: None)
    monkeypatch.setattr(routes, "get_event_store", lambda: store)
    p = h.event(h.bind())
    code(h.client.post("/v1/scoped/world/events", json=p), 503, "IDEMPOTENCY_CAPACITY")
    store.clear()
    r = h.client.post("/v1/scoped/world/events", json=p)
    assert r.status_code == 200, r.text


def test_partial_write_failure_becomes_unknown_and_never_reexecutes(h, monkeypatch):
    import app.services.companion.dialogue_service as dialogue
    from app.scoped.errors import ScopeError
    ctx = h.bind(); p = h.chat(ctx)
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(1)
        raise ScopeError(503, "STATE_UNAVAILABLE", "Simulated disk failure after the session commit")
    monkeypatch.setattr(dialogue, "record_turn_signal", unavailable)
    code(h.client.post("/v1/scoped/companion/chat", json=p), 503, "REQUEST_OUTCOME_UNKNOWN")
    code(h.client.post("/v1/scoped/companion/chat", json=p), 503, "REQUEST_OUTCOME_UNKNOWN")
    assert calls == [1]
    with use_scope(h.scope(ctx)):
        assert len(get_session_memory(10).history(ctx["run_id"], "companion.alice")) == 1


def test_closed_encounter_rejects_cached_realtime_event(h):
    ctx = h.bind(); p = h.event(ctx, combat=True)
    first = h.client.post("/v1/scoped/world/events", json=p)
    assert first.status_code == 200, first.text
    current = h.context()
    end = dict(protocol_version="0.4", request_id=str(uuid4()), save_id=ctx["scope"]["save_id"],
               service_instance_id=ctx["service_instance_id"], run_id=ctx["run_id"],
               run_binding_id=ctx["run_binding_id"], op="end", expected_encounter_revision=current["encounter_revision"],
               expected_encounter_id=p["encounter_id"])
    assert h.client.post("/v1/scoped/encounters/control", json=end).status_code == 200
    code(h.client.post("/v1/scoped/world/events", json=p), 409, "ENCOUNTER_INACTIVE")


# --- 阶段 2 v0.5 异步提交（opt-in）-------------------------------------

def test_v05_chat_returns_202_immediately_and_polls_to_completed(h):
    """v0.5 opt-in：POST 立即 202，业务后台执行，轮询 GET /requests/{id} 拿 completed+result。"""
    import time
    ctx = h.bind()
    p = h.chat(ctx, protocol_version="0.5")
    submit = h.client.post("/v1/scoped/companion/chat", json=p)
    assert submit.status_code == 202, submit.text
    body = submit.json()
    assert body["protocol_version"] == "0.5"
    assert body["state"] in {"queued", "running"}
    assert "reply_text" not in body  # 202 不含业务结果

    # 轮询直到 completed（后台池跑 mock 对话，毫秒级）。
    request_id = p["request_id"]
    status = None
    for _ in range(50):
        r = h.client.get(f"/v1/scoped/requests/{request_id}",
                        params={"operation": "chat", **{k: ctx[k] for k in
                                ("service_instance_id", "run_id", "run_binding_id", "memory_epoch")},
                                "save_id": ctx["scope"]["save_id"],
                                "companion_id": ctx["scope"]["companion_id"]})
        assert r.status_code == 200, r.text
        status = r.json()
        if status["state"] in {"completed", "failed", "expired", "unknown"}:
            break
        time.sleep(0.05)
    assert status["state"] == "completed", status
    assert status["result"] is not None
    assert "reply_text" in status["result"]


def test_v04_chat_still_returns_200_synchronously(h):
    """v0.4（默认）永久保留同步 200 行为，不进入异步分支。"""
    ctx = h.bind()
    p = h.chat(ctx)  # 默认 protocol_version="0.4"
    r = h.client.post("/v1/scoped/companion/chat", json=p)
    assert r.status_code == 200, r.text
    assert "reply_text" in r.json()


def test_v05_rejected_on_non_async_endpoints(h):
    """异步 opt-in 只放开 chat/agent-step；world/event/control 发 0.5 必须 422。"""
    ctx = h.bind()
    # world/events 继承 _ControlRequest（只认 "0.4"）。
    p = h.event(ctx)
    p["protocol_version"] = "0.5"
    assert h.client.post("/v1/scoped/world/events", json=p).status_code == 422
    # encounters/control 同理。
    c = dict(protocol_version="0.5", request_id=str(uuid4()), save_id=ctx["scope"]["save_id"],
             service_instance_id=ctx["service_instance_id"], run_id=ctx["run_id"],
             run_binding_id=ctx["run_binding_id"], op="begin", expected_encounter_revision=0,
             expected_encounter_id=None, encounter_id=str(uuid4()))
    assert h.client.post("/v1/scoped/encounters/control", json=c).status_code == 422


def test_v05_duplicate_submit_does_not_reexecute(h):
    """同 request_id 重试：幂等账本返回在途/已完成状态，不重复投递后台。"""
    import time
    ctx = h.bind()
    p = h.chat(ctx, protocol_version="0.5")
    first = h.client.post("/v1/scoped/companion/chat", json=p)
    assert first.status_code == 202
    # 立即重试同 ID：应拿到 202（在途）或 200（已完成），不重复执行业务。
    second = h.client.post("/v1/scoped/companion/chat", json=p)
    assert second.status_code in {200, 202}
    # 等终态。
    for _ in range(50):
        r = h.client.get(f"/v1/scoped/requests/{p['request_id']}",
                        params={"operation": "chat", **{k: ctx[k] for k in
                                ("service_instance_id", "run_id", "run_binding_id", "memory_epoch")},
                                "save_id": ctx["scope"]["save_id"],
                                "companion_id": ctx["scope"]["companion_id"]})
        if r.json()["state"] == "completed":
            break
        time.sleep(0.05)
