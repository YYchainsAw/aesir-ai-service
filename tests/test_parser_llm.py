import json

import httpx
import pytest

from app.schemas.tactical_order import ParseCommandResponse
from app.services.command_parser import parse_command
from app.services.parsers.llm import LLMCommandParser, LLMError


def _client_for(content: str) -> httpx.Client:
    """构造一个注入 MockTransport 的 client，返回给定的 model 输出 content。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_recognizes_valid_intent(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    order = {
        "recognized": True,
        "order": {
            "protocol_version": "1.0",
            "agent": "Eirin",
            "priority": "high",
            "expires_on": "EncounterEnd",
            "intent": "conditional_cast",
            "trigger": {"target": "Boss", "state": "Stunned"},
            "action": {"type": "CastAbility", "ability_id": "Explosion"},
        },
        "message": "cast when stunned",
    }
    parser = LLMCommandParser(client=_client_for(json.dumps(order)))

    result = parser.parse("等 Boss 眩晕了就放爆裂魔法")

    assert result.recognized is True
    assert result.order is not None
    assert result.order.intent == "conditional_cast"
    assert result.order.action.type == "CastAbility"


def test_recognized_false_output(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    parser = LLMCommandParser(
        client=_client_for(json.dumps({"recognized": False, "order": None, "message": "nope"}))
    )

    result = parser.parse("随便说点啥")

    assert result.recognized is False
    assert result.order is None


def test_invalid_json_raises_llm_error(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    parser = LLMCommandParser(client=_client_for("this is not json"))

    with pytest.raises(LLMError):
        parser.parse("不管")


def test_out_of_whitelist_field_raises_llm_error(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    bad = {
        "recognized": True,
        "order": {
            "intent": "conditional_cast",
            "trigger": {"target": "Boss", "state": "Stunned"},
            "action": {"type": "CastAbility", "ability_id": "NukeTheWorld"},  # 非白名单
        },
    }
    parser = LLMCommandParser(client=_client_for(json.dumps(bad)))

    with pytest.raises(LLMError):
        parser.parse("把世界核平了吧")


def test_missing_api_key_raises_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    parser = LLMCommandParser(client=_client_for("{}"))

    with pytest.raises(LLMError):
        parser.parse("随便")


def test_facade_falls_back_to_rule_without_key(monkeypatch) -> None:
    # 后端 llm 但未配 key → LLMNotConfiguredError → facade 回退规则
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "llm")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    result = parse_command("艾琳，撤退并优先保命")

    assert result.recognized is True
    assert result.order.intent == "retreat"


def test_facade_uses_rule_when_llm_unsure(monkeypatch) -> None:
    # LLM 明确 recognized:false → facade 让规则解析器最终兜底
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "llm")

    class FakeLLM:
        def parse(self, text: str) -> ParseCommandResponse:
            return ParseCommandResponse(
                recognized=False, order=None, message="LLM unsure"
            )

    monkeypatch.setattr("app.services.parsers.llm.LLMCommandParser", FakeLLM)

    result = parse_command("艾琳，撤退并优先保命")

    assert result.recognized is True
    assert result.order.intent == "retreat"