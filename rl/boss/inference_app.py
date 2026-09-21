"""Standalone FastAPI app for frozen Boss policy inference."""

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from rl.boss.contract import OBSERVATION_DIM, SCHEMA_VERSION
from rl.boss.inference import (
    UNREAL_ACTION_NAMES,
    BossPolicyRuntime,
    runtime_metadata,
)

PROTOCOL_VERSION = "1.0"


class BossPolicyRequest(BaseModel):
    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    schema_version: Literal[4] = SCHEMA_VERSION
    sequence: int = Field(ge=0)
    observation: list[float]

    @field_validator("observation")
    @classmethod
    def validate_observation(cls, values: list[float]) -> list[float]:
        if len(values) != OBSERVATION_DIM:
            raise ValueError(
                f"schema v{SCHEMA_VERSION} requires {OBSERVATION_DIM} values"
            )
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("observation values must be within [0, 1]")
        return values


class BossPolicyResponse(BaseModel):
    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    request_id: str
    schema_version: Literal[4] = SCHEMA_VERSION
    sequence: int
    model_id: str
    actionable: bool
    action_id: int | None = Field(default=None, ge=0, le=8)
    action_name: str | None = None
    reason: str
    inference_milliseconds: float = Field(ge=0.0)


def create_app(runtime: BossPolicyRuntime | None = None) -> FastAPI:
    policy_runtime = runtime or BossPolicyRuntime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        policy_runtime.load()
        yield

    app = FastAPI(
        title="Aesir Boss Policy Service",
        version=PROTOCOL_VERSION,
        description="Frozen high-level Boss policy inference. GAS remains authoritative.",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        return {
            "status": "ok" if policy_runtime.is_loaded else "not_loaded",
            "service": "aesir-boss-policy-service",
            "protocol_version": PROTOCOL_VERSION,
            **runtime_metadata(policy_runtime),
        }

    @app.post(
        "/v1/boss/policy/decide",
        response_model=BossPolicyResponse,
        tags=["boss-policy"],
    )
    def decide(request: BossPolicyRequest) -> BossPolicyResponse:
        try:
            decision = policy_runtime.decide(request.observation)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return BossPolicyResponse(
            request_id=request.request_id,
            sequence=request.sequence,
            model_id=policy_runtime.model_id,
            actionable=decision.actionable,
            action_id=int(decision.action) if decision.action is not None else None,
            action_name=(
                UNREAL_ACTION_NAMES[decision.action]
                if decision.action is not None
                else None
            ),
            reason=decision.reason,
            inference_milliseconds=decision.inference_milliseconds,
        )

    return app


app = create_app()
