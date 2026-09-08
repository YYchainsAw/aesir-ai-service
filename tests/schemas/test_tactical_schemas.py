"""v0.2 Schema 层 golden 测试（草案 §3~§5）。

golden 取自《docs/protocols/combat-tactical-protocol-v0.2-draft.md》的示例 JSON：
正向用例验证结构可解析且字段语义正确；负向用例验证约束（百分比范围、
枚举白名单、必填字段）按草案 §3.1 收口。
"""

import json

import pytest
from pydantic import ValidationError

from app.schemas.combat_context import CombatContext
from app.schemas.tactical_decision import (
    DecisionAction,
    Expires,
    ResolveResponse,
    TacticalDecision,
)
from app.schemas.tactical_intent import TacticalIntent

# ---------------------------------------------------------------------------
# 草案 §3 快照 golden
# ---------------------------------------------------------------------------
GOLDEN_CONTEXT = {
    "encounter_id": "encounter.20260903.001",
    "snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd",
    "captured_at": "2026-09-03T12:00:00Z",
    "mode": "combat",
    "player": {
        "id": "party.player",
        "hp_percent": 18,
        "is_downed": False,
        "distance_to_boss_m": 4.5,
    },
    "companion": {
        "id": "companion.alice",
        "hp_percent": 83,
        "mp_percent": 72,
        "current_behavior": "ranged_attack",
        "ability_states": {
            "ability.alice.basic_attack": "ready",
            "ability.alice.explosion": "ready",
            "ability.alice.quick_heal": "ready",
            "ability.alice.major_heal": "ready",
            "ability.alice.shield": "ready",
        },
    },
    "boss": {
        "id": "encounter.primary_hostile",
        "hp_percent": 42,
        "stun_percent": 100,
        "state_tags": ["state.stunned"],
        "stunned_remaining_seconds": 4.5,
        "phase": 2,
        "is_enraged": False,
    },
}

# 草案 §5.1 请求 intent golden
GOLDEN_INTENT = {
    "intent_id": "support_heal_player",
    "target_id": "party.player",
    "timing": "immediate",
    "preferences": {"strength": "unspecified", "resource_conservation": "normal"},
    "normalized_text": "艾莉，治疗玩家",
    "parse_confidence": 0.92,
}

# 草案 §5.2 响应 decision golden（拆出单测 decision 结构）
GOLDEN_DECISION = {
    "decision_id": "32b8d0f4-5432-4374-a972-7c0da10c272e",
    "status": "actionable",
    "intent_id": "support_heal_player",
    "action": {
        "order_id": "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
        "agent_id": "companion.alice",
        "type": "cast_ability",
        "ability_id": "ability.alice.major_heal",
        "target_id": "party.player",
        "priority": 95,
        "expires": {"type": "immediate"},
        "authority": "player_requested",
    },
    "reason_codes": ["PLAYER_HP_CRITICAL", "BOSS_IN_MELEE_RANGE", "MAJOR_HEAL_READY"],
    "explanation": "玩家生命值危急，强效治疗当前可用。",
}


def test_golden_combat_context_parses() -> None:
    ctx = CombatContext.model_validate(GOLDEN_CONTEXT)
    assert ctx.player.hp_percent == 18
    assert ctx.companion.ability_states["ability.alice.explosion"] == "ready"
    assert ctx.boss.stunned_remaining_seconds == 4.5
    assert ctx.boss.state_tags == ["state.stunned"]


def test_golden_intent_parses() -> None:
    intent = TacticalIntent.model_validate(GOLDEN_INTENT)
    assert intent.intent_id == "support_heal_player"
    assert intent.parse_confidence == 0.92


def test_golden_decision_parses() -> None:
    decision = TacticalDecision.model_validate(GOLDEN_DECISION)
    assert decision.status == "actionable"
    assert decision.action is not None
    assert decision.action.ability_id == "ability.alice.major_heal"
    assert decision.action.priority == 95
    assert decision.reason_codes == [
        "PLAYER_HP_CRITICAL",
        "BOSS_IN_MELEE_RANGE",
        "MAJOR_HEAL_READY",
    ]


def test_golden_resolve_response_parses() -> None:
    """草案 §5.2 完整响应信封（含 companion_reply / observability）。"""
    body = {
        "protocol_version": "0.2",
        "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
        "recognized": True,
        "source": "rule",
        "decision": GOLDEN_DECISION,
        "companion_reply": {
            "reply_text": "别硬撑！这次我会彻底把你拉回来。",
            "emotion_id": "emotion.concerned",
            "gesture_id": "gesture.cast_support",
            "facial_expression_id": "face.concerned",
            "interruptible": False,
        },
        "observability": {
            "normalized_text": "艾莉，治疗玩家",
            "policy_revision": "support-policy-001",
            "used_snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd",
        },
    }
    resp = ResolveResponse.model_validate(body)
    assert resp.decision is not None and resp.decision.status == "actionable"
    assert resp.companion_reply["emotion_id"] == "emotion.concerned"
    assert resp.observability.used_snapshot_id == body["observability"]["used_snapshot_id"]


def test_decision_without_action_is_legal() -> None:
    """not_actionable / advisory / clarification 时 action 可为 null（不虚构动作）。"""
    decision = TacticalDecision.model_validate(
        {**GOLDEN_DECISION, "status": "not_actionable", "action": None}
    )
    assert decision.action is None


# ---------------------------------------------------------------------------
# 负向：约束收口（草案 §3.1）
# ---------------------------------------------------------------------------
def _mutate(path: tuple, value) -> dict:
    obj = json.loads(json.dumps(GOLDEN_CONTEXT))
    node = obj
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return obj


@pytest.mark.parametrize(
    "path,value",
    [
        (("player", "hp_percent"), 101),   # 超上限
        (("player", "hp_percent"), -1),    # 负值
        (("companion", "mp_percent"), 100.5),
        (("boss", "stun_percent"), -0.1),
        (("player", "distance_to_boss_m"), -1),
        (("companion", "ability_states", "ability.alice.explosion"), "unknown_state"),
        (("mode",), "exploration"),        # 本协议仅 combat
    ],
)
def test_combat_context_field_constraints(path, value) -> None:
    with pytest.raises(ValidationError):
        CombatContext.model_validate(_mutate(path, value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_id", "destroy_everything"),  # 不在 7 个白名单 intent 中
        ("parse_confidence", 1.5),            # 置信度超界
        ("timing", "someday"),
    ],
)
def test_intent_whitelist(field, value) -> None:
    bad = {**GOLDEN_INTENT, field: value}
    with pytest.raises(ValidationError):
        TacticalIntent.model_validate(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "maybe"),
        ("authority", "model_decided"),
        ("priority", 101),
        ("type", "nuke_everything"),
    ],
)
def test_decision_constraints(field, value) -> None:
    bad = json.loads(json.dumps(GOLDEN_DECISION))
    if field == "authority":
        bad["action"]["authority"] = value
    elif field == "priority":
        bad["action"]["priority"] = value
    elif field == "type":
        bad["action"]["type"] = value
    else:
        bad[field] = value
    with pytest.raises(ValidationError):
        TacticalDecision.model_validate(bad)


def test_protocol_version_must_be_02() -> None:
    with pytest.raises(ValidationError):
        ResolveResponse.model_validate(
            {
                "protocol_version": "0.1",  # v0.2 端点不接受 0.1
                "request_id": "x",
                "recognized": True,
                "source": "rule",
            }
        )


def test_expires_before_seconds_needs_value() -> None:
    """before_seconds 必须带 remaining_seconds（策略层约定，见草案 §6.2）。"""
    action = DecisionAction.model_validate(GOLDEN_DECISION["action"])
    assert action.expires.type == "immediate"
    with pytest.raises(ValidationError):
        Expires.model_validate({"type": "before_seconds", "remaining_seconds": -1})
