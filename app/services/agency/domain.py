"""活动场景判定（SDD T050 / FR-019、FR-023）。

纯函数、无状态：信任 UE 上报的 ``scene`` 字段（快照是只读输入，章程原则
III），仅做防御性一致性检查；战斗域排除生活类行为；禁打断标志聚合为单一
原因名（与 ``agency_policy.yaml`` 的 ``no_interrupt_when`` 名单对齐）。
"""

from __future__ import annotations

from app.schemas.world_context import Scene, WorldContext
from app.services.agency.behavior_catalog import AgencyPolicy, get_agency_policy

# 禁打断检查顺序（FR-023）；顺序即多标志同时命中时的报告优先级
_INTERRUPT_CHECKS: tuple[tuple[str, str], ...] = (
    ("npc_casting", "companion_casting"),
    ("cutscene_playing", "cutscene_playing"),
    ("player_speaking", "player_speaking"),
    ("ui_popup", "ui_popup"),
)


def resolve_scene(ctx: WorldContext) -> Scene:
    """判定活动场景：透传 UE 上报的 ``scene``。

    scene 与内嵌 combat 快照矛盾时以 scene 为准——服务端不猜测、不重构
    客户端观测（FR-028）；战斗决策仍归 v0.1/v0.2 链路消费内嵌快照。
    """
    return ctx.scene


def domain_for(scene: Scene) -> Scene:
    """活动场景 → 指令域映射（同名一一映射，FR-019 五场景）。"""
    return scene


def allows_lifestyle(scene: Scene) -> bool:
    """战斗域排除生活类行为（FR-019）。"""
    return scene != "combat"


def no_interrupt_reason(
    ctx: WorldContext, policy: AgencyPolicy | None = None
) -> str | None:
    """禁打断判定：任一标志命中即返回原因名（与策略名单对齐），否则 None。

    命中时调用方不应发起自主行为（FR-023）；返回首个命中项保证可解释与
    测试确定性。
    """
    if policy is None:
        policy = get_agency_policy()
    allowed_causes = set(policy.throttle.no_interrupt_when)
    flags = {
        "companion_casting": ctx.companion.is_casting,
        "cutscene_playing": ctx.cutscene_playing,
        "player_speaking": ctx.player_speaking,
        "ui_popup": ctx.ui_popup,
    }
    for cause, flag_name in _INTERRUPT_CHECKS:
        if flags[flag_name] and cause in allowed_causes:
            return cause
    return None
