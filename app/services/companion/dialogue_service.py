"""陪伴对话服务入口：默认模拟回复，配置后可调用 LLM。"""

import zlib

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
    """无 LLM 时的回复：按输入分类选候选；全部未命中退回默认回复。

    同一输入始终得到同一回复（哈希轮换是确定性的），不同输入在候选间分散。
    """
    presentation = _select_fallback_presentation(request.text, profile)
    return CompanionDialogueResponse(
        companion_id=request.companion_id,
        reply_text=presentation.reply_text,
        emotion_id=presentation.emotion_id,
        gesture_id=presentation.gesture_id,
        facial_expression_id=presentation.facial_expression_id,
        interruptible=presentation.interruptible,
        source=source,
    )


def _select_fallback_presentation(text: str, profile: CompanionProfile) -> object:
    """类别判序按 YAML fallback_dialogue_responses 的出现顺序（先命中先选）。"""
    for category in profile.fallback_reply_categories:
        if any(keyword in text for keyword in category.keywords):
            return category.replies[_stable_index(text, len(category.replies))]
    return profile.default_dialogue_response


def _stable_index(text: str, count: int) -> int:
    """文本的稳定哈希轮换：同输入（含跨进程重启）恒定，不同输入近似均匀分布。"""
    return zlib.crc32(text.encode("utf-8")) % count if count else 0
