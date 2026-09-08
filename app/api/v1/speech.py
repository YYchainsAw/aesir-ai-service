"""独立语音转写端点：音频 → 文本，不接解析层。

与组合端点 ``/v1/voice/command`` 并存：UE 可先调用本端点单独调试 ASR，
拿到文本后再调 ``/v1/commands/parse``。两个基础端点长期保留，不得删除。
请求/响应格式见 ``docs/UE5_模型服务联调技术规范_v0.1.md`` §6.3。
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.config import get_settings
from app.services.transcribers.base import TranscriptionError
from app.services.transcribers.factory import get_transcriber

router = APIRouter(prefix="/v1/speech", tags=["speech"])


class TranscribeSpeechResponse(BaseModel):
    """转写结果；``text`` 为空串表示未识别出语音内容。"""

    request_id: UUID
    text: str
    language: str


@router.post("/transcribe", response_model=TranscribeSpeechResponse)
def transcribe_speech(
    audio: UploadFile = File(..., description="音频文件（WAV 16kHz / 单声道 / 16bit）"),
    request_id: str | None = Form(
        default=None, description="客户端 UUID，响应原样回显；缺省由服务端生成"
    ),
    locale: str | None = Form(
        default=None, description="预留语言提示；当前后端统一按服务端配置语言转写"
    ),
) -> TranscribeSpeechResponse:
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

    data = audio.file.read() or b""
    try:
        text = get_transcriber().transcribe(data)
    except TranscriptionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error

    return TranscribeSpeechResponse(
        request_id=request_id,
        text=text,
        language=get_settings().asr_language,
    )
