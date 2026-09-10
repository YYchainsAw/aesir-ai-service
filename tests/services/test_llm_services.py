from typing import Any

import pytest

from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
from app.services.llm.client import LLMClientError
from app.services.parsers.llm import LLMCommandParser


class StubLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
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


def test_companion_llm_prompt_injects_full_persona_and_examples() -> None:
    """方案 A 回归：prompt 必须包含人设全量字段与 few-shot 示例。"""
    stub = StubLLMClient(
        {
            "reply_text": "好呀。",
            "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle",
            "facial_expression_id": "face.bright_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="聊点什么吧"))

    prompt = stub.system_prompt
    assert "lightly_tsundere" in prompt                      # core_traits
    assert "Relationship subtext" in prompt                   # relationship_to_player.subtext
    assert "Speaking habits" in prompt                        # habits
    assert "Speaking avoid" in prompt                          # avoid
    assert "[praised] Player:" in prompt                       # dialogue_examples few-shot
    assert "emotion.shy" in prompt


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
