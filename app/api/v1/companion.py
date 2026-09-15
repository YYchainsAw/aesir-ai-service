import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.services.companion.dialogue_service import (
    create_dialogue_reply,
    stream_dialogue_reply,
)
from app.services.companion.llm_dialogue_service import StreamEvent
from app.services.companion.profile_repository import UnknownCompanionError

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
