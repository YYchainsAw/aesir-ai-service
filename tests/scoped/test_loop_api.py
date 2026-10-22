"""HTTP execution-loop regressions with controlled local generation; no UE/provider."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Lock
import time
from uuid import uuid4

import pytest

from app.scoped.context import use_scope
from app.scoped.requests import get_coordinator, reset_coordinator
from app.schemas.companion_dialogue import CompanionDialogueResponse
from app.schemas.scoped import ScopedAgentResponse, ScopedChatResponse
from app.services.companion.session_memory import get_session_memory
from test_scoped_api import h, code


@pytest.fixture
def loop(h, monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_REQUEST_TRACES_DIR", str(tmp_path / "request_traces"))
    coordinator = reset_coordinator()
    coordinator.max_generation_concurrency = 2
    yield h
    coordinator.clear()
    reset_coordinator()


@pytest.fixture
def generation(monkeypatch):
    """Capture the history actually given to generation, before final writes."""
    calls = []
    lock = Lock()
    callback = {"run": lambda request: None}

    class LocalGeneration:
        def __init__(self, *, profile):
            self.last_topics = []
            self.last_facts = []
            self.last_reply_topics = []
            self.last_relationship_signal = "none"
            self.last_salient = False
            self.last_style_violations = []
            self.last_lookup = None

        def reply(self, request, *, history=(), **kwargs):
            with lock:
                calls.append((request.text, tuple(turn.user_text for turn in history)))
            callback["run"](request)
            return CompanionDialogueResponse(
                companion_id=request.companion_id,
                session_id=request.session_id,
                reply_text="A locally generated reply.",
                emotion_id="emotion.neutral",
                gesture_id="",
                facial_expression_id="",
                source="llm",
            )

    import app.services.companion.dialogue_service as dialogue
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")
    monkeypatch.setattr(dialogue, "LLMCompanionDialogueService", LocalGeneration)
    return calls, callback


def chat_payload(harness, context, **changes):
    payload = harness.chat(context)
    payload.update(changes)
    return payload


def query(harness, context, payload=None, **changes):
    params = harness.payload(context)
    params.pop("protocol_version")
    params.pop("request_id")
    if payload is not None:
        for key in ("session_id", "encounter_id"):
            if key in payload:
                params[key] = payload[key]
    params.update(changes)
    return params


def request_status(harness, context, payload, operation="chat"):
    return harness.client.get(
        f"/v1/scoped/requests/{payload['request_id']}",
        params=query(harness, context, payload, operation=operation),
    )


def directive_status(harness, context, directive_id):
    return harness.client.get(
        f"/v1/scoped/directives/{directive_id}", params=query(harness, context),
    )


def cancel(harness, context, payload, operation="chat", **changes):
    body = harness.payload(
        context,
        target_request_id=payload["request_id"],
        operation=operation,
        session_id=payload.get("session_id", context["run_id"]),
        encounter_id=payload.get("encounter_id"),
    )
    body.update(changes)
    return harness.client.post("/v1/scoped/requests/cancel", json=body)


def await_state(harness, context, payload, state, operation="chat"):
    deadline = time.monotonic() + 3
    latest = None
    while time.monotonic() < deadline:
        latest = request_status(harness, context, payload, operation)
        if latest.status_code == 200 and latest.json()["state"] == state:
            return latest.json()
        Event().wait(0.01)
    pytest.fail(f"request did not become {state}: {latest.status_code} {latest.text}")


def history(harness, context):
    with use_scope(harness.scope(context)):
        return get_session_memory(10).history(context["run_id"], "companion.alice")


def blocker(generation, first_text=None):
    entered, release = Event(), Event()

    def wait(request):
        if first_text is None or request.text == first_text:
            entered.set()
            assert release.wait(10), "test did not release local generation"

    generation[1]["run"] = wait
    return entered, release


def issue(harness, context):
    payload = harness.agent(context)
    result = harness.client.post("/v1/scoped/agent/step", json=payload)
    assert result.status_code == 200, result.text
    return payload, result.json()["directive"]["directive_id"]


def receipt(harness, context, origin, directive_id, result, sequence):
    item = dict(
        protocol_version="0.4",
        order_id=directive_id,
        request_id=origin["request_id"],
        agent_id="companion.alice",
        result=result,
        sequence=sequence,
    )
    return harness.client.post(
        "/v1/scoped/tactical/executions",
        json=harness.payload(context, receipt=item),
    )


def test_chat_and_agent_text_share_session_fifo_and_fresh_history(loop, generation):
    context = loop.bind()
    first = chat_payload(loop, context, text="First ordinary question")
    second = loop.agent(context, text="Another ordinary question")
    entered, release = blocker(generation, first["text"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=first)
        try:
            assert entered.wait(3)
            b = pool.submit(loop.client.post, "/v1/scoped/agent/step", json=second)
            await_state(loop, context, second, "queued", "agent-step")
            assert generation[0] == [(first["text"], ())]
        finally:
            release.set()
        for response in (a.result(timeout=3), b.result(timeout=3)):
            assert response.status_code == 200, response.text
    assert generation[0] == [(first["text"], ()), (second["text"], (first["text"],))]
    assert [turn.user_text for turn in history(loop, context)] == [first["text"], second["text"]]


def test_different_sessions_run_concurrently_up_to_global_limit(loop, generation):
    context = loop.bind()
    payloads = [
        chat_payload(loop, context, text=f"Session {index}", session_id=str(uuid4()))
        for index in range(3)
    ]
    both_entered, release = Event(), Event()
    active, maximum = 0, 0
    lock = Lock()

    def wait(request):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both_entered.set()
        try:
            assert release.wait(10)
        finally:
            with lock:
                active -= 1

    generation[1]["run"] = wait
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=payload)
            for payload in payloads[:2]
        ]
        try:
            assert both_entered.wait(3), "different sessions did not enter generation together"
            futures.append(pool.submit(
                loop.client.post, "/v1/scoped/companion/chat", json=payloads[2],
            ))
            await_state(loop, context, payloads[2], "queued")
            assert len(generation[0]) == 2
        finally:
            release.set()
        for future in futures:
            response = future.result(timeout=3)
            assert response.status_code == 200, response.text
    assert maximum == 2
    assert len(generation[0]) == 3
    assert all(seen_history == () for _, seen_history in generation[0])


def test_queued_cancel_never_generates_or_writes_its_turn(loop, generation):
    context = loop.bind()
    first = chat_payload(loop, context, text="Kept turn")
    second = chat_payload(loop, context, text="Cancelled queued turn")
    entered, release = blocker(generation, first["text"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=first)
        try:
            assert entered.wait(3)
            b = pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=second)
            await_state(loop, context, second, "queued")
            cancelled = cancel(loop, context, second)
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["state"] == "cancelled"
            assert cancelled.json()["cancel_requested"] is True
            code(b.result(timeout=3), 409, "REQUEST_CANCELLED")
        finally:
            release.set()
        assert a.result(timeout=3).status_code == 200
    assert generation[0] == [(first["text"], ())]
    assert [turn.user_text for turn in history(loop, context)] == [first["text"]]


def test_running_cancel_prevents_history_and_long_term_writes(loop, generation, tmp_path):
    context = loop.bind()
    payload = loop.chat(context)
    before = {path: path.read_bytes() for path in (tmp_path / "memory").rglob("*.json")}
    entered, release = blocker(generation)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=payload)
        try:
            assert entered.wait(3)
            cancelled = cancel(loop, context, payload, reason_code="SUPERSEDED")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["reason_code"] == "SUPERSEDED"
            await_state(loop, context, payload, "cancelled")
        finally:
            release.set()
        code(future.result(timeout=3), 409, "REQUEST_CANCELLED")
    assert history(loop, context) == ()
    assert {path: path.read_bytes() for path in (tmp_path / "memory").rglob("*.json")} == before


def test_prearrival_cancel_tombstone_blocks_late_request(loop, generation):
    context = loop.bind()
    payload = loop.chat(context)
    cancelled = cancel(loop, context, payload)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    late = loop.client.post("/v1/scoped/companion/chat", json=payload)
    code(late, 409, "REQUEST_CANCELLED")
    assert request_status(loop, context, payload).json()["state"] == "cancelled"
    assert generation[0] == []
    assert history(loop, context) == ()


def test_completed_request_cannot_be_retroactively_cancelled(loop, generation):
    context = loop.bind()
    payload = loop.chat(context)
    response = loop.client.post("/v1/scoped/companion/chat", json=payload)
    assert response.status_code == 200, response.text
    cancelled = cancel(loop, context, payload)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "completed"
    assert cancelled.json()["cancel_requested"] is False
    assert len(history(loop, context)) == 1


@pytest.mark.parametrize("invalidate,expected", [
    ("binding", "RUN_BINDING_STALE"), ("epoch", "MEMORY_EPOCH_STALE"),
])
def test_stale_binding_and_epoch_cannot_read_or_cancel(loop, invalidate, expected):
    context = loop.bind()
    origin, directive_id = issue(loop, context)
    if invalidate == "binding":
        loop.bind()
    else:
        reset = loop.client.post("/v1/scoped/console/memory/reset", json=loop.payload(context))
        assert reset.status_code == 200, reset.text
    code(request_status(loop, context, origin, "agent-step"), 409, expected)
    code(directive_status(loop, context, directive_id), 409, expected)
    code(cancel(loop, context, origin, "agent-step"), 409, expected)


def test_unknown_request_and_directive_reads_are_404_receipt_is_409(loop):
    context = loop.bind()
    unknown = loop.chat(context)
    code(request_status(loop, context, unknown), 404, "REQUEST_UNKNOWN")
    unknown_directive = str(uuid4())
    code(directive_status(loop, context, unknown_directive), 404, "DIRECTIVE_UNKNOWN")
    code(receipt(loop, context, unknown, unknown_directive, "accepted", 0), 409, "DIRECTIVE_UNKNOWN")


def test_concurrent_retries_single_flight_generation_and_history(loop, generation, monkeypatch):
    context = loop.bind()
    payload = loop.chat(context)
    entered, release = blocker(generation)
    from app.scoped.idempotency import get_request_store

    # Observe the duplicate's actual wait, so a slow HTTP dispatch cannot turn
    # this into a completed-result cache test.
    duplicate_waiting = Event()
    condition = get_request_store()._condition
    original_wait = condition.wait

    def observe_duplicate_wait(timeout=None):
        duplicate_waiting.set()
        return original_wait(timeout=timeout)

    monkeypatch.setattr(condition, "wait", observe_duplicate_wait)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=payload)
        try:
            assert entered.wait(3)
            second = pool.submit(
                loop.client.post, "/v1/scoped/companion/chat", json=deepcopy(payload),
            )
            assert duplicate_waiting.wait(3), "retry never waited for the running owner"
            await_state(loop, context, payload, "running")
            assert len(generation[0]) == 1
        finally:
            release.set()
        a, b = first.result(timeout=3), second.result(timeout=3)
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json() == b.json()
    assert len(generation[0]) == 1
    assert len(history(loop, context)) == 1


def test_rule_heartbeat_does_not_wait_for_blocked_chat(loop, generation):
    context = loop.bind()
    payload = loop.chat(context)
    entered, release = blocker(generation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        chat = pool.submit(loop.client.post, "/v1/scoped/companion/chat", json=payload)
        try:
            assert entered.wait(3)
            heartbeat = pool.submit(
                loop.client.post, "/v1/scoped/agent/step",
                json=loop.agent(context, text=None),
            )
            response = heartbeat.result(timeout=3)
            assert response.status_code == 200, response.text
            assert not chat.done()
            assert len(generation[0]) == 1
        finally:
            release.set()
        assert chat.result(timeout=3).status_code == 200


def test_receipts_progress_once_ignore_late_accepted_and_reject_terminal_conflict(loop, tmp_path):
    context = loop.bind()
    origin, directive_id = issue(loop, context)
    issued = directive_status(loop, context, directive_id)
    assert issued.status_code == 200, issued.text
    assert issued.json()["state"] == "issued"
    assert issued.json()["receipt_count"] == 0

    accepted = receipt(loop, context, origin, directive_id, "accepted", 0)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["stored"] == 1
    state = directive_status(loop, context, directive_id).json()
    assert (state["state"], state["terminal"], state["receipt_count"]) == ("accepted", False, 1)
    duplicate = receipt(loop, context, origin, directive_id, "accepted", 0)
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["stored"] == 0

    executed = receipt(loop, context, origin, directive_id, "executed", 1)
    assert executed.status_code == 202, executed.text
    assert executed.json()["stored"] == 1
    late = receipt(loop, context, origin, directive_id, "accepted", 2)
    assert late.status_code == 202, late.text
    assert late.json()["stored"] == 0
    state = directive_status(loop, context, directive_id).json()
    assert (state["state"], state["last_result"], state["terminal"]) == ("executed", "executed", True)
    assert (state["sequence"], state["receipt_count"]) == (1, 2)
    code(receipt(loop, context, origin, directive_id, "rejected", 3), 409, "RECEIPT_STATE_CONFLICT")
    files = list((tmp_path / "receipts_dir").rglob("*.jsonl"))
    assert len(files) == 1
    assert len(files[0].read_text().splitlines()) == 2


def test_query_views_are_read_only_and_cannot_refresh_executable_results(loop):
    context = loop.bind()
    origin, directive_id = issue(loop, context)
    for response in (
        request_status(loop, context, origin, "agent-step"),
        directive_status(loop, context, directive_id),
    ):
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["request_id"] is None
        assert not {"directive", "payload", "timing", "reply_text", "valid_for_ms"} & view.keys()
        assert view["scope"] == context["scope"]
        assert view["run_binding_id"] == context["run_binding_id"]


def test_existing_chat_and_agent_json_fields_remain_compatible(loop):
    context = loop.bind()
    golden = Path(__file__).resolve().parents[2] / "data/golden/scoped"
    samples = [
        ("/v1/scoped/companion/chat", loop.chat(context), ScopedChatResponse, "chat_response.json"),
        ("/v1/scoped/agent/step", loop.agent(context), ScopedAgentResponse, "agent_step_directive_response.json"),
    ]
    for path, payload, model, filename in samples:
        response = loop.client.post(path, json=payload)
        assert response.status_code == 200, response.text
        parsed = model.model_validate(response.json())
        assert parsed.protocol_version == "0.4"
        assert set(response.json()) == set(json.loads((golden / filename).read_text()))


def test_expiry_after_final_commit_reports_unknown_without_reexecuting(loop, generation, monkeypatch):
    """A post-owner idempotency check must not label committed effects expired."""
    from app.api.v1 import scoped as scoped_routes
    from app.scoped.idempotency import get_request_store
    from app.scoped.timing import TimingBudget

    context = loop.bind()
    payload = loop.chat(context)
    payload["timing"]["max_request_age_ms"] = 500
    now = [1000.0]

    def controlled_budget(timing, **kwargs):
        return TimingBudget(timing, clock=lambda: now[0], **kwargs)

    monkeypatch.setattr(scoped_routes, "TimingBudget", controlled_budget)
    store = get_request_store()
    original_execute = store.execute

    def delay_outer_checks(key, body, operation, **kwargs):
        def completed_owner():
            result = operation()
            if key[-2] == "chat":
                # The coordinator has finished its own checks and committed
                # the turn; expire only the enclosing store's final check.
                now[0] += 1.0
            return result

        return original_execute(key, body, completed_owner, **kwargs)

    monkeypatch.setattr(store, "execute", delay_outer_checks)
    first = loop.client.post("/v1/scoped/companion/chat", json=payload)
    code(first, 503, "REQUEST_OUTCOME_UNKNOWN")
    status = request_status(loop, context, payload)
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "unknown"
    assert status.json()["reason_code"] == "REQUEST_OUTCOME_UNKNOWN"
    assert len(history(loop, context)) == 1
    assert len(generation[0]) == 1

    cancelled = cancel(loop, context, payload)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "unknown"
    assert cancelled.json()["cancel_requested"] is False
    repeated = loop.client.post("/v1/scoped/companion/chat", json=payload)
    assert repeated.status_code in (409, 503), repeated.text
    assert repeated.json()["detail"]["code"] in ("REQUEST_EXPIRED", "REQUEST_OUTCOME_UNKNOWN")
    assert request_status(loop, context, payload).json()["state"] == "unknown"
    assert len(history(loop, context)) == len(generation[0]) == 1
