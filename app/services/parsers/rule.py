from app.schemas.tactical_order import (
    AttackAction,
    CastAbilityAction,
    ConditionalCast,
    FollowAction,
    FollowKeepDistance,
    HoldAbility,
    HoldAbilityAction,
    ParseCommandResponse,
    PrioritizeAttack,
    Retreat,
    RetreatAction,
    Trigger,
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


class RuleCommandParser(CommandParser):
    """确定性规则解析器，覆盖第一批五条指令。

    后续会被 LLM 适配器替换，但输出 Schema 保持不变。约束越强的指令越靠前
    判断，保证「最具体的意图」优先命中。
    """

    def parse(self, text: str) -> ParseCommandResponse:
        t = _normalize(text)

        if not _has_any(t, "艾琳", "eirin"):
            return ParseCommandResponse(
                recognized=False,
                message="Command not recognized: no supported agent (expected Eirin).",
            )

        # 1. 条件施法：Boss 眩晕时释放爆裂魔法。
        if _has_any(t, "眩晕", "stun") and _has_any(t, "爆裂魔法", "explosion"):
            return ParseCommandResponse(
                recognized=True,
                order=ConditionalCast(
                    trigger=Trigger(target="Boss", state="Stunned"),
                    action=CastAbilityAction(type="CastAbility", ability_id="Explosion"),
                ),
                message="Command recognized: cast Explosion when the Boss is stunned.",
            )

        # 2. 保留技能：把爆裂魔法握在手里暂时不用。
        if _has_any(t, "保留", "hold", "save", "先别用", "不要用", "攒") and _has_any(
            t, "爆裂魔法", "explosion"
        ):
            return ParseCommandResponse(
                recognized=True,
                order=HoldAbility(
                    action=HoldAbilityAction(type="HoldAbility", ability_id="Explosion")
                ),
                message="Command recognized: hold Explosion in reserve.",
            )

        # 3. 撤退：后撤并优先保命。
        if _has_any(t, "撤退", "retreat", "保命", "撤离", "逃跑"):
            return ParseCommandResponse(
                recognized=True,
                order=Retreat(action=RetreatAction(type="Retreat")),
                message="Command recognized: retreat and prioritize survival.",
            )

        # 4. 跟随并保持距离。
        if _has_any(t, "跟随", "跟着", "follow", "跟我") and _has_any(t, "距离", "distance"):
            return ParseCommandResponse(
                recognized=True,
                order=FollowKeepDistance(
                    action=FollowAction(type="Follow", target="Player", keep_distance=True)
                ),
                message="Command recognized: follow the player and keep distance.",
            )

        # 5. 优先普通攻击。
        if _has_any(t, "优先") and _has_any(t, "普通攻击", "普攻", "平a", "平砍", "attack"):
            return ParseCommandResponse(
                recognized=True,
                order=PrioritizeAttack(action=AttackAction(type="Attack")),
                message="Command recognized: prioritize normal attacks.",
            )

        return ParseCommandResponse(
            recognized=False,
            message="Command not recognized by the current rule parser.",
        )