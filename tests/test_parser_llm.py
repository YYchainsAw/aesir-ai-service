import uuid
from typing import Any

import pytest

from app.schemas.tactical_order import DEFAULT_CONTEXT
from app.services.command_parser import parse_command
from app.services.parsers.llm import LLMCommandParser, LLMError

# 一个合法的 v0.1 conditional_cast order（全部 ID 命中 DEFAULT_CONTEXT 目录）
VALID_ORDER = {
    "order": {
        "agent_id": "companion.alice",
        "priority": 80,
        "intent": "conditional_cast",
        "when": {
            "type": "state_entered",
            "subject": "encounter.primary_hostile",
            "tag": "state.stunned",
        },
        "then": {
            "type": "cast_ability",
            "ability_id": "ability.alice.explosion",
            "target": {"ref": "when.subject"},
        },
    }
}


class StubLLMClient:
    """返回固定 payload 的 generate_json 桩，等价于真实 LLMClient 的产物。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate_json(self, *, system_prompt, user_prompt, temperature=0.2) -> dict[str, Any]:
        return self.payload


def _payload(**overrides) -> dict[str, Any]:
    base = {"recognized": True, **VALID_ORDER, "message": "ok"}
    base.update(overrides)
    return base


def test_recognizes_valid_intent() -> None:
    parser = LLMCommandParser(StubLLMClient(_payload()))

    result = parser.parse("等 Boss 眩晕了就放爆裂魔法", DEFAULT_CONTEXT)

    assert result.recognized is True
    assert result.order is not None
    assert result.order.intent == "conditional_cast"
    assert result.order.then.type == "cast_ability"
    assert result.order.when.tag == "state.stunned"


def test_recognized_false_output() -> None:
    parser = LLMCommandParser(
        StubLLMClient({"recognized": False, "order": None, "message": "nope"})
    )

    result = parser.parse("随便说点啥", DEFAULT_CONTEXT)

    assert result.recognized is False
    assert result.order is None


def test_extra_field_on_response_raises_llm_error() -> None:
    # 响应带未声明字段 → 严格校验拒绝
    parser = LLMCommandParser(StubLLMClient(_payload(unsafe_extra="must be rejected")))

    with pytest.raises(LLMError):
        parser.parse("放爆裂", DEFAULT_CONTEXT)


def test_out_of_catalog_ability_raises_llm_error() -> None:
    # 能力目录里没有该技能 → 目录越界校验拒绝
    bad = {
        "order": {
            "agent_id": "companion.alice",
            "intent": "conditional_cast",
            "when": {
                "type": "state_entered",
                "subject": "encounter.primary_hostile",
                "tag": "state.stunned",
            },
            "then": {
                "type": "cast_ability",
                "ability_id": "ability.alice.nuke",  # 不在白名单
                "target": {"ref": "when.subject"},
            },
        },
    }
    parser = LLMCommandParser(StubLLMClient(_payload(**bad)))

    with pytest.raises(LLMError):
        parser.parse("把世界核平了吧", DEFAULT_CONTEXT)


def test_unknown_agent_raises_llm_error() -> None:
    bad = {
        "order": {
            "agent_id": "companion.not_here",
            "intent": "hold_ability",
            "when": None,
            "then": {"type": "hold_ability", "ability_id": "ability.alice.explosion"},
        },
    }
    parser = LLMCommandParser(StubLLMClient(_payload(**bad)))

    with pytest.raises(LLMError):
        parser.parse("保留爆裂", DEFAULT_CONTEXT)


def test_request_id_is_echoed_through_llm() -> None:
    rid = uuid.uuid4()
    parser = LLMCommandParser(StubLLMClient(_payload()))

    result = parser.parse("放爆裂", DEFAULT_CONTEXT, request_id=rid)

    assert result.request_id == rid


def test_facade_falls_back_to_rule_without_key(monkeypatch) -> None:
    # 后端 llm 但未配 key → LLM 客户端构造失败 → facade 回退规则
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "llm")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    result = parse_command("艾琳，撤退并优先保命")

    assert result.recognized is True
    assert result.order.intent == "retreat"
    assert result.source == "rule_fallback"


def test_facade_uses_rule_when_llm_unsure(monkeypatch) -> None:
    # LLM 明确 recognized:false → facade 最终兜底到规则解析器
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "llm")

    class FakeLLM:
        def generate_json(self, *, system_prompt, user_prompt, temperature=0.2):
            return {"recognized": False, "order": None, "message": "LLM unsure"}

    monkeypatch.setattr(
        "app.services.parsers.llm.create_llm_client", lambda: FakeLLM()
    )

    result = parse_command("艾琳，撤退并优先保命")

    assert result.recognized is True
    assert result.order.intent == "retreat"
    assert result.source == "rule_fallback"