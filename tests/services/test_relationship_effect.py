"""关系阶段化行为差异测试（SDD T034 / FR-016）。

同一意图在不同关系阶段下产出可区分的资源投入与服从度
（通过 reason_codes 与决策差异观察，独立验收标准）。
"""

from __future__ import annotations

from app.schemas.combat_context import make_combat_context
from app.schemas.tactical_intent import TacticalIntent
from app.services.relationship.effect import modulate_decision
from app.services.tactical.resolver import resolve_intent


def _intent(intent_id: str) -> TacticalIntent:
    return TacticalIntent(intent_id=intent_id, normalized_text="测试指令")


def test_same_intent_differs_across_stages() -> None:
    """独立验收：同一指令在 ≥3 个关系阶段下表现可区分。"""
    intent = _intent("support_protect_player")
    ctx = make_combat_context(player_hp=55, companion_mp=8)  # 蓝量过低 + 护盾就绪

    outputs = {}
    for stage in ("distant", "neutral", "close"):
        outputs[stage] = modulate_decision(resolve_intent(intent, ctx), stage, ctx)

    # distant（conservative）：低蓝下拒绝护盾并标记关系原因
    assert outputs["distant"].status == "not_actionable"
    assert "RELATIONSHIP_DISTANT_CONSERVATIVE" in outputs["distant"].reason_codes

    # neutral：与既有保守策略一致（蓝量原因，无关系标记）
    assert outputs["neutral"].status == "not_actionable"
    assert "RELATIONSHIP_DISTANT_CONSERVATIVE" not in outputs["neutral"].reason_codes

    # close（devoted）：低蓝也愿意投入护盾
    assert outputs["close"].status == "actionable"
    assert "RELATIONSHIP_CLOSE_DEVOTED" in outputs["close"].reason_codes

    # 三阶段两两可区分
    signatures = {stage: (d.status, tuple(sorted(d.reason_codes))) for stage, d in outputs.items()}
    assert len(set(signatures.values())) == 3


def test_close_stage_protests_dangerous_order() -> None:
    """obedience=low 的亲密阶段有权以角色口吻质疑危险指令（FR-016）。"""
    intent = _intent("retreat_and_survive")
    ctx = make_combat_context(player_hp=55, companion_mp=80)
    decision = modulate_decision(resolve_intent(intent, ctx), "close")
    assert decision.status == "actionable"
    assert "RELATIONSHIP_CLOSE_PROTEST" in decision.reason_codes


def test_unknown_stage_is_passthrough() -> None:
    """未知阶段不虚构行为：原决策原样通过（降级思路，原则 II/V）。"""
    intent = _intent("follow_player")
    ctx = make_combat_context(player_hp=55)
    decision = resolve_intent(intent, ctx)
    assert modulate_decision(decision, "not_a_stage") is decision
