"""使用共享 LLM 客户端生成非战斗陪伴对话。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.services.llm.client import LLMClient, LLMClientError
from app.services.llm.factory import create_llm_client
from app.services.companion.profile_repository import CompanionProfile, get_profile


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

    def __init__(
        self,
        client: LLMClient | None = None,
        *,
        profile: CompanionProfile | None = None,
    ) -> None:
        self._client = client or create_llm_client()
        self._profile = profile or get_profile()

    def reply(self, request: CompanionDialogueRequest) -> CompanionDialogueResponse:
        payload = self._client.generate_json(
            system_prompt=_build_system_prompt(
                self._profile,
            ),
            user_prompt=request.text,
        )

        try:
            response_payload = _DialoguePayload.model_validate(payload)
        except ValidationError as error:
            raise LLMClientError("LLM dialogue response does not match the required schema.") from error

        if response_payload.emotion_id not in self._profile.allowed_emotion_ids:
            raise LLMClientError("LLM returned an unknown emotion ID.")
        if response_payload.gesture_id not in self._profile.allowed_gesture_ids:
            raise LLMClientError("LLM returned an unknown gesture ID.")
        if response_payload.facial_expression_id not in self._profile.allowed_facial_expression_ids:
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


def _build_system_prompt(
    profile: CompanionProfile,
) -> str:
    identity = profile.raw.get("identity", {})
    persona = profile.raw.get("persona", {})
    speaking_style = profile.raw.get("speaking_style", {})
    rules = profile.raw.get("conversation_rules", {}).get("response_rules", [])

    lines = [
        "You are a non-combat game companion. Reply in Chinese.",
        f"Character: {profile.display_name}.",
        f"Short description: {identity.get('short_description', '')}",
        f"Persona: {persona.get('background', '')}",
        f"Core traits: {', '.join(str(t) for t in persona.get('core_traits', []))}.",
        f"Values: {', '.join(str(v) for v in persona.get('values', []))}.",
        f"Dislikes: {', '.join(str(d) for d in persona.get('dislikes', []))}.",
    ]

    relationship = persona.get("relationship_to_player", {})
    if relationship:
        lines.append(f"Relationship surface: {relationship.get('surface', '')}")
        lines.append(f"Relationship subtext: {relationship.get('subtext', '')}")
        lines.append(
            "Relationship behavior rules: " + " ".join(str(r) for r in relationship.get("behavior_rules", []))
        )

    lines.append(f"Speaking tone: {speaking_style.get('tone', '')}")
    lines.append(f"Speaking habits: {' '.join(str(h) for h in speaking_style.get('habits', []))}")
    lines.append(f"Speaking avoid: {' '.join(str(a) for a in speaking_style.get('avoid', []))}")
    lines.append("Response rules: " + " ".join(str(rule) for rule in rules))

    examples = _format_dialogue_examples(profile)
    if examples:
        lines.append(
            "Example exchanges (match this pattern of matching reply style and emotion "
            "to the type of player input; do not reuse the literal sentences):\n" + examples
        )

    lines += [
        "Return only one JSON object with exactly these keys: reply_text, emotion_id, gesture_id, facial_expression_id, interruptible.",
        f"Allowed emotion_id values: {sorted(profile.allowed_emotion_ids)}.",
        f"Allowed gesture_id values: {sorted(profile.allowed_gesture_ids)}.",
        f"Allowed facial_expression_id values: {sorted(profile.allowed_facial_expression_ids)}.",
        "Do not issue combat commands, describe game mechanics, or invent IDs.",
    ]
    return "\n".join(lines)


def _format_dialogue_examples(profile: CompanionProfile) -> str:
    """把 YAML few-shot 样例格式化为示范对话块。"""
    blocks = []
    for example in profile.dialogue_examples:
        presentation = example.presentation
        blocks.append(
            f"[{example.category}] Player: {example.player}\n"
            f"{profile.display_name}: {presentation.reply_text} "
            f"(emotion={presentation.emotion_id}, gesture={presentation.gesture_id}, "
            f"face={presentation.facial_expression_id})"
        )
    return "\n".join(blocks)
