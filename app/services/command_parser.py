from app.schemas.tactical_order import (
    Action,
    ParseCommandResponse,
    TacticalOrder,
    Trigger,
)


def parse_command(text: str) -> ParseCommandResponse:
    """Temporary deterministic parser used before an LLM adapter is introduced.

    The output schema is deliberately constrained to identifiers that UE can validate.
    """
    normalized = text.strip().lower().replace("，", ",").replace("。", "")
    has_eirin = "艾琳" in normalized or "eirin" in normalized
    has_boss = "boss" in normalized
    has_stun = "眩晕" in normalized or "stun" in normalized
    has_explosion = "爆裂魔法" in normalized or "explosion" in normalized

    if has_eirin and has_boss and has_stun and has_explosion:
        return ParseCommandResponse(
            recognized=True,
            order=TacticalOrder(
                agent="Eirin",
                intent="conditional_cast",
                trigger=Trigger(target="Boss", state="Stunned"),
                action=Action(type="CastAbility", ability_id="Explosion"),
            ),
            message="Command recognized: Eirin will cast Explosion when the Boss is stunned.",
        )

    return ParseCommandResponse(
        recognized=False,
        message="Command not recognized by the current rule parser.",
    )
