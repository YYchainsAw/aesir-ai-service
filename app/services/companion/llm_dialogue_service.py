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
from app.services.llm.untrusted_input import untrusted_input_notice, wrap_untrusted_input
from app.services.companion.profile_repository import CompanionProfile, get_profile
from app.services.companion.session_memory import DialogueTurn
from app.services.companion import style_guard
from app.schemas.memory import MemoryEntry, TopicImpression
from app.services.skills.tools import ToolResult, run_lookup, tool_menu
from app.services.companion.prompt_builder import _build_system_prompt


# 事实条目长度上限：一句自足的中文陈述（超长说明模型在写小作文，丢弃）
_MAX_FACT_CHARS = 60


def _violation_snapshot(violation: style_guard.StyleViolation) -> dict:
    """StyleViolation → 可落盘 dict（埋点/回归报告按 category/matched_term 计数）。"""
    return {
        "category": violation.category,
        "matched_term": violation.matched_term,
        "message": violation.message,
    }


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
    # 玩家改口时被纠正的旧事实短 ID 列表（来自 long-term memories 块里的 [ID:xxxxxxxx]）。
    # #101 实测：让 LLM 照抄旧事实原文再走 dedup_key 匹配失败率高（LLM 会换
    # 标点/同义词），改成让它直接回传 ID，匹配零措辞依赖。
    corrected_fact_ids: list[str] = Field(default_factory=list, max_length=3)
    reply_topics: list[str] = Field(default_factory=list, max_length=3)
    relationship_signal: Literal["none", "warm", "deep", "cold", "hurtful"] = "none"
    salient: bool = False

    @field_validator("facts", "corrected_fact_ids")
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
        self.last_corrected_fact_ids: list[str] = []
        self.last_reply_topics: list[str] | None = None
        self.last_relationship_signal: str = "none"
        self.last_salient: bool = False
        # T083 风格校验：成功时为空列表；拦截时为违规快照 dict（#110）——
        # 非流式回退轮与流式 error 帧轮都靠它把拦截事件透传给埋点落盘。
        self.last_style_violations: list[dict] = []
        # T38 / SC-008：最近一轮查证的 ToolResult（无查证轮为 None）。
        # 原先用完即弃（只进第二轮 prompt），现在透传给埋点落盘。
        self.last_lookup: ToolResult | None = None

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
        response_payload = self._generate_payload_with_retry(
            request,
            history=history,
            memories=memories,
            impressions=impressions,
            relationship_stage=relationship_stage,
            world_context=world_context,
        )
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

    def _generate_payload_with_retry(
        self,
        request: CompanionDialogueRequest,
        *,
        history: tuple[DialogueTurn, ...],
        memories: list[MemoryEntry],
        impressions: list[TopicImpression],
        relationship_stage: str,
        world_context: WorldContext | None,
    ) -> "_DialoguePayload":
        """内部完整生成一轮回复：schema 校验 + style_guard + 查证轮；最多重试 1 次。

        重试机制（T083）：LLM 首次输出风格违规时，用同一份 system prompt
        重新生成一次；若第二次仍违规，抛 LLMClientError，由 dialogue_service
        回退到 mock/安全候选。
        """
        deadline = _lookup_deadline()
        last_violations: list[style_guard.StyleViolation] = []

        for attempt in range(2):
            payload = self._client.generate_json(
                system_prompt=_build_system_prompt(
                    self._profile,
                    history=history,
                    memories=list(memories),
                    impressions=list(impressions),
                    relationship_stage=relationship_stage,
                ),
                user_prompt=wrap_untrusted_input(request.text),
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

            violations = style_guard.check_reply(
                response_payload.reply_text,
                injected_memories=memories or None,
                injected_impressions=impressions or None,
            )
            if not violations:
                self.last_topics = response_payload.topics
                self.last_facts = response_payload.facts
                self.last_corrected_fact_ids = response_payload.corrected_fact_ids
                self.last_reply_topics = response_payload.reply_topics
                self.last_relationship_signal = response_payload.relationship_signal
                self.last_salient = response_payload.salient
                self.last_style_violations = []
                return response_payload

            last_violations = violations
            # #110：失败轮也把违规快照留给上层——否则回退 mock 后落盘的
            # style_violations 仍是初始空列表，拦截轮与干净通过无法区分。
            self.last_style_violations = [_violation_snapshot(v) for v in violations]

        # 两次尝试均失败：把违规原因带给上层日志/观测。
        detail = "; ".join(f"{v.category}: {v.message}" for v in last_violations)
        raise LLMClientError(f"LLM dialogue response failed style guard after retry: {detail}")

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
            game_id=self._profile.game_name.lower(),
            world_context=world_context,
            deadline=deadline,
        )
        self.last_lookup = result  # T38 / SC-008：透传埋点
        second = self._client.generate_json(
            system_prompt=_build_system_prompt(
                self._profile,
                history=history,
                memories=list(memories),
                impressions=list(impressions),
                relationship_stage=relationship_stage,
                lookup_result=result,
            ),
            user_prompt=wrap_untrusted_input(request.text),
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

        风格校验在完整流接收后进行：若发现违规，已发出的 delta 无法收回，
        只能向上抛异常，由 dialogue_service 在 SSE 中发出 error 事件并停止。
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
            user_prompt=wrap_untrusted_input(request.text),
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
                game_id=self._profile.game_name.lower(),
                world_context=world_context,
                deadline=deadline,
            )
            self.last_lookup = result  # T38 / SC-008：透传埋点
            for kind, value in self._stream_round(
                system_prompt=_build_system_prompt(
                    self._profile,
                    history=history,
                    memories=list(memories),
                    impressions=list(impressions),
                    relationship_stage=relationship_stage,
                    lookup_result=result,
                ),
                user_prompt=wrap_untrusted_input(request.text),
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

        # 风格校验：流式路径不重试（delta 已发出），违规即失败，由上层兜底。
        violations = style_guard.check_reply(
            response_payload.reply_text,
            injected_memories=memories or None,
            injected_impressions=impressions or None,
        )
        if violations:
            # #110：先留快照再抛——dialogue_service 在 error 帧分支据此落一行
            # source=llm_blocked 的信号记录，拦截事件不再对数据集失明。
            self.last_style_violations = [_violation_snapshot(v) for v in violations]
            detail = "; ".join(f"{v.category}: {v.message}" for v in violations)
            raise LLMClientError(f"LLM streamed response failed style guard: {detail}")

        self.last_topics = response_payload.topics
        self.last_facts = response_payload.facts
        self.last_corrected_fact_ids = response_payload.corrected_fact_ids
        self.last_reply_topics = response_payload.reply_topics
        self.last_relationship_signal = response_payload.relationship_signal
        self.last_salient = response_payload.salient
        self.last_style_violations = []

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
