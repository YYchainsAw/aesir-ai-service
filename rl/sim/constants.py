"""Boss 战模拟器全部数值常量（一处集中，便于扫描与文档对照）。

治疗阈值直接引用生产 resolver 的常量，保证规则基线在 sim 里与线上
行为同源（A/B 公平性）。所有数值均为粗略近似，仅供策略间相对比较。
"""

from dataclasses import dataclass, field

from app.services.tactical.resolver import (
    ABIL_EXPLOSION,
    ABIL_MAJOR_HEAL,
    ABIL_QUICK_HEAL,
    ABIL_SHIELD,
    PLAYER_HP_CRITICAL,
    PLAYER_HP_LOW,
)

# ---------------------------------------------------------------------------
# 动作表（Discrete(7)；follow 在单 Boss 单遭遇 sim 中无意义，故省略）
# ---------------------------------------------------------------------------
ACTION_NOOP = 0
ACTION_BASIC_ATTACK = 1
ACTION_EXPLOSION = 2
ACTION_QUICK_HEAL = 3
ACTION_MAJOR_HEAL = 4
ACTION_SHIELD = 5
ACTION_RETREAT = 6
N_ACTIONS = 7

ABILITY_ACTIONS = {
    ABIL_EXPLOSION: ACTION_EXPLOSION,
    ABIL_QUICK_HEAL: ACTION_QUICK_HEAL,
    ABIL_MAJOR_HEAL: ACTION_MAJOR_HEAL,
    ABIL_SHIELD: ACTION_SHIELD,
    "ability.alice.basic_attack": ACTION_BASIC_ATTACK,
}

# ---------------------------------------------------------------------------
# 帧长与终局
# ---------------------------------------------------------------------------
TICK_SECONDS = 1.0
MAX_TICKS = 300

# ---------------------------------------------------------------------------
# Boss（HP/眩晕均为百分比口径，与 CombatContext 的 *_percent 一致）
# ---------------------------------------------------------------------------
BOSS_MAX_HP = 100.0
BOSS_BASE_DAMAGE = 3.0        # 每 tick 对玩家的基础伤害
BOSS_PHASE2_HP = 50.0         # hp ≤ 50 → phase2，伤害 ×1.5
BOSS_PHASE3_HP = 20.0         # hp ≤ 20 → phase3（狂暴），伤害 ×2
BOSS_PHASE2_MULT = 1.5
BOSS_PHASE3_MULT = 2.0
STUN_METER_MAX = 100.0        # 眩晕值 ≥100 → 进入眩晕
STUN_DURATION_S = 6.0         # 眩晕持续；期间不攻击、受伤害 ×2.5
STUNNED_TAKEN_MULT = 2.5
PLAYER_AUTO_STUN = 3.0        # 玩家普攻每 tick 积累的眩晕值
COMPANION_ATTACK_STUN = 4.0   # 奥术弹命中积累的眩晕值
EXPLOSION_STUN = 40.0         # 爆裂魔法积累的眩晕值

# Boss 偶发 AOE 波及同伴（概率事件，走 rng 保证可复现）
AOE_CHANCE = 0.08
AOE_DAMAGE_MIN = 8.0
AOE_DAMAGE_SPAN = 7.0

# ---------------------------------------------------------------------------
# 玩家 / 同伴
# ---------------------------------------------------------------------------
PLAYER_MAX_HP = 100.0
PLAYER_AUTO_DPS = 2.0         # 玩家每 tick 对 Boss 的自动输出
COMPANION_MAX_HP = 100.0
COMPANION_MAX_MP = 100.0
MP_REGEN_PER_TICK = 2.0
RETREAT_TICKS = 4             # 撤退持续：受伤减半、玩家停止输出（不再积累眩晕）
RETREAT_DAMAGE_MULT = 0.5
SHIELD_TICKS = 3              # 护盾持续 3 tick，受伤 ×0.2
SHIELD_DAMAGE_MULT = 0.2

# ---------------------------------------------------------------------------
# 技能表（ability_id → 耗蓝 / CD / 效果；ID 与线上 resolver 同源）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AbilitySpec:
    ability_id: str
    mp_cost: float
    cooldown_s: float
    action: int


ABILITY_SPECS: dict[str, AbilitySpec] = {
    "ability.alice.basic_attack": AbilitySpec("ability.alice.basic_attack", 0.0, 1.0, ACTION_BASIC_ATTACK),
    ABIL_EXPLOSION: AbilitySpec(ABIL_EXPLOSION, 35.0, 30.0, ACTION_EXPLOSION),
    ABIL_QUICK_HEAL: AbilitySpec(ABIL_QUICK_HEAL, 15.0, 8.0, ACTION_QUICK_HEAL),
    ABIL_MAJOR_HEAL: AbilitySpec(ABIL_MAJOR_HEAL, 40.0, 25.0, ACTION_MAJOR_HEAL),
    ABIL_SHIELD: AbilitySpec(ABIL_SHIELD, 20.0, 15.0, ACTION_SHIELD),
}

EXPLOSION_BOSS_DAMAGE = 15.0
BASIC_ATTACK_BOSS_DAMAGE = 2.0
QUICK_HEAL_AMOUNT = 25.0
MAJOR_HEAL_AMOUNT = 60.0

# 奖励函数引用的治疗阈值（与 resolver 同源，用于判定「浪费治疗」）
HEAL_WASTE_THRESHOLD = PLAYER_HP_LOW


@dataclass
class SimConstants:
    """模拟器数值集合；测试可用覆盖字段构造变体（如高伤 Boss 加速终局）。"""

    tick_seconds: float = TICK_SECONDS
    max_ticks: int = MAX_TICKS
    boss_max_hp: float = BOSS_MAX_HP
    boss_base_damage: float = BOSS_BASE_DAMAGE
    player_auto_dps: float = PLAYER_AUTO_DPS
    companion_max_hp: float = COMPANION_MAX_HP
    companion_max_mp: float = COMPANION_MAX_MP
    mp_regen: float = MP_REGEN_PER_TICK
    aoe_chance: float = AOE_CHANCE
    explosion_boss_damage: float = EXPLOSION_BOSS_DAMAGE
    basic_attack_boss_damage: float = BASIC_ATTACK_BOSS_DAMAGE
    quick_heal_amount: float = QUICK_HEAL_AMOUNT
    major_heal_amount: float = MAJOR_HEAL_AMOUNT
    specs: dict = field(default_factory=lambda: dict(ABILITY_SPECS))


DEFAULT_CONSTANTS = SimConstants()
