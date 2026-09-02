from app.services.command_parser import parse_command
from app.services.parsers.rule import RuleCommandParser


def test_rule_parser_recognizes_all_five_intents() -> None:
    parser = RuleCommandParser()
    cases = {
        "conditional_cast": "艾琳，等 Boss 眩晕时使用爆裂魔法",
        "hold_ability": "艾琳，保留爆裂魔法",
        "prioritize_attack": "艾琳，优先普通攻击",
        "follow_keep_distance": "艾琳，跟随我并保持距离",
        "retreat": "艾琳，撤退并优先保命",
    }
    for intent, text in cases.items():
        result = parser.parse(text)
        assert result.recognized is True
        assert result.order is not None
        assert result.order.intent == intent


def test_rule_parser_rejects_unknown_safely() -> None:
    result = RuleCommandParser().parse("艾琳，马上释放不存在的技能")
    assert result.recognized is False
    assert result.order is None


def test_facade_defaults_to_rule_backend() -> None:
    # No AESIR_PARSER_BACKEND set → rule backend.
    result = parse_command("艾琳，撤退并优先保命")
    assert result.recognized is True
    assert result.order.intent == "retreat"
    assert result.source == "rule"


def test_facade_falls_back_to_rule_when_llm_unimplemented(monkeypatch) -> None:
    # LLM 未配置时，facade 必须回退到规则解析器；测试不能读取开发者本机的 API 配置。
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "llm")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    result = parse_command("艾琳，撤退并优先保命")
    assert result.recognized is True
    assert result.order.intent == "retreat"
    assert result.source == "rule_fallback"

    unknown = parse_command("艾琳，马上释放不存在的技能")
    assert unknown.recognized is False
    assert unknown.order is None
