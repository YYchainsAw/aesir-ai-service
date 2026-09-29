"""v0.2 战术决策端点：语义意图 + 状态快照 → 上下文战术决策（草案 §5）。

首版为规则策略（source 固定 ``rule``）。v0.1 的 ``/v1/commands/parse`` 保持
不变，继续承担「文本到意图」的前半段；UE 可先 parse 再 resolve。
"""

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.tactical_decision import (
    PROTOCOL_VERSION_V02,
    Observability,
    ResolveRequest,
    ResolveResponse,
    TacticalCommandRequest,
    TacticalDecision,
)
from app.schemas.tactical_execution import ExecutionReceiptRequest
from app.services.tactical.acknowledgement_service import create_tactical_acknowledgement
from app.services.tactical.llm_intent import parse_intent_with_source
from app.services.tactical.policy import get_policy
from app.services.tactical.receipt_store import append_receipt, append_receipts
from app.services.tactical.resolver import resolve_intent

router = APIRouter(prefix="/v1/tactical", tags=["tactical"])


def _persona_revision_or_empty(companion_id: str) -> str:
    """人设 YAML 的 profile_version（US7 / T076）；读取失败降级为空字符串。"""
    from app.services.companion.profile_repository import (
        CompanionProfileError,
        get_registered_profile,
    )

    try:
        return str(get_registered_profile(companion_id).raw.get("profile_version", ""))
    except CompanionProfileError:
        return ""


def _resolve_response(
    request_id: str, intent, combat_context, source: str = "rule"
) -> ResolveResponse:
    """resolve 与组合端点共用的响应组装（决策 + 人设回复 + 观察字段）。

    US2 关系调制（T039）不在此接入：v0.2 契约端点保持字节级行为不变，
    关系阶段化决策编排统一走 /v1/agent/step 主入口（Phase 5 T054）。
    """
    companion_id = combat_context.companion.id
    decision: TacticalDecision = resolve_intent(intent, combat_context)
    policy_backend = get_settings().tactical_policy
    # rl 后端尚未接入：按「规则系统始终保留」原则降级走规则，仅保留标记。
    # 人设回复从 data/companions YAML 读取（与 v0.1 命令路径同源），
    # 缺失时回退到状态决定的表情与兜底文案，保证路由不承载人设文案。
    ack = create_tactical_acknowledgement(intent.intent_id, companion_id=companion_id)
    return ResolveResponse(
        protocol_version=PROTOCOL_VERSION_V02,
        request_id=request_id,
        recognized=decision is not None,
        source=source,
        decision=decision,
        companion_reply={
            "reply_text": ack.reply_text if ack else "收到。",
            "emotion_id": (
                ack.emotion_id
                if ack
                else ("emotion.serious" if decision.status == "actionable" else "emotion.thoughtful")
            ),
        },
        observability=Observability(
            normalized_text=intent.normalized_text,
            # US7（T076）：人设版本（读取失败降级为空字符串）
            persona_revision=_persona_revision_or_empty(companion_id),
            # rl 后端请求但未接入时保留标记，便于在回执数据中区分；
            # 规则路径的版本号来自 data/policy/tactical_policy.yaml
            policy_revision=(
                f"{get_policy().revision}-rl-pending"
                if policy_backend == "rl"
                else get_policy().revision
            ),
            used_snapshot_id=combat_context.snapshot_id,
        ),
    )


@router.post("/resolve", response_model=ResolveResponse)
def resolve_tactical(request: ResolveRequest) -> ResolveResponse:
    return _resolve_response(request.request_id, request.intent, request.combat_context)


@router.post("/command", response_model=ResolveResponse)
def command_tactical(request: TacticalCommandRequest) -> ResolveResponse:
    """组合端点：文本 + 战斗快照 → 上下文战术决策（一次调用）。

    文本先解析出 ``TacticalIntent``（后端由 ``AESIR_INTENT_BACKEND`` 决定：
    规则 / LLM，LLM 失败自动回退规则），再走 resolve 的上下文策略；
    不可识别时按策划书 §5.2 回复澄清——不猜测、不施放。
    """
    intent, source = parse_intent_with_source(
        request.text, companion_id=request.combat_context.companion.id
    )
    if intent is None:
        return ResolveResponse(
            protocol_version=PROTOCOL_VERSION_V02,
            request_id=request.request_id,
            recognized=False,
            source=source,
            decision=None,
            companion_reply={
                "reply_text": "我没听清你想让我做什么，能再说一遍吗？",
                "emotion_id": "emotion.thoughtful",
            },
            observability=Observability(
                normalized_text=request.text,
                policy_revision=get_policy().revision,
                used_snapshot_id=request.combat_context.snapshot_id,
            ),
        )
    return _resolve_response(
        request.request_id, intent, request.combat_context, source=source
    )


@router.post("/executions", status_code=202)
def record_execution(request: ExecutionReceiptRequest) -> dict:
    """UE 对 order 的执行回执（v0.2/v0.3）：落 JSONL，202 表示受理。

    兼容单条 ``{"receipt": {...}}`` 与批量 ``{"receipts": [...]}``。
    """
    if request.receipt is not None:
        path = append_receipt(request.receipt)
        return {"stored": True, "order_id": request.receipt.order_id, "path": str(path)}

    path = append_receipts(request.receipts)
    return {
        "stored": True,
        "count": len(request.receipts),
        "order_ids": [r.order_id for r in request.receipts],
        "path": str(path),
    }
