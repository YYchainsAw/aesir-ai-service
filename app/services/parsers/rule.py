"""确定性规则解析器，覆盖第一批五条指令，输出契约 v0.1 的判别联合 order。

它只在能力目录 ``context`` 允许时产出 order（尤其技能/目标/状态 ID 必须存在于
目录），否则明确 ``recognized: false``，保证 UE 永不收到越界 ID。

多意图冲突时按 order 的 ``priority`` 降序判断（撤退 90 > 条件施法 80 > 保留
60 > 优先普攻 50 > 跟随 40），保证高优先级意图先命中——例如「别放爆裂魔法，
快撤退保命」应产出 retreat 而非 hold。
"""

from uuid import UUID

from app.schemas.tactical_order import (
    CastAbilityAction,
    ConditionalCast,
    DEFAULT_CONTEXT,
    FollowAction,
    FollowKeepDistance,
    HoldAbility,
    HoldAbilityAction,
    ParseCommandContext,
    ParseCommandResponse,
    PrioritizeAttack,
    Retreat,
    RetreatAction,
    SetPriorityAction,
    TargetRef,
    WhenStateEntered,
)
from app.schemas.ids import (
    ABILITY_EXPLOSION,
    AGENT,
    SELECTOR_PRIMARY_HOSTILE,
    SELECTOR_PLAYER,
    STATE_STUNNED,
)
from app.services.parsers.base import CommandParser


def _normalize(text: str) -> str:
    return (
        text.strip()
        .lower()
        .replace("，", ",")
        .replace("。", "")
        .replace(" ", "")
    )


def _has_any(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)


class _Catalog:
    """从能力目录 ``context`` 提炼出的五条规则各自所需的许可布尔值。"""

    def __init__(self, context: ParseCommandContext) -> None:
        agent_ability_ids = {
            a.id: set(a.ability_ids) for a in context.agents
        }
        selectors = set(context.target_selectors)
        states = set(context.state_tags)

        # agent 已在目录：艾莉可控
        self.has_agent = AGENT in agent_ability_ids
        # 目录允许「爆裂魔法」这一技能
        self.has_explosion = ABILITY_EXPLOSION in agent_ability_ids.get(AGENT, set())
        # 目录允许「主要敌人」选择器引用
        self.has_hostile = SELECTOR_PRIMARY_HOSTILE in selectors
        # 目录允许「玩家」选择器引用
        self.has_player = SELECTOR_PLAYER in selectors
        # 目录允许「眩晕」状态触发
        self.has_stunned = STATE_STUNNED in states


class RuleCommandParser(CommandParser):
    """规则解析器。context 决定哪些 ID 可用；缺省用 DEFAULT_CONTEXT。"""

    def parse(
        self,
        text: str,
        context: ParseCommandContext = DEFAULT_CONTEXT,
        request_id: UUID | None = None,
    ) -> ParseCommandResponse:
        t = _normalize(text)

        if not _has_any(t, "艾莉", "艾琳", "alice", "eirin"):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=False,
                message="当前无法确认该技能或目标。",
            )

        cat = _Catalog(context)

        # 1. 撤退（priority 90）：后撤并优先保命。
        if cat.has_agent and _has_any(t, "撤退", "retreat", "保命", "撤离", "逃跑"):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=True,
                order=Retreat(agent_id=AGENT, then=RetreatAction(), priority=90),
                message="知道了，先撤，优先保命。",
            )

        # 2. 条件施法（priority 80）：Boss 眩晕时释放爆裂魔法。
        if (
            cat.has_agent
            and cat.has_explosion
            and cat.has_hostile
            and cat.has_stunned
            and _has_any(t, "眩晕", "stun")
            and _has_any(t, "爆裂魔法", "explosion")
        ):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=True,
                order=ConditionalCast(
                    agent_id=AGENT,
                    when=WhenStateEntered(
                        subject=SELECTOR_PRIMARY_HOSTILE, tag=STATE_STUNNED
                    ),
                    then=CastAbilityAction(
                        ability_id=ABILITY_EXPLOSION, target=TargetRef(ref="when.subject")
                    ),
                    priority=80,
                ),
                message="好，等 Boss 眩晕时释放爆裂魔法。",
            )

        # 3. 保留技能（priority 60）：把爆裂魔法握在手里暂时不用。
        #    覆盖契约 golden 示例「这一整场都不要放爆裂魔法」的「不要放」表达。
        if (
            cat.has_explosion
            and _has_any(t, "保留", "hold", "save", "先别用", "不要用", "不要放", "别放", "攒")
            and _has_any(t, "爆裂魔法", "explosion")
        ):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=True,
                order=HoldAbility(
                    agent_id=AGENT,
                    then=HoldAbilityAction(ability_id=ABILITY_EXPLOSION, active=True),
                    priority=60,
                ),
                message="明白，先把爆裂魔法保留住。",
            )

        # 4. 跟随并保持距离（priority 40）。
        if (
            cat.has_player
            and _has_any(t, "跟随", "跟着", "follow", "跟我")
            and _has_any(t, "距离", "distance")
        ):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=True,
                order=FollowKeepDistance(
                    agent_id=AGENT,
                    then=FollowAction(target=SELECTOR_PLAYER, keep_distance=True),
                    priority=40,
                ),
                message="好，跟上你并保持施法距离。",
            )

        # 5. 优先普通攻击（priority 50）。
        if cat.has_explosion and _has_any(t, "优先") and _has_any(
            t, "普通攻击", "普攻", "平a", "平砍", "attack"
        ):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=True,
                order=PrioritizeAttack(
                    agent_id=AGENT,
                    then=SetPriorityAction(mode="basic_attack_first"),
                    priority=50,
                ),
                message="了解，优先普通攻击。",
            )

        return ParseCommandResponse(
            request_id=request_id,
            recognized=False,
            message="当前无法确认该技能或目标。",
        )