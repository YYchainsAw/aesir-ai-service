"""陪伴对话服务入口：默认模拟回复，配置后可调用 LLM。"""

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.config import get_settings
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
from app.services.companion.profile_repository import (
    CompanionProfile,
    UnknownCompanionError,
    get_profile,
)
from app.services.llm.client import LLMClientError


def create_dialogue_reply(request: CompanionDialogueRequest) -> CompanionDialogueResponse:
    """按 YAML 人设选择 LLM；不可用时回退到 YAML 默认回复。"""
    # mtime 缓存读取人设；id 校验语义与 require_primary 一致（404 路径不变）。
    profile = get_profile()
    if profile.companion_id != request.companion_id:
        raise UnknownCompanionError(f"Unsupported companion_id: {request.companion_id}")

    if get_settings().companion_backend == "llm":
        try:
            return LLMCompanionDialogueService(profile=profile).reply(request)
        except LLMClientError:
            return _create_mock_dialogue_reply(request, profile=profile, source="fallback")

    return _create_mock_dialogue_reply(request, profile=profile, source="mock")


def _create_mock_dialogue_reply(
    request: CompanionDialogueRequest,
    *,
    profile: CompanionProfile,
    source: str,
) -> CompanionDialogueResponse:
    """从 YAML 的 default_dialogue_response 创建临时回复。"""
    defaults = profile.default_dialogue_response
    return CompanionDialogueResponse(
        companion_id=request.companion_id,
        reply_text=defaults.reply_text,
        emotion_id=defaults.emotion_id,
        gesture_id=defaults.gesture_id,
        facial_expression_id=defaults.facial_expression_id,
        interruptible=defaults.interruptible,
        source=source,
    )
