"""从对应角色的人设资料生成战术确认回复。"""

from typing import Any

from app.schemas.tactical_order import TacticalAcknowledgement
from app.services.companion.profile_repository import (
    CompanionProfileError,
    get_registered_profile,
)


def create_tactical_acknowledgement(
    intent: str, *, companion_id: str
) -> TacticalAcknowledgement | None:
    """为已识别的意图读取对应角色 YAML 中登记的短回复。

    未登记角色或配置缺失/越界时返回 ``None``，由调用方回退默认回复。
    """
    try:
        profile = get_registered_profile(companion_id)
    except CompanionProfileError:
        return None

    acknowledgements = profile.raw.get("tactical_acknowledgements")
    if not isinstance(acknowledgements, dict):
        return None

    response = acknowledgements.get(intent)
    if not isinstance(response, dict):
        return None

    reply_text = response.get("reply_text")
    emotion_id = response.get("emotion_id")
    if not isinstance(reply_text, str) or not reply_text.strip():
        return None
    if not isinstance(emotion_id, str) or emotion_id not in profile.allowed_emotion_ids:
        return None

    return TacticalAcknowledgement(reply_text=reply_text, emotion_id=emotion_id)
