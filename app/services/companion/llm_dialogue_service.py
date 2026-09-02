"""使用共享 LLM 客户端生成非战斗陪伴对话。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.services.llm.client import LLMClient, LLMClientError
from app.services.llm.factory import create_llm_client

_PROFILE_PATH = Path(__file__).resolve().parents[3] / "data" / "companions" / "primary_companion.yaml"


class _DialoguePayload(BaseModel):
    """LLM 可输出的最小对话负载；封套字段由服务端生成。"""

    model_config = ConfigDict(extra="forbid")

    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool = True


class LLMCompanionDialogueService:
    """用 Alice 的静态人设生成受 UE 表现目录约束的回复。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or create_llm_client()
        self._profile = _load_profile()

    def reply(self, request: CompanionDialogueRequest) -> CompanionDialogueResponse:
        allowed_emotions = _ids_from_profile(self._profile, "allowed_emotion_ids")
        allowed_gestures = _ids_from_profile(self._profile, "allowed_gesture_ids")
        allowed_faces = _ids_from_profile(self._profile, "allowed_facial_expression_ids")

        payload = self._client.generate_json(
            system_prompt=_build_system_prompt(
                self._profile,
                allowed_emotions=allowed_emotions,
                allowed_gestures=allowed_gestures,
                allowed_faces=allowed_faces,
            ),
            user_prompt=request.text,
        )

        try:
            response_payload = _DialoguePayload.model_validate(payload)
        except ValidationError as error:
            raise LLMClientError("LLM dialogue response does not match the required schema.") from error

        if response_payload.emotion_id not in allowed_emotions:
            raise LLMClientError("LLM returned an unknown emotion ID.")
        if response_payload.gesture_id not in allowed_gestures:
            raise LLMClientError("LLM returned an unknown gesture ID.")
        if response_payload.facial_expression_id not in allowed_faces:
            raise LLMClientError("LLM returned an unknown facial-expression ID.")

        return CompanionDialogueResponse(
            companion_id=request.companion_id,
            reply_text=response_payload.reply_text,
            emotion_id=response_payload.emotion_id,
            gesture_id=response_payload.gesture_id,
            facial_expression_id=response_payload.facial_expression_id,
            interruptible=response_payload.interruptible,
            source="llm",
        )


def _load_profile() -> dict[str, Any]:
    try:
        profile = yaml.safe_load(_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise LLMClientError("Unable to load the primary companion profile.") from error

    if not isinstance(profile, dict):
        raise LLMClientError("Primary companion profile must be a YAML mapping.")
    return profile


def _ids_from_profile(profile: dict[str, Any], key: str) -> set[str]:
    values = profile.get(key)
    if not isinstance(values, list):
        raise LLMClientError(f"Profile field '{key}' must be a list.")

    ids = {item.get("id") for item in values if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if not ids:
        raise LLMClientError(f"Profile field '{key}' contains no IDs.")
    return ids


def _build_system_prompt(
    profile: dict[str, Any],
    *,
    allowed_emotions: set[str],
    allowed_gestures: set[str],
    allowed_faces: set[str],
) -> str:
    identity = profile.get("identity", {})
    persona = profile.get("persona", {})
    speaking_style = profile.get("speaking_style", {})
    rules = profile.get("conversation_rules", {}).get("response_rules", [])

    return "\n".join(
        [
            "You are a non-combat game companion. Reply in Chinese.",
            f"Character: {identity.get('display_name', 'Alice')}.",
            f"Persona: {persona.get('background', '')}",
            f"Speaking style: {speaking_style.get('tone', '')}",
            "Response rules: " + " ".join(str(rule) for rule in rules),
            "Return only one JSON object with exactly these keys: reply_text, emotion_id, gesture_id, facial_expression_id, interruptible.",
            f"Allowed emotion_id values: {sorted(allowed_emotions)}.",
            f"Allowed gesture_id values: {sorted(allowed_gestures)}.",
            f"Allowed facial_expression_id values: {sorted(allowed_faces)}.",
            "Do not issue combat commands, describe game mechanics, or invent IDs.",
        ]
    )
