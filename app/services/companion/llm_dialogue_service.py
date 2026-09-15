"""使用共享 LLM 客户端生成非战斗陪伴对话。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.services.llm.client import LLMClient, LLMClientError
from app.services.llm.factory import create_llm_client
from app.services.companion.profile_repository import CompanionProfile, get_profile
from app.services.companion.session_memory import DialogueTurn
from app.services.memory.retrieval import format_memory_block
from app.schemas.memory import MemoryEntry


@dataclass(frozen=True)
class StreamEvent:
    """流式对话事件：delta 携带文本增量，meta 携带权威完整响应。"""

    kind: Literal["delta", "meta", "error"]
    text: str = ""
    response: CompanionDialogueResponse | None = None


class _ReplyTextStreamExtractor:
    """从部分 JSON 中增量抽取 ``reply_text`` 字符串值。

    每次用累积缓冲从头重解码（缓冲只有一条回复，代价可忽略），
    只把比上次多出的后缀作为新增量返回——这天然处理了转义序列
    跨 chunk 分割（尾部不完整转义先不输出，等下一块补齐）。
    """

    _KEY = '"reply_text"'

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted_len = 0

    def feed(self, delta: str) -> str:
        self._buffer += delta
        decoded = self._decode()
        new_text = decoded[self._emitted_len :]
        self._emitted_len = len(decoded)
        return new_text

    def _decode(self) -> str:
        """解码当前缓冲中 reply_text 的已确定前缀；未定位到键则返回空串。"""
        key_at = self._buffer.find(self._KEY)
        if key_at < 0:
            return ""
        position = key_at + len(self._KEY)
        # 跳过键与值之间的空白和冒号。
        while position < len(self._buffer) and self._buffer[position] in " \t\r\n":
            position += 1
        if position >= len(self._buffer) or self._buffer[position] != ":":
            return ""
        position += 1
        while position < len(self._buffer) and self._buffer[position] in " \t\r\n":
            position += 1
        if position >= len(self._buffer) or self._buffer[position] != '"':
            return ""
        position += 1

        out: list[str] = []
        while position < len(self._buffer):
            char = self._buffer[position]
            if char == '"':  # 值结束
                return "".join(out)
            if char != "\\":
                out.append(char)
                position += 1
                continue
            # 转义序列：缓冲不足以完整判断时停在前缀，等下一次 feed。
            if position + 1 >= len(self._buffer):
                break
            escaped = self._buffer[position + 1]
            if escaped == "u":
                hex_digits = self._buffer[position + 2 : position + 6]
                if len(hex_digits) < 4:  # 转义跨 chunk 分割，等下一块补齐
                    break
                try:
                    out.append(chr(int(hex_digits, 16)))
                except ValueError:
                    raise LLMClientError("LLM streamed an invalid \\u escape in reply_text.") from None
                position += 6
                continue
            simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
            if escaped not in simple:
                raise LLMClientError("LLM streamed an unknown escape in reply_text.")
            out.append(simple[escaped])
            position += 2
        return "".join(out)


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

    def reply(
        self,
        request: CompanionDialogueRequest,
        *,
        history: tuple[DialogueTurn, ...] = (),
        memories: list[MemoryEntry] = (),
        relationship_stage: str = "",
    ) -> CompanionDialogueResponse:
        payload = self._client.generate_json(
            system_prompt=_build_system_prompt(
                self._profile,
                history=history,
                memories=list(memories),
                relationship_stage=relationship_stage,
            ),
            user_prompt=request.text,
        )

        try:
            response_payload = _validate_dialogue_payload(payload, self._profile)
        except ValidationError as error:
            raise LLMClientError("LLM dialogue response does not match the required schema.") from error

        return CompanionDialogueResponse(
            companion_id=request.companion_id,
            session_id=request.session_id,
            reply_text=response_payload.reply_text,
            emotion_id=response_payload.emotion_id,
            gesture_id=response_payload.gesture_id,
            facial_expression_id=response_payload.facial_expression_id,
            interruptible=response_payload.interruptible,
            source="llm",
        )

    def stream_reply(
        self,
        request: CompanionDialogueRequest,
        *,
        history: tuple[DialogueTurn, ...] = (),
        memories: list[MemoryEntry] = (),
        relationship_stage: str = "",
    ) -> Iterator[StreamEvent]:
        """流式变体：先 yield delta（reply_text 增量），最后 yield meta。

        与 ``reply`` 共用同一 system prompt 与校验规则——流式只是传输层差异，
        不会改变回复内容。中途失败（LLMClientError）直接向上抛，由调用方
        按是否已发出 delta 决定回退或报错。
        """
        extractor = _ReplyTextStreamExtractor()
        raw_content = ""
        for delta in self._client.stream_completion(
            system_prompt=_build_system_prompt(
                self._profile,
                history=history,
                memories=list(memories),
                relationship_stage=relationship_stage,
            ),
            user_prompt=request.text,
        ):
            raw_content += delta
            new_text = extractor.feed(delta)
            if new_text:
                yield StreamEvent(kind="delta", text=new_text)

        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError as error:
            raise LLMClientError("LLM streamed response is not valid JSON.") from error
        if not isinstance(payload, dict):
            raise LLMClientError("LLM streamed response root must be a JSON object.")

        try:
            response_payload = _validate_dialogue_payload(payload, self._profile)
        except ValidationError as error:
            raise LLMClientError("LLM dialogue response does not match the required schema.") from error

        yield StreamEvent(
            kind="meta",
            response=CompanionDialogueResponse(
                companion_id=request.companion_id,
                session_id=request.session_id,
                reply_text=response_payload.reply_text,
                emotion_id=response_payload.emotion_id,
                gesture_id=response_payload.gesture_id,
                facial_expression_id=response_payload.facial_expression_id,
                interruptible=response_payload.interruptible,
                source="llm",
            ),
        )


def _validate_dialogue_payload(payload: dict, profile: CompanionProfile) -> "_DialoguePayload":
    """校验 LLM 对话负载：schema + 情绪/手势/表情白名单（reply 与 stream_reply 共用）。"""
    response_payload = _DialoguePayload.model_validate(payload)

    if response_payload.emotion_id not in profile.allowed_emotion_ids:
        raise LLMClientError("LLM returned an unknown emotion ID.")
    if response_payload.gesture_id not in profile.allowed_gesture_ids:
        raise LLMClientError("LLM returned an unknown gesture ID.")
    if response_payload.facial_expression_id not in profile.allowed_facial_expression_ids:
        raise LLMClientError("LLM returned an unknown facial-expression ID.")
    return response_payload


def _build_system_prompt(
    profile: CompanionProfile,
    *,
    history: tuple[DialogueTurn, ...] = (),
    memories: list[MemoryEntry] | None = None,
    relationship_stage: str = "",
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

    # 关系阶段化人设偏移（US2 / T040）：覆盖称呼与语气；缺失阶段沿用基线
    stage_personas = profile.raw.get("relationship_stage_personas", {})
    if relationship_stage and relationship_stage in stage_personas:
        persona = stage_personas[relationship_stage]
        lines.append(
            f"Current relationship stage: {relationship_stage} "
            f"(address the player as: {persona.get('address', '')}). "
            f"Stage tone shift: {persona.get('tone_shift', '')}"
        )
    lines.append(f"Speaking habits: {' '.join(str(h) for h in speaking_style.get('habits', []))}")
    lines.append(f"Speaking avoid: {' '.join(str(a) for a in speaking_style.get('avoid', []))}")
    lines.append("Response rules: " + " ".join(str(rule) for rule in rules))

    if memories:
        lines.append(format_memory_block(memories, display_name=profile.display_name))

    if history:
        lines.append(
            "Recent conversation with the player (oldest first; continue naturally "
            "from it, do not repeat yourself):\n"
            + "\n".join(f"Player: {t.user_text}\n{profile.display_name}: {t.reply_text}" for t in history)
        )

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
