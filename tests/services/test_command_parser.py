from app.services.parsers.command_parser import parse_command
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


def test_rule_parser_echoes_request_id() -> None:
    import uuid

    rid = uuid.uuid4()
    result = RuleCommandParser().parse("艾琳，撤退并优先保命", request_id=rid)
    assert result.request_id == rid


def test_facade_defaults_to_rule_backend(monkeypatch) -> None:
    # 明确强制 rule 后端，避免被开发者本机 .env 的 AESIR_PARSER_BACKEND=llm 干扰。
    monkeypatch.delenv("AESIR_PARSER_BACKEND", raising=False)
    result = parse_command("艾琳，撤退并优先保命")
    assert result.recognized is True
    assert result.order.intent == "retreat"
    assert result.source == "rule"
    # 已识别 order → facade 挂上由人设配置生成的队友确认回应
    assert result.companion_reply is not None
    assert result.companion_reply.reply_text


def test_facade_falls_back_to_rule_when_llm_unimplemented(monkeypatch) -> None:
    # 后端被设为 llm，但适配器调用失败；facade 必须回退到规则解析器，
    # 指令仍然能被解析出来，并标记来源为 rule_fallback。
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "llm")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    result = parse_command("艾琳，撤退并优先保命")
    assert result.recognized is True
    assert result.order.intent == "retreat"
    assert result.source == "rule_fallback"

    unknown = parse_command("艾琳，马上释放不存在的技能")
    assert unknown.recognized is False
    assert unknown.order is None
    assert unknown.companion_reply is None

def test_rule_parser_intent_conflict_resolved_by_priority() -> None:
    # 回归锁定（开发记录 2026-09-07 已知未修项）：撤退 priority 90 高于保留 60，
    # 「别放爆裂魔法，快撤退保命」同时命中 hold 与 retreat 关键词时应产出 retreat。
    result = RuleCommandParser().parse("艾琳，别放爆裂魔法，快撤退保命")
    assert result.recognized is True
    assert result.order is not None
    assert result.order.intent == "retreat"


def test_order_internal_models_reject_extra_fields() -> None:
    # 回归锁定（开发记录 2026-09-07 已知未修项）：order 内部模型 extra=forbid，
    # 调用方/LLM 传入未声明字段必须被拒绝而不是静默忽略。
    import pytest
    from pydantic import ValidationError

    from app.schemas.tactical_order import CastAbilityAction, WhenStateEntered

    with pytest.raises(ValidationError):
        WhenStateEntered(subject="encounter.primary_hostile", tag="state.stunned", bogus=1)
    with pytest.raises(ValidationError):
        CastAbilityAction(ability_id="ability.alice.explosion", target="party.player", bogus=1)
