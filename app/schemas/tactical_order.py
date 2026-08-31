from typing import Literal

from pydantic import BaseModel, Field


class ParseCommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="Player text command")


class Trigger(BaseModel):
    target: Literal["Boss"]
    state: Literal["Stunned"]


class Action(BaseModel):
    type: Literal["CastAbility"]
    ability_id: Literal["Explosion"]


class TacticalOrder(BaseModel):
    protocol_version: Literal["1.0"] = "1.0"
    agent: Literal["Eirin"]
    intent: Literal["conditional_cast"]
    trigger: Trigger
    action: Action
    priority: Literal["high"] = "high"
    expires_on: Literal["EncounterEnd"] = "EncounterEnd"


class ParseCommandResponse(BaseModel):
    recognized: bool
    order: TacticalOrder | None = None
    message: str
