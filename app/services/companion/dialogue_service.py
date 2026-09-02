"""陪伴对话服务入口：默认模拟回复，配置后可调用 LLM。"""

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.config import get_companion_backend
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
from app.services.llm.client import LLMClientError


def create_dialogue_reply(
    request: CompanionDialogueRequest,
) -> CompanionDialogueResponse:
    """按配置选择 LLM；不可用时安全回退到固定回复。"""
    if get_companion_backend() == "llm":
        try:
            return LLMCompanionDialogueService().reply(request)
        except LLMClientError:
            return _create_mock_dialogue_reply(request, source="fallback")

    return _create_mock_dialogue_reply(request, source="mock")


def _create_mock_dialogue_reply(
    request: CompanionDialogueRequest,
    *,
    source: str,
) -> CompanionDialogueResponse:
    """返回稳定、可预测的临时陪伴对话响应。"""
    return CompanionDialogueResponse(
        companion_id=request.companion_id,
        reply_text="我在呢。想聊什么？",
        emotion_id="emotion.bright",
        gesture_id="gesture.cheerful_idle",
        facial_expression_id="face.bright_smile",
        interruptible=True,
        source=source,
    )
