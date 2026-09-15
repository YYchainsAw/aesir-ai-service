"""主入口：心跳与指令统一处理（SDD T013 / FR-021，协议 v0.3）。

UE 以固定间隔携带世界快照调用 ``/v1/agent/step``：
- 纯心跳（无 ``text``）：受最小间隔限流，超频返回 429；Phase 2 返回空动作。
- 玩家指令（有 ``text``）：Phase 2 骨架阶段如实返回「待接入」原因码，
  对话/记忆/仲裁链路在 T028 / T050~T054 接入；不做猜测执行（FR-028）。

系统 MUST NOT 主动向客户端推送：一切产出经本响应返回。
"""

import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas.agent_step import (
    PROTOCOL_VERSION,
    AgentStepObservability,
    AgentStepRequest,
    AgentStepResponse,
)
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
)

router = APIRouter(prefix="/v1/agent", tags=["agent"])

POLICY_REVISION = "agent-skeleton-001"  # Phase 2 骨架；仲裁/目录接入后升级

# ---------------------------------------------------------------------------
# 心跳限流（FR-022）：按角色记录最近一次心跳时刻，间隔不足即 429。
# 有界缓存防长会话膨胀（与 event_policy 同一做法）。
# ---------------------------------------------------------------------------
_MAX_TRACKED = 256

_last_heartbeat: "OrderedDict[str, float]" = OrderedDict()
_heartbeat_lock = threading.Lock()


def _heartbeat_too_soon(companion_id: str, min_interval: float) -> bool:
    now = time.monotonic()
    with _heartbeat_lock:
        last = _last_heartbeat.get(companion_id)
        if last is not None and (now - last) < min_interval:
            return True
        _last_heartbeat[companion_id] = now
        if len(_last_heartbeat) > _MAX_TRACKED:
            _last_heartbeat.popitem(last=False)
    return False


def _reset_heartbeat_tracker() -> None:
    """清空限流状态（仅测试用）。"""
    with _heartbeat_lock:
        _last_heartbeat.clear()


def _relationship_stage_or_empty(companion_id: str) -> str:
    """读取当前关系阶段（US2 / T042）；关系体系故障降级为空字符串。"""
    from app.services.relationship.state import (
        RelationshipStoreError,
        get_relationship_store,
    )

    try:
        return get_relationship_store(companion_id).state().stage
    except RelationshipStoreError:
        return ""


def _empty_response(request: AgentStepRequest, reason_codes: list[str]) -> AgentStepResponse:
    """空动作轻量返回（FR-025：不虚构行为；FR-021 判定无产出时快速返回）。"""
    return AgentStepResponse(
        protocol_version=PROTOCOL_VERSION,
        request_id=request.request_id,
        companion_id=request.companion_id,
        action="none",
        observability=AgentStepObservability(
            source="rule",
            reason_codes=reason_codes,
            policy_revision=POLICY_REVISION,
            used_snapshot_id=request.world_context.snapshot_id,
            relationship_stage=_relationship_stage_or_empty(request.companion_id),
        ),
    )


@router.post("/step", response_model=AgentStepResponse)
def agent_step(request: AgentStepRequest) -> AgentStepResponse:
    try:
        get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        # FR-044：未登记角色明确拒绝，不回退默认角色人格。
        raise HTTPException(status_code=404, detail=str(error)) from error

    if request.text is None:
        # 纯心跳：限流 + 空动作路径（T018 先跑通；自主行为判定在 T054 接入）
        settings = get_settings()
        if _heartbeat_too_soon(request.companion_id, settings.heartbeat_min_interval_seconds):
            raise HTTPException(
                status_code=429,
                detail=(
                    "心跳过频：最小间隔 "
                    f"{settings.heartbeat_min_interval_seconds} 秒（AESIR_HEARTBEAT_MIN_INTERVAL_SECONDS）"
                ),
            )
        return _empty_response(request, ["NO_AUTONOMOUS_CANDIDATE"])

    # 玩家指令：Phase 2 尚未接线（T028 对话 / T049+ 指令域），如实说明，不猜测执行。
    return _empty_response(request, ["TEXT_PIPELINE_PENDING"])
