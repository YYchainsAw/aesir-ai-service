"""Tactical order schemas shared by API routes and services.

Every field is constrained to a small whitelist so UE can validate an order
before executing it. ``TacticalOrder`` is a discriminated union selected by
the ``intent`` field: each intent exposes only the trigger/action fields that
make sense for it.
"""

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field


class _StrictSchema(BaseModel):
    """拒绝 LLM 或调用方传入的未声明字段。"""

    model_config = ConfigDict(extra="forbid")


class ParseCommandRequest(_StrictSchema):
    text: str = Field(min_length=1, max_length=500, description="Player text command")


# ---------------------------------------------------------------------------
# Shared envelope fields (kept flat so UE's C++ struct maps 1:1)
# ---------------------------------------------------------------------------
class _OrderBase(_StrictSchema):
    protocol_version: Literal["1.0"] = "1.0"
    agent: Literal["Eirin"] = "Eirin"
    priority: Literal["high"] = "high"
    expires_on: Literal["EncounterEnd"] = "EncounterEnd"


# ---------------------------------------------------------------------------
# Trigger / action vocabulary (whitelist for UE validation)
# ---------------------------------------------------------------------------
class Trigger(_StrictSchema):
    target: Literal["Boss"]
    state: Literal["Stunned"]


class CastAbilityAction(_StrictSchema):
    type: Literal["CastAbility"]
    ability_id: Literal["Explosion"]


class HoldAbilityAction(_StrictSchema):
    type: Literal["HoldAbility"]
    ability_id: Literal["Explosion"]


class AttackAction(_StrictSchema):
    type: Literal["Attack"]


class FollowAction(_StrictSchema):
    type: Literal["Follow"]
    target: Literal["Player"]
    keep_distance: bool = True


class RetreatAction(_StrictSchema):
    type: Literal["Retreat"]


# ---------------------------------------------------------------------------
# Intent variants (first batch of five commands)
# ---------------------------------------------------------------------------
class ConditionalCast(_OrderBase):
    """1. 艾琳，等 Boss 眩晕时使用爆裂魔法。"""

    intent: Literal["conditional_cast"] = "conditional_cast"
    trigger: Trigger
    action: CastAbilityAction


class HoldAbility(_OrderBase):
    """2. 艾琳，保留爆裂魔法。"""

    intent: Literal["hold_ability"] = "hold_ability"
    action: HoldAbilityAction


class PrioritizeAttack(_OrderBase):
    """3. 艾琳，优先普通攻击。"""

    intent: Literal["prioritize_attack"] = "prioritize_attack"
    action: AttackAction


class FollowKeepDistance(_OrderBase):
    """4. 艾琳，跟随我并保持距离。"""

    intent: Literal["follow_keep_distance"] = "follow_keep_distance"
    action: FollowAction


class Retreat(_OrderBase):
    """5. 艾琳，撤退并优先保命。"""

    intent: Literal["retreat"] = "retreat"
    action: RetreatAction


TacticalOrder: TypeAlias = Annotated[
    Union[
        ConditionalCast,
        HoldAbility,
        PrioritizeAttack,
        FollowKeepDistance,
        Retreat,
    ],
    Field(discriminator="intent"),
]


class ParseCommandResponse(_StrictSchema):
    recognized: bool
    order: TacticalOrder | None = None
    message: str
