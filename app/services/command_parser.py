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


def parse_command(text: str) -> ParseCommandResponse:
    """Deterministic rule parser covering the first batch of five commands.

    Replaced later by an LLM adapter without changing the output schema. The
    most specific intent wins, so more-constrained commands are checked first.
    """
    t = _normalize(text)

    if not _has_any(t, "艾琳", "eirin"):
        return ParseCommandResponse(
            recognized=False,
            message="Command not recognized: no supported agent (expected Eirin).",
        )

    # 1. Conditional cast: cast Explosion when the Boss is stunned.
    if _has_any(t, "眩晕", "stun") and _has_any(t, "爆裂魔法", "explosion"):
        return ParseCommandResponse(
            recognized=True,
            order=ConditionalCast(
                trigger=Trigger(target="Boss", state="Stunned"),
                action=CastAbilityAction(type="CastAbility", ability_id="Explosion"),
            ),
            message="Command recognized: cast Explosion when the Boss is stunned.",
        )

    # 2. Hold ability: keep Explosion in reserve.
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

    # 3. Retreat: back off and prioritize survival.
    if _has_any(t, "撤退", "retreat", "保命", "撤离", "逃跑"):
        return ParseCommandResponse(
            recognized=True,
            order=Retreat(action=RetreatAction(type="Retreat")),
            message="Command recognized: retreat and prioritize survival.",
        )

    # 4. Follow and keep distance.
    if _has_any(t, "跟随", "跟着", "follow", "跟我") and _has_any(t, "距离", "distance"):
        return ParseCommandResponse(
            recognized=True,
            order=FollowKeepDistance(
                action=FollowAction(type="Follow", target="Player", keep_distance=True)
            ),
            message="Command recognized: follow the player and keep distance.",
        )

    # 5. Prioritize normal attacks.
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
