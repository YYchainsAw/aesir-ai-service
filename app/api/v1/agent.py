"""主入口：心跳与指令统一处理（SDD T013/T054 / FR-021，协议 v0.3）。

UE 以固定间隔携带世界快照调用 ``/v1/agent/step``：
- 纯心跳（无 ``text``）：受最小间隔限流，超频返回 429；随后走自主行为
  编排——禁打断判定 → 候选生成 → 目录校验 → 跨域仲裁 → 节流 → 指令输出
  （T054，全部规则驱动、不虚构行为 FR-028）。
- 玩家指令（有 ``text``）：与 ``/v1/tactical/command`` 共用同一决策层
  （T075：``parse_intent_with_source`` → 按域路由）。战斗意图走
  ``resolve_intent`` 战术决策（含 US2 关系调制），非战斗意图映射到 agency
  行为目录并按当前场景做目录/距离校验；不可识别时回复澄清，不猜测执行。

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
from app.schemas.directives.common import (
    DirectiveEnvelope,
    DirectivePresentation,
    ExpiresBeforeSeconds,
)
from app.services.agency.arbiter import arbitrate
from app.services.agency.behavior_catalog import (
    AgencyPolicyError,
    behaviors_allowed,
    generate_candidates,
    get_agency_policy,
)
from app.services.agency.domain import domain_for, no_interrupt_reason, resolve_scene
from app.services.agency.throttle import get_throttle
from app.services.companion.profile_repository import (
    CompanionProfileError,
    UnknownCompanionError,
    get_registered_profile,
)

router = APIRouter(prefix="/v1/agent", tags=["agent"])


def _policy_revision() -> str:
    """当前策略版本（agency_policy.yaml 的 revision，归因用）。"""
    return get_agency_policy().revision


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
            policy_revision=_policy_revision(),
            used_snapshot_id=request.world_context.snapshot_id,
            relationship_stage=_relationship_stage_or_empty(request.companion_id),
        ),
    )


def _presentation_for(
    companion_id: str, gaze_target_id: str | None
) -> tuple[DirectivePresentation | None, str]:
    """表现块：台词模板取角色默认对话表现；表现 ID 已由人设 YAML 白名单校验。

    人设读取失败（IO/校验）时降级：presentation=None + 简短 reply_text
    （章程原则 V，降级不中断自主行为输出）。
    """
    try:
        profile = get_registered_profile(companion_id)
    except CompanionProfileError:
        return None, "……（她安静地待在你身边。）"
    default = profile.default_dialogue_response
    return (
        DirectivePresentation(
            reply_text=default.reply_text,
            emotion_id=default.emotion_id,
            gesture_id=default.gesture_id,
            facial_expression_id=default.facial_expression_id,
            interruptible=True,
            gaze_target_id=gaze_target_id,
        ),
        "",
    )


def _autonomous_step(request: AgentStepRequest) -> AgentStepResponse:
    """纯心跳的自主行为编排（T054）：禁打断 → 候选 → 目录 → 仲裁 → 节流。"""
    ctx = request.world_context
    companion_id = request.companion_id

    # 禁打断（FR-023）：命中即静止，不发起任何自主行为
    interrupt = no_interrupt_reason(ctx)
    if interrupt is not None:
        return _empty_response(request, [f"INTERRUPT_FORBIDDEN:{interrupt}"])

    scene = resolve_scene(ctx)
    # 候选生成内含目录域过滤与不可执行防护（FR-019/FR-025/FR-040）
    try:
        candidates = generate_candidates(
            ctx, relationship_stage=_relationship_stage_or_empty(companion_id)
        )
    except AgencyPolicyError:
        return _empty_response(request, ["AGENCY_POLICY_ERROR"])

    if not candidates:
        return _empty_response(request, ["NO_AUTONOMOUS_CANDIDATE"])

    # 防御式目录校验（策略文件即法律；生成层已过滤，此处兜底）
    allowed_names = {spec.name for spec in behaviors_allowed(scene)}
    candidates = [c for c in candidates if c.behavior in allowed_names]
    if not candidates:
        return _empty_response(request, ["NOT_ACTIONABLE"])

    result = arbitrate(candidates)
    if result.winner is None:
        return _empty_response(request, result.reason_codes or ["NO_AUTONOMOUS_CANDIDATE"])

    winner = result.winner
    decision = get_throttle().admit(companion_id, winner)
    if not decision.allowed:
        return _empty_response(request, ["THROTTLED", *decision.reason_codes])

    presentation, fallback_text = _presentation_for(companion_id, winner.target_id)
    directive = DirectiveEnvelope(
        agent_id=companion_id,
        domain=domain_for(scene),
        action_type=winner.behavior,
        priority=winner.priority,
        expires=ExpiresBeforeSeconds(remaining_seconds=10.0),
        source="autonomy",
        reason_codes=[*winner.reason_codes, f"ARB_WON:{winner.category}"],
        policy_revision=_policy_revision(),
        payload=winner.payload,
        presentation=presentation,
    )
    return AgentStepResponse(
        protocol_version=PROTOCOL_VERSION,
        request_id=request.request_id,
        companion_id=companion_id,
        action="directive",
        directive=directive,
        reply_text=fallback_text,
        observability=AgentStepObservability(
            source="rule",
            reason_codes=[f"ARB_WON:{winner.category}", *winner.reason_codes],
            policy_revision=_policy_revision(),
            used_snapshot_id=ctx.snapshot_id,
            relationship_stage=_relationship_stage_or_empty(companion_id),
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
        # 纯心跳：限流 + 自主行为编排（T054）
        settings = get_settings()
        if _heartbeat_too_soon(request.companion_id, settings.heartbeat_min_interval_seconds):
            raise HTTPException(
                status_code=429,
                detail=(
                    "心跳过频：最小间隔 "
                    f"{settings.heartbeat_min_interval_seconds} 秒（AESIR_HEARTBEAT_MIN_INTERVAL_SECONDS）"
                ),
            )
        return _autonomous_step(request)

    return _command_step(request)


# ---------------------------------------------------------------------------
# 玩家文本指令（T075）：与 /v1/tactical/command 共用同一意图解析与决策层
# ---------------------------------------------------------------------------
# 战斗意图 → 战术决策动作 → 指令 action_type（combat.py 白名单）
_COMBAT_ACTION_TYPE = {
    "major_heal": "major_heal",
    "quick_heal": "quick_heal",
    "shield": "shield",
    "explosion": "burst",
}

# 非战斗意图 → agency 行为目录行为名
_NON_COMBAT_BEHAVIOR = {
    "follow_player": "follow",
    "inspect_interactable": "inspect",
    "pickup_item": "pickup",
    "rest_here": "rest",
    "wait_here": "wait",
}


def _intent_observability(
    request: AgentStepRequest, source: str, reason_codes: list[str], snapshot_id: str
) -> AgentStepObservability:
    return AgentStepObservability(
        source=source,
        reason_codes=reason_codes,
        policy_revision=_policy_revision(),
        used_snapshot_id=snapshot_id,
        relationship_stage=_relationship_stage_or_empty(request.companion_id),
    )


def _command_step(request: AgentStepRequest) -> AgentStepResponse:
    """文本指令：意图解析（规则/LLM 门面）→ 按域路由 → 统一信封输出。

    与 ``/v1/tactical/command`` 的前半段完全同源（``parse_intent_with_source``），
    决策层不分叉：战斗意图复用 ``resolve_intent``（含关系调制），非战斗意图
    复用 agency 行为目录的场景/距离校验（FR-025/FR-040：只引用快照中的目标）。
    """
    from app.services.tactical.llm_intent import parse_intent_with_source

    intent, source = parse_intent_with_source(request.text)
    ctx = request.world_context

    if intent is None:
        # 不可识别：按策划书 §5.2 回复澄清，不猜测执行（FR-028）
        return AgentStepResponse(
            protocol_version=PROTOCOL_VERSION,
            request_id=request.request_id,
            companion_id=request.companion_id,
            action="none",
            reply_text="我没听清你想让我做什么，能再说一遍吗？",
            observability=_intent_observability(
                request, source, ["INTENT_UNRECOGNIZED"], ctx.snapshot_id
            ),
        )

    from app.schemas.tactical_intent import COMBAT_INTENT_IDS

    if intent.intent_id in COMBAT_INTENT_IDS:
        return _combat_command_step(request, intent, source)

    return _non_combat_command_step(request, intent, source)


def _combat_command_step(request: AgentStepRequest, intent, source: str) -> AgentStepResponse:
    """战斗意图：resolve_intent 战术决策 + US2 关系调制（与 /v1/tactical 同层）。"""
    from app.services.tactical.resolver import resolve_intent

    ctx = request.world_context
    if ctx.combat is None:
        # 快照未携带战斗上下文：如实说明，不虚构战况执行（FR-028）
        return AgentStepResponse(
            protocol_version=PROTOCOL_VERSION,
            request_id=request.request_id,
            companion_id=request.companion_id,
            action="none",
            reply_text="现在不在战斗中，我先待命。",
            observability=_intent_observability(
                request, source, ["COMBAT_CONTEXT_MISSING"], ctx.snapshot_id
            ),
        )

    decision = resolve_intent(intent, ctx.combat, _relationship_stage_or_empty(request.companion_id))
    if decision.status != "actionable" or decision.action is None:
        return AgentStepResponse(
            protocol_version=PROTOCOL_VERSION,
            request_id=request.request_id,
            companion_id=request.companion_id,
            action="none",
            reply_text=decision.explanation,
            observability=_intent_observability(
                request, source, decision.reason_codes, ctx.snapshot_id
            ),
        )

    action = decision.action
    if action.type == "retreat":
        action_type = "retreat"
    elif action.type == "follow":
        action_type = "follow"
    else:
        suffix = (action.ability_id or "").rsplit(".", 1)[-1]
        action_type = _COMBAT_ACTION_TYPE.get(suffix, action.type)
    presentation, _ = _presentation_for(request.companion_id, action.target_id)
    directive = DirectiveEnvelope(
        agent_id=request.companion_id,
        domain="combat",
        action_type=action_type,
        priority=action.priority,
        source="player_command",
        reason_codes=decision.reason_codes,
        policy_revision=_policy_revision(),
        payload={"target_id": action.target_id or ""},
        presentation=presentation,
    )
    return AgentStepResponse(
        protocol_version=PROTOCOL_VERSION,
        request_id=request.request_id,
        companion_id=request.companion_id,
        action="directive",
        directive=directive,
        observability=_intent_observability(
            request, source, decision.reason_codes, ctx.snapshot_id
        ),
    )


def _non_combat_command_step(request: AgentStepRequest, intent, source: str) -> AgentStepResponse:
    """非战斗意图：映射 agency 行为目录，按场景与距离校验（不虚构目标）。"""
    ctx = request.world_context
    behavior = _NON_COMBAT_BEHAVIOR[intent.intent_id]

    spec = next(
        (s for s in behaviors_allowed(ctx.scene) if s.name == behavior), None
    )
    if spec is None:
        # 当前场景不允许该行为（如战斗中「休息」）：如实说明（FR-019）
        return AgentStepResponse(
            protocol_version=PROTOCOL_VERSION,
            request_id=request.request_id,
            companion_id=request.companion_id,
            action="none",
            reply_text="现在不方便做这个。",
            observability=_intent_observability(
                request,
                source,
                ["BEHAVIOR_NOT_IN_SCENE", f"INTENT:{intent.intent_id}", f"SCENE:{ctx.scene}"],
                ctx.snapshot_id,
            ),
        )

    # 目标选择：有目标行为取快照中最近的可交互物（类型/距离按目录校验）
    payload: dict[str, str] = {}
    reasons = [f"INTENT:{intent.intent_id}", f"BEHAVIOR:{behavior}"]
    if spec.allowed_kinds:
        candidates = [
            obj
            for obj in ctx.interactables
            if obj.kind in spec.allowed_kinds and obj.distance_m <= spec.max_distance_m
        ]
        if not candidates:
            # 附近没有合适目标：不虚构（FR-040），回复澄清
            return AgentStepResponse(
                protocol_version=PROTOCOL_VERSION,
                request_id=request.request_id,
                companion_id=request.companion_id,
                action="none",
                reply_text="附近没有合适的目标。",
                observability=_intent_observability(
                    request,
                    source,
                    [*reasons, "NO_VALID_TARGET"],
                    ctx.snapshot_id,
                ),
            )
        target = min(candidates, key=lambda o: o.distance_m)
        payload["target_id"] = target.object_id
        reasons.append(f"TARGET:{target.object_id}")

    presentation, _ = _presentation_for(request.companion_id, payload.get("target_id"))
    directive = DirectiveEnvelope(
        agent_id=request.companion_id,
        domain=domain_for(ctx.scene),
        action_type=behavior,
        priority=spec.priority,
        source="player_command",
        reason_codes=reasons,
        policy_revision=_policy_revision(),
        payload=payload,
        presentation=presentation,
    )
    return AgentStepResponse(
        protocol_version=PROTOCOL_VERSION,
        request_id=request.request_id,
        companion_id=request.companion_id,
        action="directive",
        directive=directive,
        observability=_intent_observability(request, source, reasons, ctx.snapshot_id),
    )
