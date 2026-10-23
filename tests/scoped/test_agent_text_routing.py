"""Both agent HTTP entries preserve the addressed companion during intent parsing."""

import pytest

from test_scoped_api import h


class IntentClient:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.system_prompt = ""

    def generate_json(self, *, system_prompt, user_prompt, temperature):
        self.system_prompt = system_prompt
        if self.fail:
            raise RuntimeError("intent provider unavailable")
        return {
            "recognized": True,
            "intent": {"intent_id": "follow_player", "target_id": "party.player"},
        }


@pytest.fixture(params=["legacy", "scoped"])
def text_step_api(h, monkeypatch, request):
    """Exercise the real parser and action mapping through either public HTTP entry."""
    legacy = request.param == "legacy"
    if legacy:
        monkeypatch.setenv("AESIR_SCOPE_LEGACY_ENABLED", "true")

    def post(companion_id, text):
        context = h.bind(npc=companion_id)
        payload = h.agent(context, text=text)
        payload["world_context"]["player"]["id"] = "player.from.snapshot"
        if legacy:
            payload = {
                key: payload[key]
                for key in ("request_id", "companion_id", "text", "world_context")
            }
            payload["protocol_version"] = "0.3"
        path = "/v1/agent/step" if legacy else "/v1/scoped/agent/step"
        response = h.client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["request_id"] == payload["request_id"]
        identity = body["companion_id"] if legacy else body["scope"]["companion_id"]
        assert identity == companion_id
        assert body["observability"]["used_snapshot_id"] == payload["world_context"]["snapshot_id"]
        return body

    return post


@pytest.fixture(params=["rule", "rule_fallback"])
def rule_source(h, monkeypatch, request):
    if request.param == "rule_fallback":
        from app.services.llm import factory

        monkeypatch.setenv("AESIR_INTENT_BACKEND", "llm")
        monkeypatch.setattr(factory, "create_llm_client", lambda: IntentClient(fail=True))
    else:
        monkeypatch.setenv("AESIR_INTENT_BACKEND", "rule")
    return request.param


@pytest.mark.parametrize("companion_id,text", [
    ("companion.alice", "艾莉，跟着我"),
    ("companion.alice", "EIRIN follow"),
    ("companion.bruno", "布鲁诺，跟着我"),
    ("companion.bruno", "BRUNO follow"),
])
def test_rule_command_uses_companion_wake_words(text_step_api, rule_source, companion_id, text):
    body = text_step_api(companion_id, text)
    assert body["action"] == "directive"
    assert body["directive"]["agent_id"] == companion_id
    assert body["directive"]["action_type"] == "follow"
    assert body["directive"]["source"] == "player_command"
    assert body["directive"]["payload"] == {"target_id": "player.from.snapshot"}
    assert body["observability"]["source"] == rule_source
    assert body["observability"]["degraded"] is (rule_source == "rule_fallback")
    assert "INTENT:follow_player" in body["observability"]["reason_codes"]


@pytest.mark.parametrize("companion_id,text", [
    ("companion.bruno", "艾莉，跟着我"),
    ("companion.alice", "布鲁诺，跟着我"),
    ("companion.bruno", "跟着我"),
    ("companion.alice", "跟着我"),
    ("companion.bruno", "布鲁诺，今天天气不错"),
])
def test_rule_text_without_matching_command_never_issues_action(
    text_step_api, rule_source, companion_id, text
):
    body = text_step_api(companion_id, text)
    assert body["action"] == "none"
    assert body["directive"] is None
    assert body["reply_text"]
    assert "INTENT_UNRECOGNIZED" in body["observability"]["reason_codes"]
    assert "CHITCHAT_DIALOGUE" in body["observability"]["reason_codes"]


@pytest.mark.parametrize("companion_id,name", [
    ("companion.alice", "艾莉"),
    ("companion.bruno", "布鲁诺"),
])
def test_llm_command_prompt_and_directive_use_requested_companion(
    text_step_api, monkeypatch, companion_id, name
):
    from app.services.llm import factory

    client = IntentClient()
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "llm")
    monkeypatch.setattr(factory, "create_llm_client", lambda: client)
    body = text_step_api(companion_id, f"{name}，一起走吧")
    assert f"玩家指令都发给队友 {name}。" in client.system_prompt
    assert body["action"] == "directive"
    assert body["directive"]["agent_id"] == companion_id
    assert body["directive"]["action_type"] == "follow"
    assert body["directive"]["payload"] == {"target_id": "player.from.snapshot"}
    assert body["observability"]["source"] == "llm"
