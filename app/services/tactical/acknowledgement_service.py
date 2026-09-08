"""从主队友人设资料生成战术确认回复。"""

from typing import Any

from app.schemas.tactical_order import TacticalAcknowledgement
from app.services.companion.profile_repository import get_profile


def create_tactical_acknowledgement(intent: str) -> TacticalAcknowledgement | None:
    """为已识别的意图读取 YAML 中登记的短回复。"""
    profile = get_profile()
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
