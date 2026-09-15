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


def test_companion_llm_prompt_injects_conversation_history() -> None:
    """方案 B 回归：session 历史以对话块形式进入系统提示。"""
    from app.services.companion.session_memory import DialogueTurn

    stub = StubLLMClient(
        {
            "reply_text": "那就接着说。",
            "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle",
            "facial_expression_id": "face.bright_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(
        CompanionDialogueRequest(text="刚说到哪了？", session_id="s1"),
        history=(DialogueTurn(user_text="我们出发吧。", reply_text="当然可以。"),),
    )

    prompt = stub.system_prompt
    assert "Recent conversation" in prompt
    assert "Player: 我们出发吧。" in prompt
    assert "Alice: 当然可以。" in prompt
    assert stub.user_prompt == "刚说到哪了？"


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


class StubStreamingLLMClient:
    """按预定 chunk 列表产出原始文本增量的流式测试替身。"""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        raise AssertionError("stream_reply must not call generate_json")

    def stream_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ):
        yield from self._chunks


_FULL_STREAM_REPLY = (
    '{"reply_text": "好呀，那就走吧。", '
    '"emotion_id": "emotion.bright", '
    '"gesture_id": "gesture.cheerful_idle", '
    '"facial_expression_id": "face.bright_smile", '
    '"interruptible": true}'
)


def _split_mid_word(text: str, parts: int) -> list[str]:
    size = max(1, len(text) // parts)
    return [text[i : i + size] for i in range(0, len(text), size)]


def test_stream_reply_emits_deltas_then_meta() -> None:
    service = LLMCompanionDialogueService(StubStreamingLLMClient(_split_mid_word(_FULL_STREAM_REPLY, 7)))

    events = list(
        service.stream_reply(CompanionDialogueRequest(text="我们出发吧。", session_id="s1"))
    )

    deltas = [e for e in events if e.kind == "delta"]
    metas = [e for e in events if e.kind == "meta"]
    assert "".join(e.text for e in deltas) == "好呀，那就走吧。"
    assert len(metas) == 1
    assert metas[0].response is not None
    assert metas[0].response.reply_text == "好呀，那就走吧。"
    assert metas[0].response.source == "llm"
    assert metas[0].response.session_id == "s1"
    assert all(e.kind != "error" for e in events)


def test_stream_reply_decodes_escapes_across_chunks() -> None:
    r"""转义序列（\n、\uXXXX）被 chunk 边界切断时也能正确拼出 delta。"""
    chunks = [
        '{"reply_text": "第一行',
        '\\n',
        '第二行 \\u',
        '4e2d',
        '弹"',
        ', "emotion_id": "emotion.bright", "gesture_id": "gesture.cheerful_idle", '
        '"facial_expression_id": "face.bright_smile", "interruptible": true}',
    ]
    service = LLMCompanionDialogueService(StubStreamingLLMClient(chunks))

    events = list(service.stream_reply(CompanionDialogueRequest(text="测试")))

    joined = "".join(e.text for e in events if e.kind == "delta")
    assert joined == "第一行\n第二行 中弹"
    meta = next(e for e in events if e.kind == "meta")
    assert meta.response is not None
    assert meta.response.reply_text == "第一行\n第二行 中弹"


def test_stream_reply_rejects_unknown_ue_id_after_stream() -> None:
    payload = _FULL_STREAM_REPLY.replace("emotion.bright", "emotion.not_registered")
    service = LLMCompanionDialogueService(StubStreamingLLMClient([payload]))

    with pytest.raises(LLMClientError, match="unknown emotion ID"):
        list(service.stream_reply(CompanionDialogueRequest(text="测试")))


def test_stream_reply_rejects_invalid_json() -> None:
    service = LLMCompanionDialogueService(StubStreamingLLMClient(["不是 JSON"]))

    with pytest.raises(LLMClientError, match="not valid JSON"):
        list(service.stream_reply(CompanionDialogueRequest(text="测试")))
