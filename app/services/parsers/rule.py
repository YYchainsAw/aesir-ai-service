"""确定性规则解析器，覆盖第一批五条指令，输出契约 v0.1 的判别联合 order。

它只在能力目录 ``context`` 允许时产出 order（尤其技能/目标/状态 ID 必须存在于
目录），否则明确 ``recognized: false``，保证 UE 永不收到越界 ID。约束越强的
指令越靠前判断，保证「最具体的意图」优先命中。
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
from app.services.ids import (
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

        # agent 已在目录：艾琳可控
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

        if not _has_any(t, "艾琳", "eirin"):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=False,
                message="Command not recognized: no supported agent (expected Eirin).",
            )

        cat = _Catalog(context)

        # 1. 条件施法：Boss 眩晕时释放爆裂魔法。
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
                message="Command recognized: cast Explosion when the Boss is stunned.",
            )

        # 2. 保留技能：把爆裂魔法握在手里暂时不用。
        if (
            cat.has_explosion
            and _has_any(t, "保留", "hold", "save", "先别用", "不要用", "攒")
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
                message="Command recognized: hold Explosion in reserve.",
            )

        # 3. 撤退：后撤并优先保命。
        if cat.has_agent and _has_any(t, "撤退", "retreat", "保命", "撤离", "逃跑"):
            return ParseCommandResponse(
                request_id=request_id,
                recognized=True,
                order=Retreat(agent_id=AGENT, then=RetreatAction(), priority=90),
                message="Command recognized: retreat and prioritize survival.",
            )

        # 4. 跟随并保持距离。
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
                message="Command recognized: follow the player and keep distance.",
            )

        # 5. 优先普通攻击。
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
                message="Command recognized: prioritize normal attacks.",
            )

        return ParseCommandResponse(
            request_id=request_id,
            recognized=False,
            message="Command not recognized by the current rule parser.",
        )