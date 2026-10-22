"""Real OpenAI-compatible HTTP boundaries under local MockTransport only."""
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from app.scoped.context import NpcScope, RequestScope, use_scope
from app.scoped.errors import ScopeError
from app.scoped.requests import RequestCoordinator, final_commit, reset_coordinator
from app.scoped.timing import TimingBudget
from app.scoped.trace import request_trace
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitBreakerLLMClient, CircuitState
from app.services.llm.client import OpenAICompatibleLLMClient, OpenAICompatibleSettings
from app.services.tactical.llm_intent import parse_intent_with_source
from test_scoped_api import h


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def scope():
    return RequestScope(NpcScope("aesir", uuid4(), uuid4(), "companion.alice"),
                        uuid4(), uuid4(), uuid4(), uuid4(), uuid4())


@pytest.fixture
def mock_clients():
    """All provider calls use an in-process transport and a reserved .invalid host."""
    clients = []

    def create(handler, *, provider_timeout=15, http_timeout=30):
        http_client = httpx.Client(transport=httpx.MockTransport(handler), timeout=http_timeout)
        clients.append(http_client)
        return OpenAICompatibleLLMClient(
            OpenAICompatibleSettings(api_key="TEST_PRIVATE_PROVIDER_KEY", model="test-model",
                                     base_url="https://llm.invalid/v1", timeout_seconds=provider_timeout),
            http_client=http_client,
        )

    yield create
    for client in clients:
        client.close()


def timing(clock, milliseconds=2000):
    return TimingBudget(dict(capture_age_ms=0, request_age_ms=0,
                             max_snapshot_age_ms=milliseconds, max_request_age_ms=milliseconds),
                        has_snapshot=False, clock=clock)


def completion(payload):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def heal_payload():
    return {"recognized": True, "intent": {"intent_id": "support_heal_player", "target_id": "party.player",
            "timing": "immediate", "strength": "minor", "resource_conservation": "normal"}}


def traces(root):
    return [json.loads(line) for path in Path(root).rglob("requests.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_actual_httpx_timeout_is_capped_by_remaining_budget_and_attempts_counted(scope, mock_clients):
    clock = Clock()
    coordinator = RequestCoordinator(clock=clock)
    request_id, observed = uuid4(), []

    def handler(request):
        observed.append(request.extensions["timeout"])
        assert request.url.path == "/v1/chat/completions"
        return completion({"ok": True})

    client = mock_clients(handler)

    def action():
        clock.advance(0.5)
        assert client.generate_json(system_prompt="system", user_prompt="first") == {"ok": True}
        clock.advance(0.25)
        return client.generate_json(system_prompt="system", user_prompt="second")

    assert coordinator.execute(scope, "chat", request_id, action, budget=timing(clock)) == {"ok": True}
    assert len(observed) == 2
    assert set(observed[0]) == {"connect", "read", "write", "pool"}
    assert all(value == pytest.approx(1.5) for value in observed[0].values())
    assert all(value == pytest.approx(1.25) for value in observed[1].values())
    assert coordinator.status(scope, "chat", request_id)["upstream_attempts"] == 2


def test_budget_cap_preserves_a_shorter_provider_timeout(scope, mock_clients):
    clock, observed = Clock(), []
    client = mock_clients(lambda request: (observed.append(request.extensions["timeout"]), completion({}))[1],
                          provider_timeout=0.25)
    RequestCoordinator().execute(scope, "chat", uuid4(),
        lambda: client.generate_json(system_prompt="system", user_prompt="player"), budget=timing(clock))
    assert all(value == pytest.approx(0.25) for value in observed[0].values())


def test_legacy_client_retains_its_http_client_timeout(mock_clients):
    observed = []
    client = mock_clients(lambda request: (observed.append(request.extensions["timeout"]), completion({}))[1],
                          provider_timeout=15, http_timeout=7)
    assert client.generate_json(system_prompt="system", user_prompt="legacy") == {}
    assert all(value == 7 for value in observed[0].values())


@pytest.mark.parametrize("control,phase,expected", [
    ("cancel", "before", "REQUEST_CANCELLED"),
    ("cancel", "after", "REQUEST_CANCELLED"),
    ("expiry", "before", "REQUEST_EXPIRED"),
    ("expiry", "after", "REQUEST_EXPIRED"),
    ("binding", "after", "RUN_BINDING_STALE"),
    ("epoch", "after", "MEMORY_EPOCH_STALE"),
])
def test_scope_control_is_never_swallowed_by_intent_fallback_or_breaker(
        scope, mock_clients, monkeypatch, control, phase, expected):
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "llm")
    clock = Clock()
    coordinator = RequestCoordinator(clock=clock)
    request_id, effects, requests = uuid4(), [], []
    stale = {"active": False}
    breaker = CircuitBreaker(failure_threshold=1)

    def invalidate():
        if control == "cancel":
            coordinator.cancel(scope, "agent-step", request_id)
        elif control == "expiry":
            clock.advance(2)
        else:
            stale["active"] = True

    def handler(request):
        requests.append(request)
        if phase == "after":
            invalidate()
        return completion(heal_payload())

    client = CircuitBreakerLLMClient(mock_clients(handler), breaker)

    def validate():
        if stale["active"]:
            raise ScopeError(409, expected, "The binding or epoch changed")

    def action():
        if phase == "before":
            invalidate()
        # The text is also recognized by the rule parser: swallowing ScopeError
        # here would turn cancellation/expiry into a successful rule fallback.
        parsed, source = parse_intent_with_source("艾莉，帮我回一下血", client=client)
        with final_commit():
            effects.append((parsed.intent_id, source))
        return source

    with pytest.raises(ScopeError) as error:
        coordinator.execute(scope, "agent-step", request_id, action,
                            budget=timing(clock), validate=validate)
    assert error.value.code == expected
    assert len(requests) == (0 if phase == "before" else 1)
    assert effects == []
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute()
    record = coordinator.status(scope, "agent-step", request_id)
    assert record["state"] == {"cancel": "cancelled", "expiry": "expired"}.get(control, "failed")
    assert record["upstream_attempts"] == (0 if phase == "before" else 1)


def test_actual_provider_failure_still_counts_for_breaker_and_allows_rule_fallback(scope, mock_clients, monkeypatch):
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "llm")
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(503, json={"error": "local mock unavailable"})

    breaker = CircuitBreaker(failure_threshold=1)
    client = CircuitBreakerLLMClient(mock_clients(handler), breaker)
    result = RequestCoordinator().execute(scope, "agent-step", uuid4(),
        lambda: parse_intent_with_source("艾莉，帮我回一下血", client=client))
    assert result[0].intent_id == "support_heal_player" and result[1] == "rule_fallback"
    assert len(observed) == 1 and breaker.state == CircuitState.OPEN


def test_trace_pairs_distinct_upstream_uuids_and_excludes_prompts_and_credentials(
        scope, mock_clients, monkeypatch, tmp_path):
    root = tmp_path / "trace"
    monkeypatch.setenv("AESIR_REQUEST_TRACES_DIR", str(root))
    coordinator = RequestCoordinator()
    request_id = uuid4()
    private_text = "PRIVATE_PLAYER_TEXT_328704"
    private_system = "PRIVATE_PERSONA_TEXT_328704"
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion({"reply": "PRIVATE_PROVIDER_REPLY_328704"})

    client = mock_clients(handler)

    def action():
        for _ in range(2):
            client.generate_json(system_prompt=private_system, user_prompt=private_text)
        return "safe result"

    with use_scope(scope), request_trace(scope, "chat", request_id):
        assert coordinator.execute(scope, "chat", request_id, action) == "safe result"
    rows = traces(root)
    starts = [row for row in rows if row["event"] == "upstream_started"]
    finishes = [row for row in rows if row["event"] == "upstream_finished"]
    inbound = [row for row in rows if row["event"] == "http_attempt_finished"]
    assert len(starts) == len(finishes) == 2 and len(inbound) == 1
    attempt_ids = {str(UUID(row["upstream_attempt_id"])) for row in starts}
    assert len(attempt_ids) == 2
    assert attempt_ids == {row["upstream_attempt_id"] for row in finishes}
    assert all(row["http_attempt_id"] == inbound[0]["http_attempt_id"] for row in rows)
    assert str(UUID(inbound[0]["http_attempt_id"])) == inbound[0]["http_attempt_id"]
    assert all(row["logical_request_id"] == str(request_id) for row in rows)
    assert requests[0]["messages"][1]["content"] == private_text
    encoded = json.dumps(rows)
    for secret in (private_text, private_system, "TEST_PRIVATE_PROVIDER_KEY", "PRIVATE_PROVIDER_REPLY_328704"):
        assert secret not in encoded
    assert coordinator.status(scope, "chat", request_id)["upstream_attempts"] == 2


def test_scoped_http_retries_get_new_transport_uuid_without_new_upstream_attempt(
        h, mock_clients, monkeypatch, tmp_path):
    import app.services.companion.llm_dialogue_service as dialogue
    root = tmp_path / "http-trace"
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")
    monkeypatch.setenv("AESIR_REQUEST_TRACES_DIR", str(root))
    coordinator = reset_coordinator()
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion({"reply_text": "好，我陪着你。", "emotion_id": "emotion.pleased",
                           "gesture_id": "gesture.enthusiastic_nod",
                           "facial_expression_id": "face.gentle_smile", "interruptible": True})

    breaker = CircuitBreaker(failure_threshold=1)
    client = CircuitBreakerLLMClient(mock_clients(handler), breaker)
    monkeypatch.setattr(dialogue, "create_llm_client", lambda: client)
    context = h.bind()
    private_text = "PRIVATE_HTTP_PLAYER_TEXT_901721"
    first = h.chat(context)
    first["text"] = private_text
    second = h.chat(context)
    second["text"] = "PRIVATE_HTTP_PLAYER_TEXT_901722"
    try:
        responses = [h.client.post("/v1/scoped/companion/chat", json=payload)
                     for payload in (first, first, second)]
        assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
        assert responses[0].json() == responses[1].json()
        assert all(response.json()["source"] == "llm" for response in responses)
        assert len(requests) == 2
        assert private_text in json.dumps(requests[0], ensure_ascii=False)
        rows = traces(root)
        inbound = [row for row in rows if row["event"] == "http_attempt_finished"]
        starts = [row for row in rows if row["event"] == "upstream_started"]
        assert len(inbound) == 3 and len(starts) == 2
        assert len({UUID(row["http_attempt_id"]) for row in inbound}) == 3
        assert len({UUID(row["upstream_attempt_id"]) for row in starts}) == 2
        assert sum(row["logical_request_id"] == first["request_id"] for row in inbound) == 2
        for payload in (first, second):
            record = coordinator.status(h.scope(context), "chat", payload["request_id"])
            assert record["upstream_attempts"] == 1 and record["state"] == "completed"
        serialized = json.dumps(rows)
        assert private_text not in serialized and "TEST_PRIVATE_PROVIDER_KEY" not in serialized
        assert breaker.state == CircuitState.CLOSED
    finally:
        coordinator.clear()
        reset_coordinator()