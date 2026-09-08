from typing import Any

import pytest

from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
from app.services.llm.client import LLMClientError
from app.services.parsers.llm import LLMCommandParser


class StubLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        return self.payload


def test_companion_llm_service_validates_and_returns_ue_ids() -> None:
    service = LLMCompanionDialogueService(
        StubLLMClient(
            {
                "reply_text": "当然可以，和你一起出发总不会无聊。",
                "emotion_id": "emotion.pleased",
                "gesture_id": "gesture.enthusiastic_nod",
                "facial_expression_id": "face.gentle_smile",
                "interruptible": True,
            }
        )
    )

    response = service.reply(CompanionDialogueRequest(text="我们出发吧。"))

    assert response.source == "llm"
    assert response.companion_id == "companion.alice"
    assert response.emotion_id == "emotion.pleased"


def test_companion_llm_service_rejects_unknown_ue_id() -> None:
    service = LLMCompanionDialogueService(
        StubLLMClient(
            {
                "reply_text": "这可不是我会用的表情。",
                "emotion_id": "emotion.not_registered",
                "gesture_id": "gesture.cheerful_idle",
                "facial_expression_id": "face.bright_smile",
                "interruptible": True,
            }
        )
    )

    with pytest.raises(LLMClientError, match="unknown emotion ID"):
        service.reply(CompanionDialogueRequest(text="测试"))


def test_tactical_llm_parser_rejects_extra_fields() -> None:
    parser = LLMCommandParser(
        StubLLMClient(
            {
                "recognized": False,
                "order": None,
                "message": "Unknown command.",
                "unsafe_extra": "must be rejected",
            }
        )
    )

    with pytest.raises(LLMClientError, match="failed validation"):
        parser.parse("做一个不存在的动作")


def test_tactical_llm_parser_marks_its_own_source() -> None:
    parser = LLMCommandParser(
        StubLLMClient(
            {
                "recognized": False,
                "order": None,
                "message": "Unknown command.",
            }
        )
    )

    response = parser.parse("做一个不存在的动作")

    assert response.source == "llm"
