"""从主队友 YAML 读取并校验静态人设资料。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PRIMARY_PROFILE_PATH = Path(__file__).resolve().parents[3] / "data" / "companions" / "primary_companion.yaml"


class CompanionProfileError(RuntimeError):
    """角色资料缺失或不符合配置契约。"""


class UnknownCompanionError(CompanionProfileError):
    """调用方请求的队友 ID 不属于已登记的主队友。"""


@dataclass(frozen=True)
class DialoguePresentation:
    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool


@dataclass(frozen=True)
class CompanionProfile:
    """从 YAML 提取出的、聊天服务所需的已校验人设快照。"""

    companion_id: str
    display_name: str
    raw: dict[str, Any]
    allowed_emotion_ids: frozenset[str]
    allowed_gesture_ids: frozenset[str]
    allowed_facial_expression_ids: frozenset[str]
    default_dialogue_response: DialoguePresentation


class CompanionProfileRepository:
    """每次读取 YAML，确保人设资料是聊天服务的唯一静态来源。"""

    def __init__(self, profile_path: Path = _PRIMARY_PROFILE_PATH) -> None:
        self._profile_path = profile_path

    def load_primary(self) -> CompanionProfile:
        try:
            raw_profile = yaml.safe_load(self._profile_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise CompanionProfileError("Unable to load the primary companion profile.") from error

        if not isinstance(raw_profile, dict):
            raise CompanionProfileError("Primary companion profile must be a YAML mapping.")

        identity = _required_mapping(raw_profile, "identity")
        companion_id = _required_string(identity, "id")
        display_name = _required_string(identity, "display_name")
        allowed_emotions = _id_set(raw_profile, "allowed_emotion_ids")
        allowed_gestures = _id_set(raw_profile, "allowed_gesture_ids")
        allowed_faces = _id_set(raw_profile, "allowed_facial_expression_ids")
        default_response = _default_response(raw_profile)

        if default_response.emotion_id not in allowed_emotions:
            raise CompanionProfileError("Default dialogue emotion ID is not registered in the profile.")
        if default_response.gesture_id not in allowed_gestures:
            raise CompanionProfileError("Default dialogue gesture ID is not registered in the profile.")
        if default_response.facial_expression_id not in allowed_faces:
            raise CompanionProfileError("Default dialogue facial-expression ID is not registered in the profile.")

        return CompanionProfile(
            companion_id=companion_id,
            display_name=display_name,
            raw=raw_profile,
            allowed_emotion_ids=frozenset(allowed_emotions),
            allowed_gesture_ids=frozenset(allowed_gestures),
            allowed_facial_expression_ids=frozenset(allowed_faces),
            default_dialogue_response=default_response,
        )

    def require_primary(self, companion_id: str) -> CompanionProfile:
        profile = self.load_primary()
        if companion_id != profile.companion_id:
            raise UnknownCompanionError(f"Unsupported companion_id: {companion_id}")
        return profile


def _required_mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise CompanionProfileError(f"Profile field '{key}' must be a mapping.")
    return value


def _required_string(container: dict[str, Any], key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CompanionProfileError(f"Profile field '{key}' must be a non-empty string.")
    return value


def _id_set(profile: dict[str, Any], key: str) -> set[str]:
    values = profile.get(key)
    if not isinstance(values, list):
        raise CompanionProfileError(f"Profile field '{key}' must be a list.")

    ids = {
        item.get("id")
        for item in values
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    }
    if not ids:
        raise CompanionProfileError(f"Profile field '{key}' contains no IDs.")
    return ids


def _default_response(profile: dict[str, Any]) -> DialoguePresentation:
    defaults = _required_mapping(profile, "default_dialogue_response")
    return DialoguePresentation(
        reply_text=_required_string(defaults, "reply_text"),
        emotion_id=_required_string(defaults, "emotion_id"),
        gesture_id=_required_string(defaults, "gesture_id"),
        facial_expression_id=_required_string(defaults, "facial_expression_id"),
        interruptible=defaults.get("interruptible", True),
    )
