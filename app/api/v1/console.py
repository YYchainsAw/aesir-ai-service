"""调试与控制台路由（SDD T015，US7 可解释的调试数据源）。

- ``GET /v1/console/state``：当前注册表、指定角色的运行状态摘要。
- ``GET /v1/console/memory``：查看指定角色的三级长期记忆（调试用，US1 验收）。
- ``POST /v1/console/memory/reset``：清空指定角色的会话与长期记忆。

Phase 2 骨架：长期记忆重置（T029）与情绪/关系阶段查询（T077）随后接入；
当前返回的就地状态以「如实汇报骨架能力」为限，不虚构未实现字段。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
    list_registered_companions,
)
from app.services.companion.session_memory import get_session_memory
from app.services.memory.store import MemoryStoreError, get_memory_store
from app.services.tactical.policy import get_policy

router = APIRouter(prefix="/v1/console", tags=["console"])


class ConsoleStateResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    registered_companions: list[str]
    companion_id: str
    display_name: str
    memory_backend: str          # 当前记忆后端说明（长期记忆 T025 落地后更新）
    session_memory_turns: int    # 会话记忆窗口配置
    tactical_policy_revision: str


class MemoryResetRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    companion_id: str = Field(min_length=1)


class MemoryResetResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    companion_id: str
    reset: bool
    cleared_sessions: int       # 实际清除的会话分区数（含 0：无会话也是成功）


@router.get("/state", response_model=ConsoleStateResponse)
def console_state(companion_id: str) -> ConsoleStateResponse:
    try:
        profile = get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return ConsoleStateResponse(
        registered_companions=list_registered_companions(),
        companion_id=profile.companion_id,
        display_name=profile.display_name,
        memory_backend="session-memory（进程内滚动窗口；长期记忆见 SDD T025）",
        session_memory_turns=get_settings().dialogue_history_turns,
        tactical_policy_revision=get_policy().revision,
    )


class MemoryEntryView(BaseModel):
    """调试视图：单条长期记忆的精简字段。"""

    model_config = ConfigDict(extra="forbid")
    content: str
    importance: str
    source: str
    real_time: str


class TopicImpressionView(BaseModel):
    """调试视图：单条模糊印象（主题 × 提及频率）。"""

    model_config = ConfigDict(extra="forbid")
    topic: str
    mention_count: int
    weight: float
    last_seen: str


class MemoryViewResponse(BaseModel):
    """长期记忆全量视图（GET /v1/console/memory），含模糊印象层。"""

    model_config = ConfigDict(extra="forbid")
    companion_id: str
    counts: dict[str, int]           # short_term / summaries / archive / impressions 各层条数
    short_term: list[MemoryEntryView]
    summaries: list[MemoryEntryView]
    archive: list[MemoryEntryView]
    impressions: list[TopicImpressionView]


@router.get("/memory", response_model=MemoryViewResponse)
def view_memory(companion_id: str) -> MemoryViewResponse:
    try:
        get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    try:
        snapshot = get_memory_store(companion_id).snapshot()
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
                weight=i.weight, last_seen=i.last_seen,
            )
            for i in snapshot.impressions
        ],
    )


@router.post("/memory/reset", response_model=MemoryResetResponse)
def reset_memory(request: MemoryResetRequest) -> MemoryResetResponse:
    try:
        get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    # 记忆重置（FR-010 / T029）：清空长期记忆 + 会话记忆分区。
    # 长期记忆故障时仍算部分成功：会话记忆已清，长期记忆保持原样并如实返回。
    memory = get_session_memory(get_settings().dialogue_history_turns)
    cleared = memory.clear(request.companion_id)
    long_term_reset = True
    try:
        get_memory_store(request.companion_id).clear()
    except MemoryStoreError:
        long_term_reset = False
    return MemoryResetResponse(
        companion_id=request.companion_id, reset=long_term_reset, cleared_sessions=cleared
    )
