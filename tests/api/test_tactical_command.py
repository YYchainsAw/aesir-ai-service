"""`POST /v1/tactical/command` 组合端点测试：文本 + 快照 → 上下文决策一次到位。"""

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.combat_context import make_combat_context

client = TestClient(app)
RID = "99d7e6b4-f4f2-4d39-8c96-a23d293882f6"


def _payload(text: str, ctx) -> dict:
    return {
        "protocol_version": "0.2",
        "request_id": RID,
        "text": text,
        "combat_context": ctx.model_dump(),
    }


def test_heal_text_critical_snapshot_yields_major_heal() -> None:
    resp = client.post(
        "/v1/tactical/command",
        json=_payload("艾莉，帮我回一下血", make_combat_context(player_hp=18)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recognized"] is True
    decision = body["decision"]
    assert decision["status"] == "actionable"
    assert decision["action"]["ability_id"] == "ability.alice.major_heal"
    assert "PLAYER_HP_CRITICAL" in decision["reason_codes"]


def test_same_heal_text_different_snapshot_changes_action() -> None:
    """组合端点同样满足「同一句命令 × 不同战况 → 不同决策」的 v0.2 卖点。"""
    steady = client.post(
        "/v1/tactical/command",
        json=_payload("艾莉，帮我回一下血", make_combat_context(player_hp=65)),
    ).json()
    healthy = client.post(
        "/v1/tactical/command",
        json=_payload("艾莉，帮我回一下血", make_combat_context(player_hp=90)),
    ).json()
    assert steady["decision"]["action"]["ability_id"] == "ability.alice.quick_heal"
    assert healthy["decision"]["status"] == "not_actionable"


def test_colloquial_heal_and_retreat_and_burst() -> None:
    cases = [
        ("艾莉奶我一口", "support_heal_player", make_combat_context(player_hp=40)),
        ("艾莉，撤退并优先保命", "retreat_and_survive", make_combat_context(player_hp=50)),
        (
            "艾莉，等它晕了放大招",
            "prepare_burst_on_stun",
            make_combat_context(player_hp=70, boss_state_tags=[], stunned_remaining=None),
        ),
        ("艾莉，集火 Boss", "focus_fire_boss", make_combat_context(player_hp=70)),
        ("艾莉，跟着我", "follow_player", make_combat_context(player_hp=70)),
    ]
    for text, intent_id, ctx in cases:
        body = client.post("/v1/tactical/command", json=_payload(text, ctx)).json()
        assert body["recognized"] is True, text
        assert body["decision"]["intent_id"] == intent_id, text


def test_unrecognized_text_returns_clarification_not_guess() -> None:
    resp = client.post(
        "/v1/tactical/command",
        json=_payload("今天天气不错", make_combat_context(player_hp=50)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recognized"] is False
    assert body["decision"] is None
    assert "再说一遍" in body["companion_reply"]["reply_text"]


def test_text_without_wake_word_not_recognized() -> None:
    resp = client.post(
        "/v1/tactical/command",
        json=_payload("帮我回一下血", make_combat_context(player_hp=18)),
    )
    assert resp.status_code == 200
    assert resp.json()["recognized"] is False


def test_empty_text_rejected_with_422() -> None:
    resp = client.post(
        "/v1/tactical/command",
        json=_payload("", make_combat_context(player_hp=50)),
    )
    assert resp.status_code == 422


def test_llm_backend_without_config_falls_back_to_rule(monkeypatch) -> None:
    """AESIR_INTENT_BACKEND=llm 但 LLM 未配置（无 key）→ 回退规则，source 标记。

    注意 .env 里可能存在真实 key（load_dotenv 注入进程环境），测试必须
    显式清空，否则会发真实 LLM 请求。
    """
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "llm")
    monkeypatch.setenv("LLM_API_KEY", "")
    resp = client.post(
        "/v1/tactical/command",
        json=_payload("艾莉，帮我回一下血", make_combat_context(player_hp=18)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recognized"] is True
    assert body["source"] == "rule_fallback"
    assert body["decision"]["action"]["ability_id"] == "ability.alice.major_heal"


def test_llm_backend_misconfigured_text_unrecognized(monkeypatch) -> None:
    """LLM 不可用且规则也不识别 → 澄清回复，source 仍是 rule_fallback。"""
    monkeypatch.setenv("AESIR_INTENT_BACKEND", "llm")
    monkeypatch.setenv("LLM_API_KEY", "")
    resp = client.post(
        "/v1/tactical/command",
        json=_payload("今天天气不错", make_combat_context(player_hp=50)),
    )
    body = resp.json()
    assert body["recognized"] is False
    assert body["source"] == "rule_fallback"
