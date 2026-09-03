"""语音战术指令端点：音频 → ASR 转写 → 既有解析层 → ParseCommandResponse。

与 ``/v1/commands/parse`` 共享同一个解析层与契约 v0.1；唯一区别是本端点
先用转写后端把音频变成文本，再送入 ``parse_command``。UE 传输约定：
WAV / 16kHz / 单声道 / 16bit（multipart 上传）。
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.schemas.tactical_order import (
    DEFAULT_CONTEXT,
    ParseCommandContext,
    ParseCommandResponse,
)
from app.services.command_parser import parse_command
from app.services.transcribers.base import TranscriptionError
from app.services.transcribers.factory import get_transcriber

router = APIRouter(prefix="/v1/voice", tags=["voice"])


@router.post("/command", response_model=ParseCommandResponse)
def transcribe_and_parse_voice(
    file: UploadFile = File(..., description="音频文件（WAV 16kHz / 单声道 / 16bit）"),
    request_id: str | None = Form(
        default=None, description="客户端 UUID，响应原样回显；缺省由服务端生成"
    ),
    context_json: str | None = Form(
        default=None, description="ParseCommandContext 的 JSON 字符串；缺省回填默认能力目录"
    ),
) -> ParseCommandResponse:
    if request_id is not None:
        try:
            request_id = UUID(request_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid request_id: must be a UUID",
            ) from None
    else:
        request_id = uuid4()

    context = DEFAULT_CONTEXT
    if context_json:
        try:
            context = ParseCommandContext.model_validate_json(context_json)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid context: {exc}",
            ) from exc

    audio = file.file.read() or b""
    try:
        text = get_transcriber().transcribe(audio)
    except TranscriptionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error

    return parse_command(text, context, request_id)