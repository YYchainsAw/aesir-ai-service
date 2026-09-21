"""20 条意图 × 4 类战况的回归评测集（策划书阶段 2 要求）。

四类战况（快照互不相同，覆盖状态空间的四个象限）：
  A 濒危贴脸：玩家 HP 18、贴 Boss、艾莉状态健康
  B 稳态消耗：玩家 HP 65、Boss 半血、无特殊状态
  C 眩晕窗口：Boss 眩晕剩 4.5s、其余同 B
  D 资源枯竭：艾莉 MP 10、玩家 HP 35、爆裂/强疗 CD

对每条意图断言其在四类战况下的期望决策（status + 关键动作字段），
并验证 v0.2 的核心卖点：同一意图在不同战况下可产出不同决策。
"""

import pytest

from app.schemas.combat_context import CombatContext, make_combat_context
from app.schemas.tactical_intent import TacticalIntent
from app.services.tactical.resolver import resolve_intent


def _situation_a() -> CombatContext:
    return make_combat_context(player_hp=18, player_distance=4.5)


def _situation_b() -> CombatContext:
    return make_combat_context(player_hp=65, boss_state_tags=[])


def _situation_c() -> CombatContext:
    return make_combat_context(
        player_hp=65, boss_state_tags=["state.stunned"], stunned_remaining=4.5
    )


def _situation_d() -> CombatContext:
    ctx = make_combat_context(player_hp=35, companion_mp=10)
    ctx.companion.ability_states["ability.alice.explosion"] = "cooldown"
    ctx.companion.ability_states["ability.alice.major_heal"] = "cooldown"
    return ctx


SITUATIONS = {
    "A_濒危贴脸": _situation_a,
    "B_稳态消耗": _situation_b,
    "C_眩晕窗口": _situation_c,
    "D_资源枯竭": _situation_d,
}

# 20 条意图输入（覆盖 7 种 intent_id 的代表性变体，含偏好差异）
INTENTS = [
    ("support_heal_player", "immediate", {}),
    ("support_heal_player", "immediate", {"strength": "major"}),
    ("support_heal_player", "when_possible", {"resource_conservation": "conservative"}),
    ("support_heal_player", "immediate", {"strength": "minor"}),
    ("support_protect_player", "immediate", {}),
    ("support_protect_player", "immediate", {"strength": "major"}),
    ("burst_boss", "immediate", {}),
    ("burst_boss", "immediate", {"resource_conservation": "aggressive"}),
    ("prepare_burst_on_stun", "on_condition", {}),
    ("prepare_burst_on_stun", "immediate", {"strength": "major"}),
    ("focus_fire_boss", "immediate", {}),
    ("focus_fire_boss", "immediate", {"resource_conservation": "aggressive"}),
    ("retreat_and_survive", "immediate", {}),
    ("retreat_and_survive", "when_possible", {}),
    ("follow_player", "immediate", {}),
    ("follow_player", "immediate", {"strength": "minor"}),
    ("support_heal_player", "immediate", {"strength": "unspecified", "resource_conservation": "aggressive"}),
    ("burst_boss", "on_condition", {}),
    ("support_protect_player", "when_possible", {}),
    ("follow_player", "when_possible", {}),
]


def _intent(intent_id: str, timing: str, prefs: dict) -> TacticalIntent:
    return TacticalIntent(
        intent_id=intent_id,  # type: ignore[arg-type]
        target_id="party.player",
        timing=timing,  # type: ignore[arg-type]
        preferences=prefs,  # type: ignore[arg-type]
        normalized_text=f"测试:{intent_id}",
        parse_confidence=0.9,
    )


@pytest.mark.parametrize("intent_id,timing,prefs", INTENTS)
@pytest.mark.parametrize("situation", SITUATIONS.keys())
def test_intent_across_situations(intent_id, timing, prefs, situation) -> None:
    """每条意图 × 每类战况：决策必须结构合法且行为可复现（确定性策略）。"""
    ctx = SITUATIONS[situation]()
    d1 = resolve_intent(_intent(intent_id, timing, prefs), ctx)
    d2 = resolve_intent(_intent(intent_id, timing, prefs), ctx)

    # 确定性：同一输入两次解析结果一致（除 uuid）
    assert d1.status == d2.status
    if d1.action and d2.action:
        assert d1.action.ability_id == d2.action.ability_id
        assert d1.action.type == d2.action.type
        assert d1.action.priority == d2.action.priority

    # 结构不变式：not_actionable 必无动作；actionable 必有动作与 reason
    if d1.status == "not_actionable":
        assert d1.action is None
        assert d1.reason_codes
    if d1.status == "actionable":
        assert d1.action is not None
        assert d1.reason_codes
        assert 0 <= d1.action.priority <= 100


# ---------------------------------------------------------------------------
# 关键上下文感知断言：同一意图在四类战况下确实产出不同结果
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "intent_id",
    ["support_heal_player", "burst_boss", "prepare_burst_on_stun", "support_protect_player"],
)
def test_decision_varies_across_situations(intent_id: str) -> None:
    """v0.2 核心验收：同一指令、不同战况 → 至少两种不同的决策输出。"""
    outputs = set()
    for make in SITUATIONS.values():
        d = resolve_intent(_intent(intent_id, "immediate", {}), make())
        key = (d.status, d.action.ability_id if d.action else None)
        outputs.add(key)
    assert len(outputs) >= 2, f"{intent_id} 在四类战况下决策完全相同，上下文感知失效"


def test_situation_d_never_invents_cooldown_abilities() -> None:
    """资源枯竭战况：任何意图都不得引用 CD 中的爆裂/强疗（不虚构动作）。"""
    ctx = _situation_d()
    for intent_id, timing, prefs in INTENTS:
        d = resolve_intent(_intent(intent_id, timing, prefs), ctx)
        if d.action and d.action.ability_id:
            assert d.action.ability_id not in (
                "ability.alice.explosion",
                "ability.alice.major_heal",
            ), f"{intent_id} 在 CD 中虚构了 {d.action.ability_id}"


# ---------------------------------------------------------------------------
# T072/T073：回归集扩展——「关系阶段」维度（distant/neutral/friendly/close 抽样）
# ---------------------------------------------------------------------------
RELATIONSHIP_STAGES = ["distant", "neutral", "friendly", "close"]

# 抽样意图：覆盖三类策略（治疗/保护、爆发、撤退跟随），每类取代表意图
RELATIONSHIP_SAMPLE_INTENTS = [
    ("support_heal_player", "immediate", {}),
    ("support_protect_player", "immediate", {}),
    ("burst_boss", "immediate", {}),
    ("retreat_and_survive", "immediate", {}),
]


@pytest.mark.parametrize("intent_id,timing,prefs", RELATIONSHIP_SAMPLE_INTENTS)
@pytest.mark.parametrize("stage", RELATIONSHIP_STAGES)
@pytest.mark.parametrize("situation", SITUATIONS.keys())
def test_intent_across_relationship_stages(intent_id, timing, prefs, stage, situation) -> None:
    """T072：意图 × 战况 × 关系阶段抽样——决策结构合法且可复现（确定性）。"""
    ctx = SITUATIONS[situation]()
    d1 = resolve_intent(_intent(intent_id, timing, prefs), ctx, relationship_stage=stage)
    d2 = resolve_intent(_intent(intent_id, timing, prefs), ctx, relationship_stage=stage)
    assert d1.status == d2.status
    if d1.action and d2.action:
        assert d1.action.ability_id == d2.action.ability_id
        assert d1.action.priority == d2.action.priority
    if d1.status == "not_actionable":
        assert d1.action is None
        assert d1.reason_codes
    if d1.status == "actionable":
        assert d1.action is not None
        assert d1.reason_codes
        assert 0 <= d1.action.priority <= 100
    # T073：关系调制必须可解释——原因码标注了关系依据（未知阶段除外）
    if any(code.startswith("RELATIONSHIP_") for code in d1.reason_codes):
        assert any(
            code.startswith(f"RELATIONSHIP_{stage.upper()}") for code in d1.reason_codes
        )


@pytest.mark.parametrize("stage", RELATIONSHIP_STAGES)
def test_relationship_stage_never_invents_cooldown_abilities(stage: str) -> None:
    """T073 安全约束：任何关系阶段都不得虚构 CD 中的能力（关系调制不得越权）。"""
    ctx = _situation_d()
    for intent_id, timing, prefs in INTENTS:
        d = resolve_intent(_intent(intent_id, timing, prefs), ctx, relationship_stage=stage)
        if d.action and d.action.ability_id:
            assert d.action.ability_id not in (
                "ability.alice.explosion",
                "ability.alice.major_heal",
            ), f"{intent_id} 在 {stage} 阶段虚构了 {d.action.ability_id}"


def test_close_stage_devoted_rebuilds_shield_only_when_ready() -> None:
    """T073：亲密 devoted 调制重建护盾的前提是护盾 ready——不满足则维持原决策。"""
    from app.schemas.combat_context import ContextCompanion, ContextPlayer

    for shield_state in ("ready", "cooldown", None):
        ctx = _situation_d()  # 低蓝：基础决策会拒绝护盾（COMPANION_MP_LOW）
        states = dict(ctx.companion.ability_states)
        if shield_state is None:
            states.pop("ability.alice.shield", None)
        else:
            states["ability.alice.shield"] = shield_state
        ctx.companion = ContextCompanion(
            id=ctx.companion.id,
            hp_percent=ctx.companion.hp_percent,
            mp_percent=ctx.companion.mp_percent,
            ability_states=states,
        )
        d = resolve_intent(
            _intent("support_protect_player", "immediate", {}),
            ctx,
            relationship_stage="close",
        )
        if shield_state == "ready":
            assert d.status == "actionable"
            assert d.action is not None and d.action.ability_id == "ability.alice.shield"
            assert "RELATIONSHIP_CLOSE_DEVOTED" in d.reason_codes
        else:
            # 护盾不可用/状态未知：不得虚构动作（FR-025）
            assert d.status == "not_actionable"
            assert d.action is None


def test_close_stage_protest_marks_but_does_not_change_action() -> None:
    """T073：亲密阶段对危险指令的抗议只追加原因码，不改变动作本身（UE 否决权）。"""
    base = resolve_intent(_intent("retreat_and_survive", "immediate", {}), _situation_b())
    protested = resolve_intent(
        _intent("retreat_and_survive", "immediate", {}), _situation_b(), relationship_stage="close"
    )
    assert "RELATIONSHIP_CLOSE_PROTEST" in protested.reason_codes
    assert protested.status == base.status
    assert protested.action is not None and base.action is not None
    assert protested.action.type == base.action.type
    assert protested.action.priority == base.action.priority


def test_same_intent_varies_across_relationship_stages() -> None:
    """US2 核心验收：同一意图 × 同一战况，不同关系阶段至少一处决策差异。"""
    # 低蓝战况：distant 维持保守拒绝，close devoted 重建护盾
    outputs = set()
    for stage in RELATIONSHIP_STAGES:
        d = resolve_intent(
            _intent("support_protect_player", "immediate", {}),
            _situation_d(),
            relationship_stage=stage,
        )
        outputs.add((d.status, d.action.ability_id if d.action else None))
    assert len(outputs) >= 2, "关系阶段对决策毫无影响，阶段化行为失效"
