"""BossSim：纯 Python 的单 Boss 单遭遇模拟器内核（无三方依赖）。

复刻总策划书的核心战术循环：玩家普攻积累 Boss 眩晕值 → 眩晕 6s 窗口
（受伤害 ×2.5）→ 爆裂魔法等窗口爆发。``prepare_burst_on_stun`` 的线上
语义由此产生。

确定性：所有随机项走 ``random.Random(seed)``，同 seed 逐 tick 可复现
（规则基线分数可比的前提）。

动作（Discrete(7)）：0 noop / 1 basic_attack / 2 explosion /
3 quick_heal / 4 major_heal / 5 shield / 6 retreat。
follow 在单 Boss 单遭遇 sim 中无意义，故省略。
"""

from dataclasses import dataclass, field
import random

from app.schemas.combat_context import CombatContext, ContextBoss, ContextCompanion, ContextPlayer
from app.services.ids import AGENT, SELECTOR_PLAYER as PLAYER_ID, SELECTOR_PRIMARY_HOSTILE as BOSS_ID

from rl.sim.constants import (
    ABILITY_ACTIONS,
    ACTION_BASIC_ATTACK,
    ACTION_EXPLOSION,
    ACTION_MAJOR_HEAL,
    ACTION_NOOP,
    ACTION_QUICK_HEAL,
    ACTION_RETREAT,
    ACTION_SHIELD,
    AOE_DAMAGE_MIN,
    AOE_DAMAGE_SPAN,
    BOSS_PHASE2_HP,
    BOSS_PHASE2_MULT,
    BOSS_PHASE3_HP,
    BOSS_PHASE3_MULT,
    COMPANION_MAX_HP,
    COMPANION_MAX_MP,
    EXPLOSION_STUN,
    HEAL_WASTE_THRESHOLD,
    PLAYER_AUTO_DPS,
    PLAYER_AUTO_STUN,
    PLAYER_MAX_HP,
    RETREAT_DAMAGE_MULT,
    RETREAT_TICKS,
    SHIELD_DAMAGE_MULT,
    SHIELD_TICKS,
    SimConstants,
    STUNNED_TAKEN_MULT,
    STUN_DURATION_S,
    STUN_METER_MAX,
    COMPANION_ATTACK_STUN,
    DEFAULT_CONSTANTS,
)


@dataclass
class SimState:
    """模拟器内部状态；``to_context()`` 输出与服务端同一形状的快照。"""

    tick: int = 0
    player_hp: float = PLAYER_MAX_HP
    companion_hp: float = COMPANION_MAX_HP
    companion_mp: float = COMPANION_MAX_MP
    boss_hp: float = 100.0
    boss_stun: float = 0.0
    boss_stunned_remaining: float = 0.0
    boss_phase: int = 1
    boss_enraged: bool = False
    cooldowns: dict[str, float] = field(default_factory=dict)
    shield_active_ticks: int = 0
    retreat_active_ticks: int = 0

    @property
    def player_downed(self) -> bool:
        return self.player_hp <= 0

    @property
    def companion_downed(self) -> bool:
        return self.companion_hp <= 0

    @property
    def boss_stunned(self) -> bool:
        return self.boss_stunned_remaining > 0

    def to_context(self, constants: "SimConstants | None" = None) -> CombatContext:
        """导出为服务端同构快照（resolver / features 都吃这个形状）。

        HP/MP 字段为百分比口径（0-100），按 ``constants`` 的上限归一化；
        不传时用默认常量（自定义 ``SimConstants`` 变体请经 ``BossSim.to_context()``）。
        """
        c = constants or DEFAULT_CONSTANTS
        ability_states: dict[str, str] = {}
        for ability_id in ABILITY_ACTIONS:
            if self.cooldowns.get(ability_id, 0.0) > 0:
                ability_states[ability_id] = "cooldown"
            else:
                ability_states[ability_id] = "ready"
        tags = []
        if self.boss_stunned:
            tags.append("state.stunned")
        return CombatContext(
            encounter_id="sim.bossfight",
            snapshot_id=f"sim-tick-{self.tick}",
            captured_at=f"sim-t{self.tick}",
            mode="combat",
            player=ContextPlayer(
                id=PLAYER_ID,
                hp_percent=max(0.0, self.player_hp) / c.player_max_hp * 100.0,
                is_downed=self.player_downed,
                distance_to_boss_m=8.0,
            ),
            companion=ContextCompanion(
                id=AGENT,
                hp_percent=max(0.0, self.companion_hp) / c.companion_max_hp * 100.0,
                mp_percent=self.companion_mp / c.companion_max_mp * 100.0,
                current_behavior="ranged_attack",
                ability_states=ability_states,
            ),
            boss=ContextBoss(
                id=BOSS_ID,
                hp_percent=max(0.0, self.boss_hp) / c.boss_max_hp * 100.0,
                stun_percent=STUN_METER_MAX if self.boss_stunned else min(STUN_METER_MAX, self.boss_stun),
                state_tags=tags,
                stunned_remaining_seconds=self.boss_stunned_remaining or None,
                phase=self.boss_phase,
                is_enraged=self.boss_enraged,
            ),
        )


@dataclass
class SimStepResult:
    """单 tick 明细，供 rewards.py 计分与 eval 指标统计。"""

    action: int
    damage_to_boss: float = 0.0
    companion_damage_to_boss: float = 0.0   # 同伴主动技能造成的部分（奖励计权只看它）
    damage_to_player: float = 0.0
    damage_to_companion: float = 0.0
    healed_player: float = 0.0
    boss_stunned_at_action: bool = False
    invalid_cast: bool = False       # 蓝不足 / CD 中
    wasted_heal: bool = False        # 玩家 hp > 阈值时施放治疗
    shield_applied: bool = False
    retreat_applied: bool = False


@dataclass
class SimEnvState:
    """一局的环境侧状态（state + rng + 终局原因）。"""

    state: SimState
    rng: random.Random
    done_reason: str | None = None


class BossSim:
    """确定性 Boss 战模拟器。``step`` 返回 (新状态, tick 明细, 终局原因)。"""

    def __init__(self, seed: int = 0, constants: SimConstants | None = None):
        self.constants = constants or DEFAULT_CONSTANTS
        self._seed = seed
        self._env = self._fresh(seed)

    def _fresh(self, seed: int) -> SimEnvState:
        return SimEnvState(state=SimState(), rng=random.Random(seed))

    # -- 生命周期 -----------------------------------------------------------
    def reset(self, seed: int | None = None) -> SimState:
        """重开一局；同 seed 逐 tick 可复现。"""
        self._seed = seed if seed is not None else self._seed
        self._env = self._fresh(self._seed)
        return self._env.state

    @property
    def state(self) -> SimState:
        return self._env.state

    @property
    def done_reason(self) -> str | None:
        return self._env.done_reason

    def to_context(self) -> CombatContext:
        """按本局常量归一化导出快照（自定义 HP 上限的变体必须走这里）。"""
        return self._env.state.to_context(self.constants)

    # -- 主循环 -------------------------------------------------------------
    def step(self, action: int) -> tuple[SimState, SimStepResult, str | None]:
        env = self._env
        if env.done_reason is not None:
            raise RuntimeError("episode already done; call reset() first")
        st, rng, c = env.state, env.rng, self.constants
        events = SimStepResult(action=action)

        # 1) 冷却递减与回蓝
        for ability_id in list(st.cooldowns):
            st.cooldowns[ability_id] = max(0.0, st.cooldowns[ability_id] - c.tick_seconds)
        st.companion_mp = min(c.companion_max_mp, st.companion_mp + c.mp_regen)

        # 2) 同伴动作
        self._apply_action(action, events)

        # 3) Boss 行为（眩晕中不攻击）
        if st.boss_stunned:
            st.boss_stunned_remaining = max(0.0, st.boss_stunned_remaining - c.tick_seconds)
            if not st.boss_stunned:
                st.boss_stun = 0.0  # 眩晕结束清零，重新积累
        else:
            dmg = c.boss_base_damage * self._phase_mult(st)
            if st.shield_active_ticks > 0:
                dmg *= SHIELD_DAMAGE_MULT
            if st.retreat_active_ticks > 0:
                dmg *= RETREAT_DAMAGE_MULT
            st.player_hp -= dmg
            events.damage_to_player = dmg
            if rng.random() < self.constants.aoe_chance:
                aoe = AOE_DAMAGE_MIN + rng.random() * AOE_DAMAGE_SPAN
                st.companion_hp -= aoe
                events.damage_to_companion = aoe

        # 4) 玩家自动输出（撤退时不输出、不积累眩晕；眩晕窗口伤害 ×2.5）
        if st.retreat_active_ticks <= 0 and st.player_hp > 0:
            taken = PLAYER_AUTO_DPS * (STUNNED_TAKEN_MULT if st.boss_stunned else 1.0)
            self._damage_boss(taken)
            events.damage_to_boss += taken
            if not st.boss_stunned:
                st.boss_stun = min(STUN_METER_MAX, st.boss_stun + PLAYER_AUTO_STUN)

        # 5) 护盾 / 撤退倒计时
        if st.shield_active_ticks > 0:
            st.shield_active_ticks -= 1
        if st.retreat_active_ticks > 0:
            st.retreat_active_ticks -= 1

        # 6) 相位与狂暴
        if st.boss_hp <= BOSS_PHASE3_HP:
            st.boss_phase, st.boss_enraged = 3, True
        elif st.boss_hp <= BOSS_PHASE2_HP:
            st.boss_phase = 2

        st.tick += 1
        env.done_reason = self._terminal(st)
        return st, events, env.done_reason

    # -- 内部 ---------------------------------------------------------------
    def _apply_action(self, action: int, events: SimStepResult) -> None:
        st, c = self._env.state, self.constants
        spec_by_action = c.specs_by_action

        if action == ACTION_RETREAT:
            st.retreat_active_ticks = RETREAT_TICKS
            events.retreat_applied = True
            return
        if action == ACTION_SHIELD:
            spec = spec_by_action.get(ACTION_SHIELD)
            if spec is None or not self._consume(spec, events):
                return
            st.shield_active_ticks = SHIELD_TICKS
            events.shield_applied = True
            return
        if action in (ACTION_NOOP,):
            return

        spec = spec_by_action.get(action)
        if spec is None or not self._consume(spec, events):
            return

        if action == ACTION_BASIC_ATTACK:
            dmg = c.basic_attack_boss_damage * (STUNNED_TAKEN_MULT if st.boss_stunned else 1.0)
            self._damage_boss(dmg)
            events.damage_to_boss += dmg
            events.companion_damage_to_boss += dmg
            events.boss_stunned_at_action = st.boss_stunned
            if not st.boss_stunned:
                st.boss_stun = min(STUN_METER_MAX, st.boss_stun + COMPANION_ATTACK_STUN)
        elif action == ACTION_EXPLOSION:
            events.boss_stunned_at_action = st.boss_stunned
            dmg = c.explosion_boss_damage * (STUNNED_TAKEN_MULT if st.boss_stunned else 1.0)
            self._damage_boss(dmg)
            events.damage_to_boss += dmg
            events.companion_damage_to_boss += dmg
            if not st.boss_stunned:
                st.boss_stun = min(STUN_METER_MAX, st.boss_stun + EXPLOSION_STUN)
        elif action == ACTION_QUICK_HEAL:
            events.wasted_heal = st.player_hp > HEAL_WASTE_THRESHOLD
            st.player_hp = min(PLAYER_MAX_HP, st.player_hp + c.quick_heal_amount)
            events.healed_player = c.quick_heal_amount
        elif action == ACTION_MAJOR_HEAL:
            events.wasted_heal = st.player_hp > HEAL_WASTE_THRESHOLD
            st.player_hp = min(PLAYER_MAX_HP, st.player_hp + c.major_heal_amount)
            events.healed_player = c.major_heal_amount

    def _consume(self, spec, events: SimStepResult) -> bool:
        """扣蓝与进 CD；不可施放（蓝不足/CD 中）记 invalid_cast 并返回 False。"""
        st, c = self._env.state, self.constants
        if st.cooldowns.get(spec.ability_id, 0.0) > 0 or st.companion_mp < spec.mp_cost:
            events.invalid_cast = True
            return False
        st.companion_mp -= spec.mp_cost
        st.cooldowns[spec.ability_id] = spec.cooldown_s
        return True

    def _damage_boss(self, amount: float) -> None:
        st = self._env.state
        st.boss_hp = max(0.0, st.boss_hp - amount)
        if st.boss_hp <= 0:
            return
        # 眩晕值 ≥100 → 进入眩晕（被眩晕期间不再积累）
        if not st.boss_stunned and st.boss_stun >= STUN_METER_MAX:
            st.boss_stunned_remaining = STUN_DURATION_S

    def _phase_mult(self, st: SimState) -> float:
        if st.boss_hp <= BOSS_PHASE3_HP:
            return BOSS_PHASE3_MULT
        if st.boss_hp <= BOSS_PHASE2_HP:
            return BOSS_PHASE2_MULT
        return 1.0

    def _terminal(self, st: SimState) -> str | None:
        c = self.constants
        if st.boss_hp <= 0:
            return "boss_dead"
        if st.player_downed:
            return "player_downed"
        if st.companion_downed:
            return "companion_downed"
        if st.tick >= c.max_ticks:
            return "timeout"
        return None
