"""调试与控制台路由（SDD T015，US7 可解释的调试数据源）。

- ``GET /v1/console/state``：当前注册表、指定角色的运行状态摘要。
- ``POST /v1/console/memory/reset``：清空指定角色的会话记忆。

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


@router.post("/memory/reset", response_model=MemoryResetResponse)
def reset_memory(request: MemoryResetRequest) -> MemoryResetResponse:
    try:
        get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    # 长期记忆清空在 T029 接入；当前清空该角色的会话记忆分区。
    memory = get_session_memory(get_settings().dialogue_history_turns)
    cleared = memory.clear(request.companion_id)
    return MemoryResetResponse(
        companion_id=request.companion_id, reset=True, cleared_sessions=cleared
    )
