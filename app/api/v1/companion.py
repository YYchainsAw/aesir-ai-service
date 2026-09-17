import json
from collections.abc import Iterator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.schemas.world_context import WorldContext
from app.services.companion.dialogue_service import (
    create_dialogue_reply,
    stream_dialogue_reply,
)
from app.services.companion.llm_dialogue_service import StreamEvent
from app.services.companion.profile_repository import UnknownCompanionError
from app.services.transcribers.base import TranscriptionError
from app.services.transcribers.factory import get_transcriber

router = APIRouter(prefix="/v1/companion", tags=["companion"])


@router.post("/chat", response_model=CompanionDialogueResponse)
def chat_with_companion(request: CompanionDialogueRequest) -> CompanionDialogueResponse:
    """返回非战斗陪伴对话的模拟响应。

    仅允许 exploration / conversation 状态调用；战斗战术必须继续使用独立接口。
    """
    try:
        return create_dialogue_reply(request)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/chat/stream")
def chat_with_companion_stream(request: CompanionDialogueRequest) -> StreamingResponse:
    """/chat 的流式变体（SSE）：delta 帧出文本增量，meta 帧出权威完整响应。

    契约见 ue-protocol-contract-v0.1.md 的 SSE 附录；非流式端点保持不变。
    """
    try:
        stream = stream_dialogue_reply(request)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return StreamingResponse(
        _sse_frames(stream),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class VoiceCompanionDialogueResponse(CompanionDialogueResponse):
    """/chat/voice 的响应：在既有对话响应之上附带 ASR 转写文本。

    ``transcribed_text`` 供 UE 展示「你说了什么」与调试转写质量；其余
    字段与 /v1/companion/chat 完全一致。
    """

    transcribed_text: str


@router.post("/chat/voice", response_model=VoiceCompanionDialogueResponse)
def chat_with_companion_voice(
    audio: UploadFile = File(..., description="音频文件（WAV 16kHz / 单声道 / 16bit）"),
    companion_id: str = Form(default="companion.alice"),
    game_state: str = Form(default="exploration"),
    session_id: str | None = Form(default=None),
    world_context_json: str | None = Form(
        default=None, description="WorldContext 的 JSON 字符串（可选，同 /chat 的 world_context）"
    ),
) -> VoiceCompanionDialogueResponse:
    """语音陪伴对话：音频 → ASR 转写 → 既有对话链路。

    与 ``/v1/voice/command`` 同款模式，尾部接陪伴对话而非战术指令解析；
    记忆 / 关系 / 信号埋点全部生效。转写失败 502、空转写 422——对话里
    「听错还硬答」比「明确听不清」更糟，不回退 mock 文本。
    """
    data = audio.file.read() or b""
    try:
        text = get_transcriber().transcribe(data)
    except TranscriptionError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未识别出语音内容"
        )

    world_context: WorldContext | None = None
    if world_context_json:
        try:
            world_context = WorldContext.model_validate_json(world_context_json)
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"invalid world_context: {error}"
            ) from error

    try:
        request = CompanionDialogueRequest(
            text=text,
            companion_id=companion_id,
            game_state=game_state,  # type: ignore[arg-type]
            session_id=session_id,
            world_context=world_context,
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"invalid request: {error}"
        ) from error

    try:
        response = create_dialogue_reply(request)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return VoiceCompanionDialogueResponse(
        **response.model_dump(), transcribed_text=text
    )


def _sse_frames(events: Iterator[StreamEvent]) -> Iterator[str]:
    """把 StreamEvent 逐个格式化为 SSE 帧（event + 单行 JSON data）。"""
    for event in events:
        yield _format_frame(event)


def _format_frame(event: StreamEvent) -> str:
    if event.kind == "delta":
        data = {"protocol_version": "0.1", "text": event.text}
    elif event.kind == "meta":
        assert event.response is not None
        data = event.response.model_dump()
    else:
        data = {"detail": event.text}
    return f"event: {event.kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
