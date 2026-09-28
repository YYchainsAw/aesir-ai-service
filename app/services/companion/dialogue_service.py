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
    get_registered_profile,
)
from app.services.companion.dialogue_signals import record_turn_signal
from app.services.companion.session_memory import get_session_memory
from app.services.llm.client import LLMClientError
from app.services.memory.facts import is_grounded
from app.services.memory.store import MemoryStore, MemoryStoreError, get_memory_store
from app.services.memory.retrieval import retrieve, retrieve_impressions
from app.services.memory.topics import extract_topics, looks_salient


def create_dialogue_reply(request: CompanionDialogueRequest) -> CompanionDialogueResponse:
    """按 YAML 人设选择 LLM；不可用时回退到 YAML 分类候选回复。

    记忆接入（SDD T028）：检索长期记忆注入 LLM prompt；回复后把该轮写入短期
    记忆。记忆体系任何故障都降级为「无记忆继续对话」（FR-011 / T030），
    绝不因记忆问题中断玩家流程。
    """
    # 按 companion_id 路由到已登记角色；未登记抛 UnknownCompanionError → 404（FR-044）。
    profile = get_registered_profile(request.companion_id)

    memory = get_session_memory(get_settings().dialogue_history_turns)
    history = memory.history(request.session_id) if request.session_id else ()

    memories = _recall(request.companion_id)
    impressions = _recall_impressions(request.companion_id, history)
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
            facts = service.last_facts
            salient = service.last_salient
            reply_topics = service.last_reply_topics
            relationship_signal = service.last_relationship_signal
        except LLMClientError:
            response = _create_mock_dialogue_reply(request, profile=profile, source="fallback")
            topics = None
            facts = None
            salient = None
            reply_topics = None
            relationship_signal = None
    else:
        response = _create_mock_dialogue_reply(request, profile=profile, source="mock")
        topics = None
        facts = None
        salient = None
        reply_topics = None
        relationship_signal = None
    response.relationship_stage = stage
    response.relationship_stage_display = _relationship_stage_display(stage)
    _annotate_observability(response, profile, memories=memories, impressions=impressions)
    response.relationship_delta = _record_turn(
        request,
        response,
        topics=topics,
        facts=facts,
        salient=salient,
        reply_topics=reply_topics,
        relationship_signal=relationship_signal,
        injected_topics=[i.topic for i in impressions],
        style_violations=getattr(service, "last_style_violations", None) if get_settings().companion_backend == "llm" else None,
    )
    return response


def stream_dialogue_reply(request: CompanionDialogueRequest) -> Iterator[StreamEvent]:
    """``create_dialogue_reply`` 的流式变体：delta 先行，meta 为权威结束帧。

    回退语义（契约附录有记录）：LLM 在发出任何 delta 之前失败 → 静默回退
    mock（source="fallback"），与非流式一致；已发出 delta 后中断 → yield
    error 事件并停止，该轮不写记忆（唯一与非流式的行为差异）。

    注意：本函数是普通函数（不是生成器），人设校验在调用时立即执行，
    未知名伴的 404 得以在 SSE 响应头发出之前抛出。
    """
    profile = get_registered_profile(request.companion_id)

    memory = get_session_memory(get_settings().dialogue_history_turns)
    history = memory.history(request.session_id) if request.session_id else ()

    memories = _recall(request.companion_id)
    impressions = _recall_impressions(request.companion_id, history)
    stage = _relationship_stage(request.companion_id)

    if get_settings().companion_backend != "llm":
        return _stream_mock_reply(
            request, profile=profile, source="mock", stage=stage,
            memories=memories, impressions=impressions,
        )

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
            event.response.relationship_delta = _record_turn(
                request,
                event.response,
                topics=service.last_topics,
                facts=service.last_facts,
                salient=service.last_salient,
                reply_topics=service.last_reply_topics,
                relationship_signal=service.last_relationship_signal,
                injected_topics=[i.topic for i in impressions],
                style_violations=service.last_style_violations,
            )
            _annotate_observability(
                event.response, profile, memories=memories, impressions=impressions
            )
            yield _with_stage(event, stage)
            return
    except LLMClientError:
        if emitted_delta:
            yield StreamEvent(kind="error", text="LLM stream interrupted; this turn is incomplete.")
            return
        yield from _stream_mock_reply(
            request, profile=profile, source="fallback", stage=stage,
            memories=memories, impressions=impressions,
        )


def _stream_mock_reply(
    request: CompanionDialogueRequest,
    *,
    profile: CompanionProfile,
    source: str,
    stage: str,
    memories: list[MemoryEntry],
    impressions: list,
) -> Iterator[StreamEvent]:
    """mock / fallback 流式输出：单 delta（全文）+ meta，保持客户端体验一致。"""
    response = _create_mock_dialogue_reply(request, profile=profile, source=source)
    _record_turn(request, response)
    _annotate_observability(response, profile, memories=memories, impressions=impressions)
    if response.reply_text:
        yield StreamEvent(kind="delta", text=response.reply_text)
    yield _with_stage(StreamEvent(kind="meta", response=response), stage)


def _with_stage(event: StreamEvent, stage: str) -> StreamEvent:
    if event.response is not None:
        event.response.relationship_stage = stage
        event.response.relationship_stage_display = _relationship_stage_display(stage)
    return event


def _relationship_stage_display(stage: str) -> str:
    """FIX-05：关系阶段中文展示名；空 stage 或故障时返回空字符串。"""
    from app.services.relationship.policy import get_stage_display_name

    return get_stage_display_name(stage)


def _note_runtime(request: CompanionDialogueRequest, response: CompanionDialogueResponse) -> None:
    """US7（T077）：记录最近情绪，供调试台查询；任何故障静默。"""
    try:
        from app.services.console.runtime_state import record_observation

        record_observation(request.companion_id, emotion_id=response.emotion_id)
    except Exception:
        pass


def _annotate_observability(
    response: CompanionDialogueResponse,
    profile: CompanionProfile,
    *,
    memories: list[MemoryEntry],
    impressions: list,
) -> None:
    """US7（T076）链路信息：人设版本 + 本轮实际注入的记忆条数（按通道）。

    只报事实：mock/回退路径同样注入了记忆（供埋点口径统一），但回退回复
    未必使用——仍如实记录注入量。
    """
    response.persona_revision = str(profile.raw.get("profile_version", ""))
    response.memory_layers = {
        "long_term": len(memories),
        "impressions": len(impressions),
    }


def _record_turn(
    request: CompanionDialogueRequest,
    response: CompanionDialogueResponse,
    *,
    topics: list[str] | None = None,
    facts: list[str] | None = None,
    salient: bool | None = None,
    reply_topics: list[str] | None = None,
    relationship_signal: str | None = None,
    injected_topics: list[str] | None = None,
    style_violations: list[str] | None = None,
) -> int:
    """成功完成一轮后写入会话记忆与长期记忆（与非流式路径相同副作用）。

    四通道：``topics``/``facts``/``salient``/``reply_topics``/``relationship_signal``
    为 LLM 顺带返回；``None``（mock/回退路径）退化为规则提取（事实通道无规则
    兜底，直接为空——规则切不出可靠的「事实」，宁可没有；关系信号同理——
    规则判断不了「玩家的关心是真心还是客套」，mock 路径不推动关系）。郑重声明
    （salient）逐字入档案（玩家期待精确复述）+ 主题入印象层（等效提及加成按
    在意值缩放、衰减更慢）；普通发言的主题只入印象层，陈述出的事实经接地校验
    后入档案。艾莉自己的回复的主题入印象（非显著）——她记得自己说过什么，
    反复谈起的话题同样形成印象；六修（2026-09-22 实测复盘）起 LLM 路径改用
    模型自述的 ``reply_topics``——规则切词没有分词库，产出「主修/厉害/水系本来」
    这类碎片直接污染印象层（且新印象权重 1.0 立即回注 prompt）。
    ``relationship_signal`` 是对话推动关系（2026-09-22）的入口：把 LLM 判定的
    玩家发言情感质量计进关系层，返回本轮实际 delta。``injected_topics`` 为
    本轮注入 prompt 的印象主题（埋点用，见 ``dialogue_signals``）。
    """
    memory = get_session_memory(get_settings().dialogue_history_turns)
    prior_history = memory.history(request.session_id) if request.session_id else ()
    _note_runtime(request, response)
    if request.session_id:
        # 情绪一并落窗口：下一轮把它作为「当前心情」注入，情绪才有惯性
        # （mock/回退路径同样有 emotion_id，故降级时也延续）。
        memory.record(
            request.session_id,
            request.text,
            response.reply_text,
            emotion_id=response.emotion_id,
        )
    if topics is None:
        topics = extract_topics(request.text)
    if salient is None:
        salient = looks_salient(request.text)
    if salient:
        _remember_fact(request.companion_id, request.text)
    _remember_facts(
        request.companion_id,
        facts or [],
        # 接地来源 = 玩家本轮原话 + 近期真说过的玩家发言（跨轮拼出的复合事实
        # 也能落地，但凭空捏造的仍会被拦下）。
        sources=[request.text, *(t.user_text for t in prior_history)],
    )
    salience_boost = _care_scaled_boost(request.companion_id) if salient else None
    _remember_turn(
        request.companion_id, topics, salient=salient, salience_boost=salience_boost
    )
    if reply_topics is None:
        # mock/回退路径没有 LLM 自述主题，规则提取兜底（玩家侧规则路径维持现状）。
        reply_topics = extract_topics(response.reply_text)
    if reply_topics:
        # 艾莉自己的话也入印象，但标 origin=companion——注入时按「她说过的话」
        # 而非「玩家提过的话题」措辞，避免她把自己的话记成玩家说的。
        _remember_turn(request.companion_id, reply_topics, origin="companion")

    # 信号埋点（RL 前置）：先用记录前的会话历史算复读度/话题延续，再落 JSONL；
    # 任何故障静默（绝不阻塞对话）。
    record_turn_signal(
        request.companion_id,
        request.session_id,
        player_text=request.text,
        reply_text=response.reply_text,
        source=response.source or "mock",
        emotion_id=response.emotion_id,
        gesture_id=response.gesture_id,
        facial_expression_id=response.facial_expression_id,
        game_state=request.game_state,
        injected_topics=injected_topics,
        previous_player_texts=[t.user_text for t in prior_history],
        previous_reply_texts=[t.reply_text for t in prior_history],
        style_violations=style_violations,
    )
    return _apply_relationship_signal(request.companion_id, relationship_signal)


# 对话推动关系（2026-09-22）：LLM 判定的玩家发言情感质量 → 关系事件类型。
# none 不计分（绝大多数轮次都是 none——宁漏勿滥）。
_DIALOGUE_RELATIONSHIP_EVENTS = {
    "warm": "dialogue_warm_exchange",
    "deep": "dialogue_deep_connection",
    "cold": "dialogue_cold_dismissal",
    "hurtful": "dialogue_hurtful_remark",
}


def _apply_relationship_signal(companion_id: str, signal: str | None) -> int:
    """把情感质量信号计进关系层；返回本轮实际 delta，故障静默返回 0。

    复用关系规则层全套（同类冷却/日上限/持久化/损坏降级）——对话信号用
    更严的冷却窗口（默认 300 秒 vs 事实事件 60 秒）：对话每轮都发生，
    60 秒拦不住连点刷分。关系层故障不中断对话（FR-011 同纪律）。
    """
    event_type = _DIALOGUE_RELATIONSHIP_EVENTS.get(signal or "none")
    if event_type is None:
        return 0
    from app.services.relationship.state import (
        RelationshipStoreError,
        get_relationship_store,
    )

    try:
        _, delta = get_relationship_store(companion_id).apply_event(
            event_type,
            cooldown_seconds=get_settings().relationship_dialogue_cooldown_seconds,
        )
        return delta
    except RelationshipStoreError:
        return 0


def _recall(companion_id: str) -> list[MemoryEntry]:
    """检索长期记忆（预算内）；故障降级为空列表（FR-011）。"""
    try:
        return retrieve(get_memory_store(companion_id))
    except MemoryStoreError:
        return []


def _recall_impressions(companion_id: str, history: tuple = ()) -> list:
    """检索模糊印象（份额内）；故障降级为空列表（FR-011 同语义）。

    ``history`` 为近期会话原文：已经聊过的话题本轮冷却不注入（防话题
    重复复读，实测 2026-09-21）。
    """
    try:
        recent_texts = [t.user_text for t in history] + [t.reply_text for t in history]
        return retrieve_impressions(
            get_memory_store(companion_id), recent_texts=recent_texts or None
        )
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


def _remember_facts(companion_id: str, facts: list[str], *, sources: list[str]) -> int:
    """把本轮抽出的事实写进长期档案（过接地校验），返回落档条数。

    接地校验（``memory.facts.is_grounded``）是这条通道的**安全阀**：档案里的
    事实会被当作「她确定知道的事」长期注入，一旦编造就是永久错误记忆——
    比当场幻视严重得多。对不上玩家原话的事实直接丢弃（印象层仍留痕）。
    写失败静默降级（与其余记忆写入同语义）。
    """
    grounded = [fact for fact in facts if is_grounded(fact, sources)]
    if not grounded:
        return 0
    try:
        return get_memory_store(companion_id).record_facts(
            [
                MemoryEntry(
                    content=fact,
                    importance="normal",
                    source="player_statement",
                    tags=["dialogue", "fact"],
                )
                for fact in grounded
            ]
        )
    except MemoryStoreError:
        return 0


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
