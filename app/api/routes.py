from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas.tactical_order import (
    DEFAULT_CONTEXT,
    PROTOCOL_VERSION,
    ParseCommandRequest,
    ParseCommandResponse,
)
from app.services.command_parser import parse_command

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Returns immediately so UE can verify that the local service is available."""
    return {"status": "ok", "service": "aesir-ai-service", "protocol_version": PROTOCOL_VERSION}


# 遗留别名：旧客户端只传 text，由服务端回填默认能力目录与 request_id。
class _LegacyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post(
    "/parse-command",
    response_model=ParseCommandResponse,
    tags=["commands"],
    description="遗留兼容入口：只传 text，内部回填默认能力目录。正式联调请用 /v1/commands/parse。",
)
def parse_tactical_command_legacy(request: _LegacyRequest) -> ParseCommandResponse:
    """把纯文本指令按默认能力目录解析为 UE-safe tactical order。"""
    return parse_command(request.text, DEFAULT_CONTEXT, uuid4())


@router.post(
    "/v1/commands/parse",
    response_model=ParseCommandResponse,
    tags=["commands"],
    description="契约 v0.1：携带 UE 能力目录 context 与 request_id，解析战术指令。",
)
def parse_command_v1(request: ParseCommandRequest) -> ParseCommandResponse:
    """把玩家文本指令、配合 UE 能力目录解析为受限 TacticalOrder。"""
    return parse_command(request.text, request.context, request.request_id)