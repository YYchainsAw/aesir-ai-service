"""陪伴对话服务入口：默认模拟回复，配置后可调用 LLM。"""

import zlib
from collections.abc import Iterator

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.schemas.memory import MemoryEntry
from app.config import get_settings
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService, StreamEvent
from app.services.companion.profile_repository import (
    CompanionProfile,
    UnknownCompanionError,
    get_profile,
)
from app.services.companion.session_memory import get_session_memory
from app.services.llm.client import LLMClientError
from app.services.memory.store import MemoryStore, MemoryStoreError, get_memory_store
from app.services.memory.retrieval import retrieve, retrieve_impressions
from app.services.memory.topics import extract_topics, looks_salient


def create_dialogue_reply(request: CompanionDialogueRequest) -> CompanionDialogueResponse:
    """按 YAML 人设选择 LLM；不可用时回退到 YAML 分类候选回复。

    记忆接入（SDD T028）：检索长期记忆注入 LLM prompt；回复后把该轮写入短期
    记忆。记忆体系任何故障都降级为「无记忆继续对话」（FR-011 / T030），
    绝不因记忆问题中断玩家流程。
    """
    # mtime 缓存读取人设；id 校验语义与 require_primary 一致（404 路径不变）。
    profile = get_profile()
    if profile.companion_id != request.companion_id:
        raise UnknownCompanionError(f"Unsupported companion_id: {request.companion_id}")

    memory = get_session_memory(get_settings().dialogue_history_turns)
    history = memory.history(request.session_id) if request.session_id else ()

    memories = _recall(request.companion_id)
    impressions = _recall_impressions(request.companion_id)
    stage = _relationship_stage(request.companion_id)

    if get_settings().companion_backend == "llm":
        service = LLMCompanionDialogueService(profile=profile)
        try:
            response = service.reply(
                request,
                history=history,
                memories=memories,
                impressions=impressions,
                relationship_stage=stage,
                world_context=request.world_context,
            )
            topics = service.last_topics
            salient = service.last_salient
        except LLMClientError:
            response = _create_mock_dialogue_reply(request, profile=profile, source="fallback")
            topics = None
            salient = None
    else:
        response = _create_mock_dialogue_reply(request, profile=profile, source="mock")
        topics = None
        salient = None
    response.relationship_stage = stage
    _record_turn(request, response, topics=topics, salient=salient)
    return response


def stream_dialogue_reply(request: CompanionDialogueRequest) -> Iterator[StreamEvent]:
    """``create_dialogue_reply`` 的流式变体：delta 先行，meta 为权威结束帧。

    回退语义（契约附录有记录）：LLM 在发出任何 delta 之前失败 → 静默回退
    mock（source="fallback"），与非流式一致；已发出 delta 后中断 → yield
    error 事件并停止，该轮不写记忆（唯一与非流式的行为差异）。

    注意：本函数是普通函数（不是生成器），人设校验在调用时立即执行，
    未知名伴的 404 得以在 SSE 响应头发出之前抛出。
    """
    profile = get_profile()
    if profile.companion_id != request.companion_id:
        raise UnknownCompanionError(f"Unsupported companion_id: {request.companion_id}")

    memory = get_session_memory(get_settings().dialogue_history_turns)
    history = memory.history(request.session_id) if request.session_id else ()

    memories = _recall(request.companion_id)
    impressions = _recall_impressions(request.companion_id)
    stage = _relationship_stage(request.companion_id)

    if get_settings().companion_backend != "llm":
        return _stream_mock_reply(request, profile=profile, source="mock", stage=stage)

    return _stream_llm_reply(
        request,
        profile=profile,
        history=history,
        memories=memories,
        impressions=impressions,
        stage=stage,
    )


def _stream_llm_reply(
    request: CompanionDialogueRequest,
    *,
    profile: CompanionProfile,
    history: tuple,
    memories: list[MemoryEntry],
    impressions: list,
    stage: str,
) -> Iterator[StreamEvent]:
    service = LLMCompanionDialogueService(profile=profile)
    emitted_delta = False
    try:
        for event in service.stream_reply(
            request,
            history=history,
            memories=memories,
            impressions=impressions,
            relationship_stage=stage,
            world_context=request.world_context,
        ):
            if event.kind == "delta":
                emitted_delta = True
                yield event
                continue
            _record_turn(
                request,
                event.response,
                topics=service.last_topics,
                salient=service.last_salient,
            )
            yield _with_stage(event, stage)
            return
    except LLMClientError:
        if emitted_delta:
            yield StreamEvent(kind="error", text="LLM stream interrupted; this turn is incomplete.")
            return
        yield from _stream_mock_reply(request, profile=profile, source="fallback", stage=stage)


def _stream_mock_reply(
    request: CompanionDialogueRequest,
    *,
    profile: CompanionProfile,
    source: str,
    stage: str,
) -> Iterator[StreamEvent]:
    """mock / fallback 流式输出：单 delta（全文）+ meta，保持客户端体验一致。"""
    response = _create_mock_dialogue_reply(request, profile=profile, source=source)
    _record_turn(request, response)
    if response.reply_text:
        yield StreamEvent(kind="delta", text=response.reply_text)
    yield _with_stage(StreamEvent(kind="meta", response=response), stage)


def _with_stage(event: StreamEvent, stage: str) -> StreamEvent:
    if event.response is not None:
        event.response.relationship_stage = stage
    return event


def _record_turn(
    request: CompanionDialogueRequest,
    response: CompanionDialogueResponse,
    *,
    topics: list[str] | None = None,
    salient: bool | None = None,
) -> None:
    """成功完成一轮后写入会话记忆与长期记忆（与非流式路径相同副作用）。

    双通道：``topics``/``salient`` 为 LLM 顺带返回；``None``（mock/回退
    路径）退化为规则提取。郑重声明（salient）逐字入档案（玩家期待精确
    复述）+ 主题入印象层（等效提及加成按在意值缩放、衰减更慢）；普通
    发言只入印象层。艾莉自己的回复也提取主题入印象（非显著）——她记得
    自己说过什么，反复谈起的话题同样形成印象。
    """
    memory = get_session_memory(get_settings().dialogue_history_turns)
    if request.session_id:
        memory.record(request.session_id, request.text, response.reply_text)
    if topics is None:
        topics = extract_topics(request.text)
    if salient is None:
        salient = looks_salient(request.text)
    if salient:
        _remember_fact(request.companion_id, request.text)
    salience_boost = _care_scaled_boost(request.companion_id) if salient else None
    _remember_turn(
        request.companion_id, topics, salient=salient, salience_boost=salience_boost
    )
    reply_topics = extract_topics(response.reply_text)
    if reply_topics:
        # 艾莉自己的话也入印象，但标 origin=companion——注入时按「她说过的话」
        # 而非「玩家提过的话题」措辞，避免她把自己的话记成玩家说的。
        _remember_turn(request.companion_id, reply_topics, origin="companion")


def _recall(companion_id: str) -> list[MemoryEntry]:
    """检索长期记忆（预算内）；故障降级为空列表（FR-011）。"""
    try:
        return retrieve(get_memory_store(companion_id))
    except MemoryStoreError:
        return []


def _recall_impressions(companion_id: str) -> list:
    """检索模糊印象（份额内）；故障降级为空列表（FR-011 同语义）。"""
    try:
        return retrieve_impressions(get_memory_store(companion_id))
    except MemoryStoreError:
        return []


def _relationship_stage(companion_id: str) -> str:
    """当前关系阶段（US2 / T040）；故障降级为空字符串（对话不中断）。"""
    from app.services.relationship.state import (
        RelationshipStoreError,
        get_relationship_store,
    )

    try:
        return get_relationship_store(companion_id).state().stage
    except RelationshipStoreError:
        return ""


def _remember_turn(
    companion_id: str,
    topics: list[str],
    *,
    salient: bool = False,
    salience_boost: float | None = None,
    origin: str = "player",
) -> None:
    """把本轮主题写入模糊印象（频率强化）；写失败静默降级（服务继续，不记得而已）。"""
    try:
        get_memory_store(companion_id).record_mention(
            topics, salient=salient, salience_boost=salience_boost, origin=origin
        )
    except MemoryStoreError:
        pass


def _care_scaled_boost(companion_id: str) -> float | None:
    """郑重声明的等效提及加成，按当前在意值缩放。

    在意 = 偏离无感的程度（极爱与极厌都最在意）。关系数值读取失败时
    返回 ``None``（用全局默认加成，不缩放）。
    """
    from app.services.memory.topics import care_scale
    from app.services.relationship.state import (
        RelationshipStoreError,
        get_relationship_store,
    )

    try:
        value = get_relationship_store(companion_id).state().value
    except RelationshipStoreError:
        return None
    settings = get_settings()
    return settings.memory_impression_salience_boost * care_scale(value)


def _remember_fact(companion_id: str, player_text: str) -> None:
    """郑重声明逐字入档案（双通道之一：精确复述用）；写失败静默降级。"""
    try:
        get_memory_store(companion_id).record_fact(
            MemoryEntry(
                content=player_text,
                importance="high",
                source="player_statement",
                tags=["dialogue", "salient"],
            )
        )
    except MemoryStoreError:
        pass


def _create_mock_dialogue_reply(
    request: CompanionDialogueRequest,
    *,
    profile: CompanionProfile,
    source: str,
) -> CompanionDialogueResponse:
    """无 LLM 时的回复：按输入分类选候选；全部未命中退回默认回复。

    同一输入始终得到同一回复（哈希轮换是确定性的），不同输入在候选间分散。
    """
    presentation = _select_fallback_presentation(request.text, profile)
    return CompanionDialogueResponse(
        companion_id=request.companion_id,
        session_id=request.session_id,
        reply_text=presentation.reply_text,
        emotion_id=presentation.emotion_id,
        gesture_id=presentation.gesture_id,
        facial_expression_id=presentation.facial_expression_id,
        interruptible=presentation.interruptible,
        source=source,
    )


def _select_fallback_presentation(text: str, profile: CompanionProfile) -> object:
    """类别判序按 YAML fallback_dialogue_responses 的出现顺序（先命中先选）。"""
    for category in profile.fallback_reply_categories:
        if any(keyword in text for keyword in category.keywords):
            return category.replies[_stable_index(text, len(category.replies))]
    return profile.default_dialogue_response


def _stable_index(text: str, count: int) -> int:
    """文本的稳定哈希轮换：同输入（含跨进程重启）恒定，不同输入近似均匀分布。"""
    return zlib.crc32(text.encode("utf-8")) % count if count else 0
