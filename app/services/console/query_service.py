"""Shared console queries and explicit reset operation."""
from fastapi import HTTPException

from app.config import get_settings
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
    list_registered_companions,
)
from app.services.companion.session_memory import get_session_memory
from app.services.memory.store import MemoryStoreError, get_memory_store
from app.services.tactical.policy import get_policy


from app.schemas.console import MemoryEntryView, ConsoleStateResponse, MemoryResetRequest, MemoryResetResponse, TopicImpressionView, MemoryViewResponse

def console_state(companion_id: str) -> ConsoleStateResponse:
    try:
        profile = get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    game_id = profile.game_name.lower()

    # US7（T077）：关系（故障降级为空阶段/None，不阻塞调试台）
    from app.services.relationship.policy import get_stage_display_name
    from app.services.relationship.state import (
        RelationshipStoreError,
        get_relationship_store,
    )

    try:
        rel = get_relationship_store(companion_id, game_id=game_id).state()
        relationship_stage, relationship_value = rel.stage, rel.value
    except RelationshipStoreError:
        relationship_stage, relationship_value = "", None
    relationship_stage_display = get_stage_display_name(relationship_stage)

    # 近期记忆摘要（检索预算内的条目按重要性取前 5；故障为空列表）
    try:
        from app.services.memory.retrieval import retrieve

        recent = retrieve(get_memory_store(companion_id, game_id=game_id))[:5]
    except MemoryStoreError:
        recent = []

    from app.services.agency.behavior_catalog import get_agency_policy
    from app.services.console.runtime_state import get_observation

    observation = get_observation(companion_id)

    return ConsoleStateResponse(
        registered_companions=list_registered_companions(),
        companion_id=profile.companion_id,
        display_name=profile.display_name,
        memory_backend="四级存储：短期窗口 / 经历摘要 / 长期档案 / 模糊印象",
        session_memory_turns=get_settings().dialogue_history_turns,
        tactical_policy_revision=get_policy().revision,
        persona_revision=str(profile.raw.get("profile_version", "")),
        agency_policy_revision=get_agency_policy().revision,
        relationship_stage=relationship_stage,
        relationship_stage_display=relationship_stage_display,
        relationship_value=relationship_value,
        last_scene=observation.scene,
        last_emotion_id=observation.emotion_id,
        last_seen=observation.last_seen,
        recent_memory=[
            MemoryEntryView(
                content=e.content, importance=e.importance,
                source=e.source, real_time=e.real_time,
            )
            for e in recent
        ],
    )


def view_memory(companion_id: str) -> MemoryViewResponse:
    try:
        profile = get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    try:
        snapshot = get_memory_store(companion_id, game_id=profile.game_name.lower()).snapshot()
    except MemoryStoreError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    def _view(entry) -> MemoryEntryView:
        return MemoryEntryView(
            content=entry.content, importance=entry.importance,
            source=entry.source, real_time=entry.real_time,
        )

    return MemoryViewResponse(
        companion_id=companion_id,
        counts={
            "short_term": len(snapshot.short_term),
            "summaries": len(snapshot.summaries),
            "archive": len(snapshot.archive),
            "impressions": len(snapshot.impressions),
        },
        short_term=[_view(e) for e in snapshot.short_term],
        summaries=[_view(e) for e in snapshot.summaries],
        archive=[_view(e) for e in snapshot.archive],
        impressions=[
            TopicImpressionView(
                topic=i.topic, mention_count=i.mention_count,
                weight=i.weight, last_seen=i.last_seen, origin=i.origin,
            )
            for i in snapshot.impressions
        ],
    )


def reset_memory(request: MemoryResetRequest) -> MemoryResetResponse:
    try:
        profile = get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    # 记忆重置（FR-010 / T029）：清空长期记忆 + 会话记忆分区。
    # 长期记忆故障时仍算部分成功：会话记忆已清，长期记忆保持原样并如实返回。
    memory = get_session_memory(get_settings().dialogue_history_turns)
    cleared = memory.clear(request.companion_id)
    long_term_reset = True
    try:
        get_memory_store(request.companion_id, game_id=profile.game_name.lower()).clear()
    except MemoryStoreError:
        long_term_reset = False
    return MemoryResetResponse(
        companion_id=request.companion_id, reset=long_term_reset, cleared_sessions=cleared
    )
