"""BossSim 内核测试（纯 Python，无 RL 三方依赖，永远执行）。

验证：同 seed 逐 tick 可复现、眩晕积累/触发/清零、眩晕窗口伤害倍率、
相位与狂暴、非法施法、三种终局、规则基线适配器动作合法且可跑完整局。
"""

import pytest

from rl.sim.constants import (
    ACTION_BASIC_ATTACK,
    ACTION_EXPLOSION,
    ACTION_NOOP,
    ACTION_QUICK_HEAL,
    ACTION_RETREAT,
    ACTION_SHIELD,
    N_ACTIONS,
    SimConstants,
    STUN_DURATION_S,
)
from rl.sim.core import BossSim, SimState
from rl.policy.rule import RulePolicyAdapter


def _run_scripted(sim: BossSim, actions: list[int]) -> list[tuple[SimState, str | None]]:
    out = []
    for a in actions:
        st, _, done = sim.step(a)
        out.append((st, done))
        if done:
            break
    return out


def test_same_seed_tick_by_tick_reproducible() -> None:
    """同 seed 两局、固定动作序列 → 逐 tick 状态完全一致（规则基线可比的前提）。"""
    actions = [ACTION_BASIC_ATTACK] * 50
    s1 = _run_scripted(BossSim(seed=42), actions)
    s2 = _run_scripted(BossSim(seed=42), actions)
    assert len(s1) == len(s2)
    for (st1, d1), (st2, d2) in zip(s1, s2):
        assert st1 == st2
        assert d1 == d2


def test_different_seed_diverges() -> None:
    a = _run_scripted(BossSim(seed=1), [ACTION_NOOP] * 80)
    b = _run_scripted(BossSim(seed=2), [ACTION_NOOP] * 80)
    # AOE 是概率事件，不同 seed 的同伴血量轨迹几乎必然分叉
    assert any(s1.companion_hp != s2.companion_hp for (s1, _), (s2, _) in zip(a, b))


def test_stun_accumulates_and_triggers() -> None:
    sim = BossSim(seed=7)
    triggered = None
    for i in range(40):
        st, _, _ = sim.step(ACTION_BASIC_ATTACK)
        if st.boss_stunned:
            triggered = i
            break
    assert triggered is not None, "40 tick 内应触发眩晕"
    assert "state.stunned" in st.to_context().boss.state_tags
    assert st.boss_stunned_remaining > 0
    # 眩晕结束后清零重新积累：结束后的下一 tick，玩家普攻从 0 重新积 3 点
    from rl.sim.constants import PLAYER_AUTO_STUN
    while st.boss_stunned:
        st, _, _ = sim.step(ACTION_NOOP)
    assert st.boss_stunned_remaining == 0.0
    assert st.boss_stun == pytest.approx(PLAYER_AUTO_STUN)


def test_explosion_in_stun_window_deals_bonus_damage() -> None:
    sim = BossSim(seed=3)
    hp_before = None
    # 先打到眩晕
    for _ in range(40):
        st, _, _ = sim.step(ACTION_BASIC_ATTACK)
        if st.boss_stunned:
            break
    assert st.boss_stunned
    hp_before = st.boss_hp
    _, events, _ = sim.step(ACTION_EXPLOSION)
    assert events.boss_stunned_at_action
    # 爆裂 15×2.5 + 玩家普攻 2×2.5（眩晕窗口内玩家自动输出同样享受倍率）
    assert events.damage_to_boss == pytest.approx(15.0 * 2.5 + 2.0 * 2.5)
    assert st.boss_hp == pytest.approx(max(0.0, hp_before - events.damage_to_boss))


def test_invalid_cast_on_cooldown_or_low_mp() -> None:
    sim = BossSim(seed=0)
    sim.state.companion_mp = 10.0  # 强行低蓝
    _, events, _ = sim.step(ACTION_EXPLOSION)
    assert events.invalid_cast
    # CD：连续两次快速治疗，第二次应失败
    sim2 = BossSim(seed=0)
    sim2.state.companion_mp = 100.0
    _, e1, _ = sim2.step(ACTION_QUICK_HEAL)
    _, e2, _ = sim2.step(ACTION_QUICK_HEAL)
    assert not e1.invalid_cast and e2.invalid_cast


def test_shield_and_retreat_reduce_damage() -> None:
    base = BossSim(seed=11)
    st0 = base.state
    _, plain, _ = base.step(ACTION_NOOP)
    dmg_plain = plain.damage_to_player

    shielded = BossSim(seed=11)
    _, ev, _ = shielded.step(ACTION_SHIELD)
    assert ev.shield_applied
    assert ev.damage_to_player == pytest.approx(dmg_plain * 0.2)

    retreat = BossSim(seed=11)
    _, ev, _ = retreat.step(ACTION_RETREAT)
    assert ev.retreat_applied
    assert ev.damage_to_player == pytest.approx(dmg_plain * 0.5)


def test_boss_phase_and_enrage() -> None:
    # 高伤爆裂 + 短 CD 快速压血线触发 phase2/3
    from rl.sim.constants import ABILITY_SPECS, ABIL_EXPLOSION, AbilitySpec
    c = SimConstants(
        explosion_boss_damage=25.0,
        specs={
            ABIL_EXPLOSION: AbilitySpec(
                ability_id=ABIL_EXPLOSION, mp_cost=0.0, cooldown_s=1.0, action=ACTION_EXPLOSION
            )
        },
    )
    sim = BossSim(seed=0, constants=c)
    seen_phase2 = seen_phase3 = False
    for _ in range(20):
        st, _, done = sim.step(ACTION_EXPLOSION)
        seen_phase2 |= st.boss_phase == 2
        seen_phase3 |= st.boss_phase == 3 and st.boss_enraged
        if done:
            break
    assert seen_phase2 and seen_phase3


def test_terminal_boss_dead_and_player_downed() -> None:
    # Boss 速死
    c = SimConstants(boss_max_hp=20.0)
    sim = BossSim(seed=0, constants=c)
    sim.state.boss_hp = 5.0
    st, _, done = sim.step(ACTION_EXPLOSION)
    assert done == "boss_dead" and st.boss_hp == 0.0

    # 玩家速倒
    c = SimConstants(boss_base_damage=200.0)
    sim = BossSim(seed=0, constants=c)
    _, _, done = sim.step(ACTION_NOOP)
    assert done == "player_downed"

    # tick 上限
    c = SimConstants(max_ticks=5, boss_base_damage=0.0)
    sim = BossSim(seed=0, constants=c)
    for _ in range(5):
        st, _, done = sim.step(ACTION_NOOP)
    assert done == "timeout"


def test_step_after_done_raises() -> None:
    c = SimConstants(boss_base_damage=200.0)
    sim = BossSim(seed=0, constants=c)
    sim.step(ACTION_NOOP)
    with pytest.raises(RuntimeError):
        sim.step(ACTION_NOOP)


def test_rule_policy_full_episode_valid_actions() -> None:
    """规则基线跑完整局：动作始终合法、必达终局、context 导出合法。"""
    sim = BossSim(seed=99)
    policy = RulePolicyAdapter()
    steps = 0
    while True:
        state = sim.state
        ctx = state.to_context()  # 期间持续导出也不应抛错
        assert ctx.mode == "combat"
        action = policy.select_action(None, state)
        assert 0 <= action < N_ACTIONS
        _, _, done = sim.step(action)
        steps += 1
        if done or steps > 400:
            break
    assert done, "规则基线应在 max_ticks 内达成终局"
    assert steps <= 300 + 1
