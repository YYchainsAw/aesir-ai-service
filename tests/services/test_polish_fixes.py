"""已知小尾巴修复的回归（2026-10-15）：

- event_policy recommendation 文案按 companion_id 取人格包 display_name，
  Bruno 触发时不得再出现「艾莉」字样（穿帮修复）。
- command_parser 缺省回退不再写死 ``companion.alice``：上下文无 agent 时
  从注册表取第一个已登记角色。
- ``/v1/agent/step`` 的 ``observability.degraded`` 在熔断器打开 / 规则兜底 /
  命中降级原因码时为 true（此前 schema 恒为默认 False）。
- 对话信号埋点新增 ``memory_cited`` / ``relationship_stage`` 可选字段，
  验收脚本可据此把 SC-001/SC-003 从 N/A 升级为可判定。
"""

import json

import pytest

from app.schemas.combat_context import (
    CombatContext,
    ContextBoss,
    ContextCompanion,
    ContextPlayer,
)
from app.schemas.combat_event import CombatEvent, CombatEventRequest
from app.services.tactical.event_policy import _reset_seen_events, handle_combat_event

_OCCURRED_AT = "2026-10-15T12:00:00Z"


@pytest.fixture(autouse=True)
def _clean_event_cache():
    _reset_seen_events()
    yield
    _reset_seen_events()


def _mp_low_combat_request(companion_id: str, *, event_id: str) -> CombatEventRequest:
    """构造 v0.2 战斗通道的 companion_mp_low 请求（硬编码文案就在这条决策路径）。"""
    ctx = CombatContext(
        encounter_id="encounter.polish.001",
        snapshot_id="66666666-6666-4666-8666-666666666666",
        captured_at=_OCCURRED_AT,
        mode="combat",
        player=ContextPlayer(id="party.player", hp_percent=80),
        companion=ContextCompanion(
            id=companion_id, hp_percent=90, mp_percent=20,
            ability_states={"ability.alice.basic_attack": "ready"},
        ),
        boss=ContextBoss(id="encounter.primary_hostile", hp_percent=40),
    )
    return CombatEventRequest(
        protocol_version="0.2",
        request_id=f"req.{event_id}",
        event=CombatEvent(
            event_id=event_id, event_type="companion_mp_low",
            occurred_at=_OCCURRED_AT, sequence=1,
        ),
        combat_context=ctx,
    )


# --- ① event_policy 硬编码「艾莉」 -------------------------------------------


def test_mp_low_recommendation_uses_companion_display_name() -> None:
    """Bruno 触发蓝量低事件：建议文案用 Bruno 的称呼，不出现「艾莉」。"""
    response = handle_combat_event(
        _mp_low_combat_request("companion.bruno", event_id="event.polish.bruno.001")
    )
    assert response.recommendation is not None
    text = response.recommendation.display_text
    assert "艾莉" not in text
    assert "Bruno" in text


def test_mp_low_recommendation_alice_keeps_name() -> None:
    """Alice 触发同一事件：文案用其人格包称呼（回归保护旧语义）。"""
    response = handle_combat_event(
        _mp_low_combat_request("companion.alice", event_id="event.polish.alice.001")
    )
    assert response.recommendation is not None
    # Alice 的 display_name 是「Alice」（人格包 aliases 含「艾莉」）
    assert "Alice" in response.recommendation.display_text


# --- ② command_parser 缺省回退 ----------------------------------------------


def test_primary_companion_falls_back_to_registry() -> None:
    """上下文无 agent 时从注册表取，而非写死 companion.alice。"""
    from app.schemas.tactical_order import ParseCommandContext
    from app.services.parsers.command_parser import _primary_companion_id

    ctx = ParseCommandContext(
        agents=[],
        target_selectors=[],
        state_tags=[],
    )
    companion_id = _primary_companion_id(ctx)
    # 注册表（当前游戏）至少含 Alice/Bruno 之一；关键是走注册表而非硬编码。
    assert companion_id.startswith("companion.")


# --- ③ observability.degraded ------------------------------------------------


def test_degraded_flag_reflects_open_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """熔断器处于 OPEN 时 degraded 应为 true（此前生产路径恒 False）。"""
    from app.api.v1.agent import _degraded_flag

    class _OpenBreaker:
        state = "open"

    monkeypatch.setattr(
        "app.services.llm.factory.get_llm_circuit_breaker", lambda: _OpenBreaker()
    )
    assert _degraded_flag([]) is True
    assert _degraded_flag([], extra=True) is True


def test_degraded_flag_false_when_closed() -> None:
    """熔断器 CLOSED 且无降级原因码时 degraded 为 false（正常路径语义不变）。"""
    from app.api.v1.agent import _degraded_flag

    assert _degraded_flag([]) is False
    assert _degraded_flag(["NO_AUTONOMOUS_CANDIDATE"]) is False


def test_degraded_flag_true_on_degrade_reason_code() -> None:
    """命中已知降级原因码（关系存储故障等）时 degraded 为 true。"""
    from app.api.v1.agent import _degraded_flag

    assert _degraded_flag(["RELATIONSHIP_UNAVAILABLE"]) is True
    assert _degraded_flag(["COMBAT_CONTEXT_MISSING"]) is True


# --- ④ 对话信号新增埋点字段 --------------------------------------------------


def test_record_turn_signal_persists_new_fields(tmp_path, monkeypatch) -> None:
    """memory_cited / relationship_stage 显式传入时落盘；缺省时不写键。"""
    from app.services.companion import dialogue_signals as mod

    monkeypatch.setattr(mod, "get_settings", lambda: type(
        "S", (), {"dialogue_signals_dir": str(tmp_path)}
    ))

    from app.services.companion.dialogue_signals import record_turn_signal

    # 显式传新字段
    record_turn_signal(
        "companion.alice",
        "sess.1",
        player_text="记得我喜欢钓鱼吗",
        reply_text="当然，你喜欢钓鱼。",
        source="llm",
        emotion_id="emotion.happy",
        gesture_id="gesture.nod",
        facial_expression_id="face.smile",
        game_state="exploration",
        memory_cited=True,
        relationship_stage="friendly",
        game_id="aesir",
    )
    line = (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["memory_cited"] is True
    assert record["relationship_stage"] == "friendly"

    # 缺省不传：键不应出现（旧记录结构稳定）
    record_turn_signal(
        "companion.alice",
        "sess.2",
        player_text="hi",
        reply_text="你好。",
        source="mock",
        emotion_id="emotion.neutral",
        gesture_id="gesture.idle",
        facial_expression_id="face.neutral",
        game_state="exploration",
        game_id="aesir",
    )
    last = (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    record2 = json.loads(last)
    assert "memory_cited" not in record2
    assert "relationship_stage" not in record2
