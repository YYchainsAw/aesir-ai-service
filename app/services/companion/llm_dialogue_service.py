"""使用共享 LLM 客户端生成非战斗陪伴对话。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import get_settings
from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.schemas.world_context import WorldContext
from app.services.llm.client import LLMClient, LLMClientError
from app.services.llm.factory import create_llm_client
from app.services.companion.profile_repository import CompanionProfile, get_profile
from app.services.companion.session_memory import DialogueTurn
from app.services.memory.retrieval import format_impression_block, format_memory_block
from app.schemas.memory import MemoryEntry, TopicImpression
from app.services.skills.tools import ToolResult, run_lookup, tool_menu
from app.services.tactical.policy import get_policy


# 事实条目长度上限：一句自足的中文陈述（超长说明模型在写小作文，丢弃）
_MAX_FACT_CHARS = 60


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
    """LLM 可输出的最小对话负载；封套字段由服务端生成。

    ``topics`` 为模糊印象层的主题提取（1~3 个玩家本轮谈及的关键词），
    ``facts`` 为长期档案的事实提取（玩家陈述过的、跨会话仍然成立的事），
    ``reply_topics`` 为她本轮自述主题（替代规则切词，见 ``_record_turn``），
    ``relationship_signal`` 为本轮对话的情感质量信号（对话推动关系用），
    均由 LLM 顺带返回，零额外请求。

    ``action`` 默认 ``reply``，老模型输出（不带该键）行为不变；只有
    ``lookup`` 才走查证分支（见 ``_lookup_request``）。
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["reply"] = "reply"
    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool = True
    topics: list[str] = Field(default_factory=list, max_length=3)
    facts: list[str] = Field(default_factory=list, max_length=3)
    reply_topics: list[str] = Field(default_factory=list, max_length=3)
    relationship_signal: Literal["none", "warm", "deep", "cold", "hurtful"] = "none"
    salient: bool = False

    @field_validator("facts")
    @classmethod
    def _clean_facts(cls, values: list[str]) -> list[str]:
        """清洗事实条目：去空白、丢空串与超长项。

        事实是「锦上添花」的旁路字段，**不因它报废整轮对话**——格式不合的
        条目直接丢弃，回复照常返回。写档案前的接地校验另在
        ``memory.facts.is_grounded``（防编造）。
        """
        cleaned: list[str] = []
        for value in values:
            text = value.strip()
            if text and len(text) <= _MAX_FACT_CHARS:
                cleaned.append(text)
        return cleaned


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
        # 最近一次成功生成提取的主题/事实/自述主题/关系信号/显著性（实例按请求创建，见 dialogue_service）。
        self.last_topics: list[str] = []
        self.last_facts: list[str] = []
        self.last_reply_topics: list[str] | None = None
        self.last_relationship_signal: str = "none"
        self.last_salient: bool = False

    def reply(
        self,
        request: CompanionDialogueRequest,
        *,
        history: tuple[DialogueTurn, ...] = (),
        memories: list[MemoryEntry] = (),
        impressions: list[TopicImpression] = (),
        relationship_stage: str = "",
        world_context: WorldContext | None = None,
    ) -> CompanionDialogueResponse:
        deadline = _lookup_deadline()
        payload = self._client.generate_json(
            system_prompt=_build_system_prompt(
                self._profile,
                history=history,
                memories=list(memories),
                impressions=list(impressions),
                relationship_stage=relationship_stage,
            ),
            user_prompt=request.text,
        )
        payload = self._verify_if_requested(
            payload, request=request, world_context=world_context, deadline=deadline,
            history=history, memories=memories, impressions=impressions,
            relationship_stage=relationship_stage,
        )

        try:
            response_payload = _validate_dialogue_payload(payload, self._profile)
        except ValidationError as error:
            raise LLMClientError("LLM dialogue response does not match the required schema.") from error
        self.last_topics = response_payload.topics
        self.last_facts = response_payload.facts
        self.last_reply_topics = response_payload.reply_topics
        self.last_relationship_signal = response_payload.relationship_signal
        self.last_salient = response_payload.salient

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

    def _verify_if_requested(
        self,
        payload: dict[str, Any],
        *,
        request: CompanionDialogueRequest,
        world_context: WorldContext | None,
        deadline: float,
        history: tuple[DialogueTurn, ...] = (),
        memories: list[MemoryEntry] = (),
        impressions: list[TopicImpression] = (),
        relationship_stage: str = "",
    ) -> dict[str, Any]:
        """第一轮若索取查证，执行只读查证并带着结果再生成一次（FR-036~FR-038）。

        上限 2 轮：第二轮若仍索取查证，说明模型在超限要求——宁可报错让上层
        回退候选回复，也不无限查下去（FR-038「超限后降级为直接回应」）。
        """
        lookup = _lookup_request(payload)
        if lookup is None:
            return payload

        result = run_lookup(
            lookup,
            companion_id=request.companion_id,
            world_context=world_context,
            deadline=deadline,
        )
        second = self._client.generate_json(
            system_prompt=_build_system_prompt(
                self._profile,
                history=history,
                memories=list(memories),
                impressions=list(impressions),
                relationship_stage=relationship_stage,
                lookup_result=result,
            ),
            user_prompt=request.text,
        )
        if _lookup_request(second) is not None:
            raise LLMClientError("LLM exceeded the lookup round limit.")
        return second

    def _stream_round(
        self, *, system_prompt: str, user_prompt: str
    ) -> Iterator[tuple[str, Any]]:
        """跑一轮流式生成：先逐段 yield ``("delta", 文本)``，最后 yield ``("payload", 解析结果)``。

        查证轮与正式回复轮共用本方法——两轮的唯一差别只有 system prompt。
        """
        extractor = _ReplyTextStreamExtractor()
        raw_content = ""
        for delta in self._client.stream_completion(
            system_prompt=system_prompt, user_prompt=user_prompt
        ):
            raw_content += delta
            new_text = extractor.feed(delta)
            if new_text:
                yield "delta", new_text
        yield "payload", _parse_json_object(raw_content)

    def stream_reply(
        self,
        request: CompanionDialogueRequest,
        *,
        history: tuple[DialogueTurn, ...] = (),
        memories: list[MemoryEntry] = (),
        impressions: list[TopicImpression] = (),
        relationship_stage: str = "",
        world_context: WorldContext | None = None,
    ) -> Iterator[StreamEvent]:
        """流式变体：先 yield delta（reply_text 增量），最后 yield meta。

        与 ``reply`` 共用同一 system prompt 与校验规则——流式只是传输层差异，
        不会改变回复内容。中途失败（LLMClientError）直接向上抛，由调用方
        按是否已发出 delta 决定回退或报错。

        查证轮是安全的：索取查证的负载里没有 ``reply_text``，抽取器一个字符
        都不会吐出去，因此换轮不会让玩家看到半截话。
        """
        deadline = _lookup_deadline()
        payload: dict[str, Any] = {}
        for kind, value in self._stream_round(
            system_prompt=_build_system_prompt(
                self._profile,
                history=history,
                memories=list(memories),
                impressions=list(impressions),
                relationship_stage=relationship_stage,
            ),
            user_prompt=request.text,
        ):
            if kind == "delta":
                yield StreamEvent(kind="delta", text=value)
            else:
                payload = value

        lookup = _lookup_request(payload)
        if lookup is not None:
            result = run_lookup(
                lookup,
                companion_id=request.companion_id,
                world_context=world_context,
                deadline=deadline,
            )
            for kind, value in self._stream_round(
                system_prompt=_build_system_prompt(
                    self._profile,
                    history=history,
                    memories=list(memories),
                    impressions=list(impressions),
                    relationship_stage=relationship_stage,
                    lookup_result=result,
                ),
                user_prompt=request.text,
            ):
                if kind == "delta":
                    yield StreamEvent(kind="delta", text=value)
                else:
                    payload = value
            if _lookup_request(payload) is not None:
                raise LLMClientError("LLM exceeded the lookup round limit.")

        try:
            response_payload = _validate_dialogue_payload(payload, self._profile)
        except ValidationError as error:
            raise LLMClientError("LLM dialogue response does not match the required schema.") from error
        self.last_topics = response_payload.topics
        self.last_facts = response_payload.facts
        self.last_reply_topics = response_payload.reply_topics
        self.last_relationship_signal = response_payload.relationship_signal
        self.last_salient = response_payload.salient

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


def _lookup_deadline() -> float:
    """本轮查证的时间预算终点（``time.monotonic()`` 口径，FR-038）。"""
    return time.monotonic() + get_settings().tools_lookup_timeout_seconds


def _parse_json_object(raw_content: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as error:
        raise LLMClientError("LLM streamed response is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise LLMClientError("LLM streamed response root must be a JSON object.")
    return payload


def _lookup_request(payload: dict[str, Any]) -> dict[str, Any] | None:
    """本轮输出是否在索取查证；不是则返回 ``None``（按普通回复处理）。

    配置关掉查证轮（``AESIR_TOOLS_MAX_ROUNDS < 2``）时一律视为普通回复，
    prompt 里也不会给工具清单——模型无从索取，也就不会索取。
    同时带 ``reply_text`` 的畸形负载交给 schema 校验去拒绝，避免流式路径
    已经吐出的半截话与查证轮重复。
    """
    if get_settings().tools_max_rounds < 2:
        return None
    if payload.get("action") != "lookup" or "reply_text" in payload:
        return None
    return payload


def _format_lookup_menu() -> str:
    """第一轮 prompt 里的工具清单：告诉模型「不确定就先查，别猜」。"""
    lines = [
        "Before answering, you may verify facts. If the player asks about the world, "
        "your own condition, the surroundings, or something you two talked about, and "
        "you are NOT certain, request one lookup instead of guessing.",
        'To do that, return exactly: {"action": "lookup", "tool": "<tool>", "query": "<what to look up>"}',
        "Available tools:",
    ]
    lines += [f"- {spec.name}: {spec.description}" for spec in tool_menu()]
    lines.append(
        'Otherwise answer normally and include "action": "reply" in your JSON.'
    )
    return "\n".join(lines)


def _format_lookup_result(result: ToolResult) -> str:
    """第二轮 prompt 里的查证回填块。

    未命中时明确要求「说不确定」，因为编造最容易发生在「查了但没查到」
    这个当口——模型此时有强烈的把话说圆的本能（FR-037）。
    """
    if result.found:
        return (
            "Verification result for your lookup (authoritative; use ONLY this, "
            "do not add facts beyond it):\n"
            f"{result.content}\n"
            "Now answer the player, staying in character."
        )
    return (
        "Verification result for your lookup:\n"
        f"{result.content}\n"
        "Nothing reliable was found. Tell the player plainly that you do not know or "
        "cannot confirm it — do NOT invent any fact. Now answer, staying in character."
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
    impressions: list[TopicImpression] | None = None,
    relationship_stage: str = "",
    lookup_result: ToolResult | None = None,
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
        stage_persona = stage_personas[relationship_stage]
        lines.append(
            f"Current relationship stage: {relationship_stage} "
            f"(address the player as: {stage_persona.get('address', '')}). "
            f"Stage tone shift: {stage_persona.get('tone_shift', '')}"
        )
        # 阶段硬边界（2026-09-21 实测复盘）：只偏移语气时，基础人设的「暗藏情愫」
        # 照常生效，于是出现「一边叫旅行者、一边聊两人合披一块油布」的割裂。
        boundary = stage_persona.get("boundary", "")
        if boundary:
            lines.append(
                "Stage hard boundary (when it conflicts with the base persona's "
                f"subtext or behavior rules, THIS wins): {boundary}"
            )
    lines.append(f"Speaking habits: {' '.join(str(h) for h in speaking_style.get('habits', []))}")
    lines.append(f"Speaking avoid: {' '.join(str(a) for a in speaking_style.get('avoid', []))}")
    lines.append("Response rules: " + " ".join(str(rule) for rule in rules))

    # 能力目录注入（2026-09-22 实测复盘「水系魔法幻视」）：对话链路此前完全不
    # 引用能力清单，被问「你会什么魔法」时只能现编且越编越自洽。真相源是
    # tactical_policy 的 abilities（注册表投影会丢 display_name，故直接取
    # policy）——单份配置，对话与战斗不会漂移。策略层故障时静默不注入，
    # 对话不中断（FR-041 同纪律）。
    try:
        abilities = list(get_policy().abilities.values())
        if abilities:
            catalog = "、".join(
                f"{ability.display_name}（{ability.description}）" for ability in abilities
            )
            lines.append(
                f"Your complete and ONLY abilities: {catalog}. "
                "You know no other spells; do not invent abilities you were not given. "
                "If asked about magic outside this list, say plainly you cannot do it."
            )
    except Exception:  # pragma: no cover - 配置损坏时对话不陪葬
        pass

    if memories:
        lines.append(format_memory_block(memories, display_name=profile.display_name))

    if impressions:
        lines.append(format_impression_block(impressions, display_name=profile.display_name))

    if history:
        lines.append(
            "Recent conversation with the player (oldest first; continue naturally "
            "from it, do not repeat yourself):\n"
            + "\n".join(f"Player: {t.user_text}\n{profile.display_name}: {t.reply_text}" for t in history)
        )
        lines.append(
            "Anti-repetition: do NOT reuse sentence structures, catchphrases, or "
            "openings from the recent turns above (e.g. the same '...' + '不过' "
            "pattern); vary your phrasing, length, and rhythm each turn. Also "
            "vary gesture_id / facial_expression_id choices instead of defaulting "
            "to the same ones — but NOT emotion_id (see mood continuity below)."
        )
        # 情绪惯性（2026-09-21 实测复盘）：上一版 Anti-repetition 要求情绪也轮换，
        # 模型于是每轮重挑一个，出现无来由的情绪跳变与回摆。心情该延续，不是抽签。
        mood = history[-1].emotion_id
        if mood:
            lines.append(
                f"Your current mood: {mood} — the emotion you were left with after "
                "your last reply. Feelings have inertia: keep this mood unless the "
                "player's message genuinely changes the situation (a joke lands, "
                "something worrying, sad, or exciting comes up). Do NOT switch it "
                "just to look varied."
            )

    # 事实诚实（实测 2026-09-21「烤鱼幻视」）：无论有没有会话历史都必须遵守——
    # 首轮没有历史时模型最容易把假设当既定事实编圆。六修（2026-09-22）把覆盖面
    # 从「过去事件」扩到四类：实测她还现编了天气（世界状态）与「才几天不见」
    # （相处时长）。涉及这四类，没有依据就必须不确定或反问，绝不用确定语气补细节。
    lines.append(
        "Memory honesty: everything you know about the past is ONLY the recent "
        "conversation, the long-term memories, and the fuzzy impressions shown "
        "above (fuzzy impressions are topic-level only — they contain no facts). "
        "State a long-term memory plainly when it is relevant — that is what it is "
        "for — but NEVER add details beyond it. This honesty rule covers four areas, "
        "and in all of them no record means uncertain: (1) past events — NEVER assert "
        "any other specific past event (something was eaten, done, said, or promised) "
        "unless it appears in the records above; (2) current world state — weather, "
        "surroundings, other people — trust ONLY a verification result or world "
        "snapshot when one is given, otherwise admit you cannot tell; (3) your own "
        "abilities — trust ONLY the ability list above, never a spell outside it; "
        "(4) how long you have known the player or how long since you last met — "
        "you have no clock and no record, so NEVER say things like \"才几天不见\". "
        "If the player asks about something you have no record of, express "
        "uncertainty or ask them back — never fill in details with a confident tone."
    )

    examples = _format_dialogue_examples(profile)
    if examples:
        lines.append(
            "Example exchanges (match this pattern of matching reply style and emotion "
            "to the type of player input; do not reuse the literal sentences). Any "
            "world details in them (names, places, objects, events, weather) are "
            "placeholders, NOT facts — never cite anything from an example as "
            "something that actually happened:\n" + examples
        )

    # 查证（US6 / T069）：第一轮给工具清单，第二轮把结果回填并要求据此作答。
    if lookup_result is not None:
        lines.append(_format_lookup_result(lookup_result))
    elif get_settings().tools_max_rounds >= 2:
        lines.append(_format_lookup_menu())

    lines += [
        "Return only one JSON object with exactly these keys: action, reply_text, emotion_id, gesture_id, facial_expression_id, interruptible, topics, facts, reply_topics, relationship_signal, salient.",
        'relationship_signal: rate the EMOTIONAL QUALITY of what the PLAYER said in this '
        'message — not your own tone. "warm" if they showed genuine care, gratitude, or '
        'friendly warmth; "deep" if they solemnly opened up, entrusted something to you, '
        'apologized, or expressed real feeling; "cold" if they were dismissive, impatient, '
        'or brushed you off; "hurtful" if they maliciously belittled, threatened, or '
        'deliberately hurt you. "none" for ordinary conversation — the vast majority of '
        'turns MUST be "none"; when in doubt, choose "none" (a missed signal costs far '
        'less than a wrong one, because it moves a persistent relationship score).',
        'reply_topics: list of 1-3 short Chinese topic words (2-6 chars, concrete nouns '
        'only) that YOUR OWN reply this turn actually talked about; empty list if your '
        'reply had no concrete topic. These become fuzzy impressions of what you care '
        'to mention, so keep them clean — no fillers, no verb or adjective fragments '
        '(like 主修/厉害/代价/不小), no whole phrases.',
        'topics: list of 1-3 short Chinese keywords the PLAYER talked about in this message '
        '(things worth remembering about them, not your own reply); each keyword must be a '
        'concrete noun or topic word (2-6 chars), never connectives, fillers, or fragments '
        'like 不过/然后/意思; empty list if nothing salient.',
        'facts: list of 0-3 durable facts about the PLAYER that you learned from what the '
        'player actually said (in this message or in the recent conversation above): who they '
        'are, their background, family, pets, home, work, strong likes and dislikes, plans, '
        'or promises they made. Each fact must be a self-contained Chinese sentence in the '
        'third person, at most 40 characters, e.g. "玩家养了一只叫小黑的猫" or "玩家最讨厌蘑菇". '
        'Only include what the player stated — NEVER your own words, your guesses, or any '
        'detail you invented; empty list if the player only made small talk. These facts are '
        'stored and reused later, so a wrong one becomes a permanent false memory.',
        'salient: true only if the player solemnly declares something important about themselves '
        'and clearly wants it remembered (e.g. "记住：...", "有件重要的事情告诉你", promises, '
        'strong likes/dislikes); false for ordinary chat.',
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
