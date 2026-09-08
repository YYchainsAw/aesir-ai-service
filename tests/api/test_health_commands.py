from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.tactical_order import DEFAULT_CONTEXT, PROTOCOL_VERSION

client = TestClient(app)


@pytest.fixture(autouse=True)
def force_rule_tactical_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口测试不得调用开发者本机 .env 里的真实战术 LLM。"""
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "rule")


def _order_intent(body: dict) -> str:
    assert body["recognized"] is True
    assert body["order"] is not None
    return body["order"]["intent"]


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["protocol_version"] == PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# 遗留入口 /parse-command（只传 text，服务端回填默认能力目录）
# ---------------------------------------------------------------------------
def test_legacy_conditional_cast() -> None:
    response = client.post(
        "/parse-command",
        json={"text": "艾琳，等 Boss 眩晕时使用爆裂魔法。"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["protocol_version"] == "0.1"
    # 遗留入口未收 request_id → 服务端用 uuid4() 生成一个用于日志关联
    assert body["request_id"]
    UUID(body["request_id"])

    order = body["order"]
    assert order["intent"] == "conditional_cast"
    assert order["agent_id"] == "companion.alice"
    assert order["priority"] == 80
    assert order["when"] == {
        "type": "state_entered",
        "subject": "encounter.primary_hostile",
        "tag": "state.stunned",
    }
    assert order["then"] == {
        "type": "cast_ability",
        "ability_id": "ability.alice.explosion",
        "target": {"ref": "when.subject"},
    }
    # order_id 由 schema 生成，必须是合法 UUID 字符串
    assert order["order_id"]
    assert order["expires"] == {"type": "encounter_end"}


def test_legacy_hold_ability() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，保留爆裂魔法"})

    assert _order_intent(response.json()) == "hold_ability"
    assert response.json()["order"]["then"] == {
        "type": "hold_ability",
        "ability_id": "ability.alice.explosion",
        "active": True,
    }


def test_legacy_prioritize_attack() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，优先普通攻击"})

    assert _order_intent(response.json()) == "prioritize_attack"
    assert response.json()["order"]["then"] == {
        "type": "set_priority",
        "mode": "basic_attack_first",
    }


def test_legacy_follow_keep_distance() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，跟随我并保持距离"})

    assert _order_intent(response.json()) == "follow_keep_distance"
    assert response.json()["order"]["then"] == {
        "type": "follow",
        "target": "party.player",
        "keep_distance": True,
    }


def test_legacy_retreat() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，撤退并优先保命"})

    assert _order_intent(response.json()) == "retreat"
    assert response.json()["order"]["then"] == {"type": "retreat"}
    assert response.json()["order"]["priority"] == 90


def test_display_name_alias_alice_is_recognized() -> None:
    """统一到 companion.alice/艾莉 后，旧名「艾琳」仍作为别名被识别（向后兼容）。"""
    response = client.post("/parse-command", json={"text": "艾莉，撤退并优先保命"})

    assert _order_intent(response.json()) == "retreat"


def test_unknown_command_is_rejected_safely() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，马上释放不存在的技能"})

    assert response.status_code == 200
    assert response.json()["recognized"] is False
    assert response.json()["order"] is None


# ---------------------------------------------------------------------------
# 契约 v0.1 入口 /v1/commands/parse（携带能力目录 + request_id）
# ---------------------------------------------------------------------------
def test_v1_parse_echoes_request_id_and_context() -> None:
    request = {
        "protocol_version": "0.1",
        "request_id": "11111111-1111-1111-1111-111111111111",
        "text": "艾琳，撤退并优先保命",
        "context": DEFAULT_CONTEXT.model_dump(),
    }

    response = client.post("/v1/commands/parse", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert _order_intent(body) == "retreat"


def test_v1_parse_rejects_invalid_request_id() -> None:
    request = {
        "protocol_version": "0.1",
        "request_id": "not-a-uuid",
        "text": "艾琳，撤退",
        "context": DEFAULT_CONTEXT.model_dump(),
    }

    response = client.post("/v1/commands/parse", json=request)

    assert response.status_code == 422


def test_golden_contract_per_section_8() -> None:
    """契约《UE5-协议格式契约-v0.1.md》§8 的 5 份 golden 输入必须各自命中对应行。"""
    rid = "1fad2e69-4a2d-4308-ad4f-2f8abb338b89"
    golden = {
        "艾琳，等 Boss 眩晕时使用爆裂魔法。": (80, {
            "type": "state_entered",
            "subject": "encounter.primary_hostile",
            "tag": "state.stunned",
        }, {
            "type": "cast_ability",
            "ability_id": "ability.alice.explosion",
            "target": {"ref": "when.subject"},
        }),
        "艾琳，这一整场都不要放爆裂魔法。": (60, None, {
            "type": "hold_ability",
            "ability_id": "ability.alice.explosion",
            "active": True,
        }),
        "艾琳，优先普通攻击。": (50, None, {
            "type": "set_priority",
            "mode": "basic_attack_first",
        }),
        "艾琳，跟着我并保持距离。": (40, None, {
            "type": "follow",
            "target": "party.player",
            "keep_distance": True,
        }),
        "艾琳，撤退并优先保命。": (90, None, {"type": "retreat"}),
    }
    for text, (priority, when, then) in golden.items():
        request = {
            "protocol_version": "0.1",
            "request_id": rid,
            "text": text,
            "context": DEFAULT_CONTEXT.model_dump(),
        }
        body = client.post("/v1/commands/parse", json=request).json()
        assert body["recognized"] is True
        assert body["request_id"] == rid
        order = body["order"]
        assert order["agent_id"] == "companion.alice"
        assert order["priority"] == priority
        assert order["when"] == when
        assert order["then"] == then
        assert order["expires"] == {"type": "encounter_end"}
        # 契约 §7.1：order 内不携带 protocol_version
        assert "protocol_version" not in order
        UUID(order["order_id"])


def test_v1_parse_rejects_catalog_oob_ability() -> None:
    # 客户端声明能力目录里没有爆裂魔法 → 服务端不得产出越界 order
    request = {
        "protocol_version": "0.1",
        "request_id": "22222222-2222-2222-2222-222222222222",
        "text": "艾琳，等 Boss 眩晕时使用爆裂魔法",
        "context": {
            "catalog_revision": "dev-001",
            "locale": "zh-CN",
            "agents": [
                {
                    "id": "companion.alice",
                    "ability_ids": ["ability.alice.basic_attack"],
                }
            ],
            "target_selectors": ["encounter.primary_hostile"],
            "state_tags": ["state.stunned"],
        },
    }

    response = client.post("/v1/commands/parse", json=request)

    assert response.status_code == 200
    assert response.json()["recognized"] is False
    assert response.json()["order"] is None