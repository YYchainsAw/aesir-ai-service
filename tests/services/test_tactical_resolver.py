"""`/v1/tactical/resolve` 规则策略测试。

四类战况（治疗/保护、爆发、撤退跟随、资源受限）× 语义意图，验证：
- 同一意图在不同快照下产出不同决策（上下文感知是 v0.2 的核心卖点）；
- 能力不可用/蓝量低时绝不虚构动作（not_actionable + reason_codes）。
"""

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.combat_context import make_combat_context

client = TestClient(app)
RID = "88d7e6b4-f4f2-4d39-8c96-a23d293882f6"


def _intent(intent_id: str, **kw) -> dict:
    return {
        "intent_id": intent_id,
        "target_id": kw.pop("target_id", "party.player"),
        "timing": "immediate",
        "preferences": {"strength": "unspecified", "resource_conservation": "normal"},
        "normalized_text": kw.pop("normalized_text", ""),
        "parse_confidence": 0.92,
    }


def _resolve(intent: dict, ctx) -> dict:
    resp = client.post(
        "/v1/tactical/resolve",
        json={
            "protocol_version": "0.2",
            "request_id": RID,
            "intent": intent,
            "combat_context": ctx.model_dump(),
        },
    )
    assert resp.status_code == 200
    return resp.json()


def test_heal_critical_uses_major_heal() -> None:
    """玩家濒危（HP18、贴脸）→ 强效治疗，reason 带危急与贴脸。"""
    ctx = make_combat_context(player_hp=18, player_distance=4.5)
    body = _resolve(_intent("support_heal_player"), ctx)
    d = body["decision"]
    assert d["status"] == "actionable"
    assert d["action"]["ability_id"] == "ability.alice.major_heal"
    assert d["action"]["priority"] == 95
    assert d["action"]["expires"]["type"] == "immediate"
    assert "PLAYER_HP_CRITICAL" in d["reason_codes"]
    assert "BOSS_IN_MELEE_RANGE" in d["reason_codes"]
    assert body["observability"]["used_snapshot_id"] == ctx.snapshot_id


def test_same_intent_low_hp_uses_quick_heal() -> None:
    """同一治疗意图，HP 65（非濒危）→ 快速治疗而非强效（上下文感知差异之二）。"""
    ctx = make_combat_context(player_hp=65)
    d = _resolve(_intent("support_heal_player"), ctx)["decision"]
    assert d["action"]["ability_id"] == "ability.alice.quick_heal"
    assert d["action"]["priority"] == 85


def test_same_intent_healthy_player_not_actionable() -> None:
    """同一治疗意图，HP 90 → 不治疗（差异之三：相同指令不同结果）。"""
    ctx = make_combat_context(player_hp=90)
    d = _resolve(_intent("support_heal_player"), ctx)["decision"]
    assert d["status"] == "not_actionable"
    assert d["action"] is None
    assert d["reason_codes"] == ["PLAYER_HP_HEALTHY"]


def test_heal_unavailable_when_on_cooldown() -> None:
    """治疗技能 CD → not_actionable，不虚构动作。"""
    ctx = make_combat_context(player_hp=18)
    ctx.companion.ability_states["ability.alice.major_heal"] = "cooldown"
    ctx.companion.ability_states["ability.alice.quick_heal"] = "cooldown"
    d = _resolve(_intent("support_heal_player"), ctx)["decision"]
    assert d["status"] == "not_actionable"
    assert "HEAL_NOT_READY" in d["reason_codes"]


def test_protect_with_low_mp_is_conservative() -> None:
    """护盾就绪但艾莉蓝量 <20 → 保守拒绝。"""
    ctx = make_combat_context(player_hp=18, companion_mp=15)
    d = _resolve(_intent("support_protect_player"), ctx)["decision"]
    assert d["status"] == "not_actionable"
    assert "COMPANION_MP_LOW" in d["reason_codes"]


def test_burst_immediate_when_ready() -> None:
    ctx = make_combat_context(player_hp=80)
    d = _resolve(_intent("burst_boss"), ctx)["decision"]
    assert d["status"] == "actionable"
    assert d["action"]["ability_id"] == "ability.alice.explosion"
    assert d["action"]["target_id"] == "encounter.primary_hostile"


def test_burst_low_mp_is_conservative() -> None:
    ctx = make_combat_context(player_hp=80, companion_mp=10)
    d = _resolve(_intent("burst_boss"), ctx)["decision"]
    assert d["status"] == "not_actionable"
    assert d["reason_codes"] == ["COMPANION_MP_LOW", "EXPLOSION_READY"]


def test_prepare_burst_waits_for_stun() -> None:
    """等眩晕爆发：Boss 未眩晕 → 登记到 encounter_end（UE 等触发）。"""
    ctx = make_combat_context(player_hp=80, boss_state_tags=[])
    d = _resolve(_intent("prepare_burst_on_stun"), ctx)["decision"]
    assert d["status"] == "actionable"
    assert d["action"]["expires"]["type"] == "encounter_end"
    assert "BOSS_NOT_STUNNED_YET" in d["reason_codes"]


def test_prepare_burst_fires_now_when_stunned() -> None:
    """等眩晕爆发：Boss 已眩晕 → 立即施放（同一指令、状态不同、动作不同）。"""
    ctx = make_combat_context(
        player_hp=80, boss_state_tags=["state.stunned"], stunned_remaining=4.5
    )
    d = _resolve(_intent("prepare_burst_on_stun"), ctx)["decision"]
    assert d["action"]["expires"]["type"] == "immediate"


def test_retreat_and_follow_always_actionable() -> None:
    ctx = make_combat_context(player_hp=50)
    d = _resolve(_intent("retreat_and_survive"), ctx)["decision"]
    assert d["action"]["type"] == "retreat" and d["action"]["priority"] == 90
    d = _resolve(_intent("follow_player"), ctx)["decision"]
    assert d["action"]["type"] == "follow" and d["action"]["target_id"] == "party.player"


def test_response_envelope_fields() -> None:
    ctx = make_combat_context(player_hp=18)
    body = _resolve(_intent("support_heal_player", normalized_text="艾莉，治疗玩家"), ctx)
    assert body["protocol_version"] == "0.2"
    assert body["request_id"] == RID
    assert body["source"] == "rule"
    assert body["companion_reply"]["reply_text"]
    assert body["observability"]["policy_revision"] == "support-policy-001"


def test_invalid_intent_id_returns_422() -> None:
    ctx = make_combat_context(player_hp=50)
    resp = client.post(
        "/v1/tactical/resolve",
        json={
            "protocol_version": "0.2",
            "request_id": RID,
            "intent": _intent("destroy_everything"),
            "combat_context": ctx.model_dump(),
        },
    )
    assert resp.status_code == 422


def test_wrong_protocol_version_returns_422() -> None:
    ctx = make_combat_context(player_hp=50)
    resp = client.post(
        "/v1/tactical/resolve",
        json={
            "protocol_version": "0.1",  # v0.2 端点拒收
            "request_id": RID,
            "intent": _intent("retreat_and_survive"),
            "combat_context": ctx.model_dump(),
        },
    )
    assert resp.status_code == 422
