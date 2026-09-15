"""US2 阶段对比演示（SDD T043）：同一指令 × 4 个关系阶段。

独立验收标准：同一指令在至少 3 个关系阶段下表现可区分。

用法（无需启动服务，直接运行）：

    .venv\\Scripts\\python scripts\\demo_relationship.py            # 战斗决策对比
    .venv\\Scripts\\python scripts\\demo_relationship.py --events  # 事件计分/防刷/日上限演示
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.combat_context import make_combat_context  # noqa: E402
from app.schemas.tactical_intent import TacticalIntent  # noqa: E402
from app.services.relationship.policy import get_policy  # noqa: E402
from app.services.relationship.rules import apply_relationship_event  # noqa: E402
from app.schemas.relationship import RelationshipState  # noqa: E402
from app.services.tactical.resolver import resolve_intent  # noqa: E402


def demo_stages() -> None:
    """战斗决策对比：低蓝量下请求护盾（distant 拒 / neutral 拒 / friendly 谨慎 / close 护）。"""
    policy = get_policy()
    intent = TacticalIntent(intent_id="support_protect_player", normalized_text="护住我！")
    ctx = make_combat_context(player_hp=55, companion_mp=8)  # 蓝量过低 + 护盾就绪

    print("=" * 62)
    print("演示一：同一指令「护住我！」在 4 个关系阶段下的决策差异")
    print(f"（快照：玩家 HP 55%，艾莉 MP 8%，护盾就绪；策略 {policy.revision}）")
    print("=" * 62)
    for stage in policy.stages:
        decision = resolve_intent(intent, ctx, relationship_stage=stage.name)
        print(f"\n[{stage.name:9s}] 数值 {stage.low}-{stage.high}｜称呼「{stage.address}」"
              f"｜投入 {stage.resource_willingness}｜服从 {stage.obedience}")
        print(f"  status      : {decision.status}")
        print(f"  reason_codes: {decision.reason_codes}")
        print(f"  explanation : {decision.explanation}")
        if decision.action:
            print(f"  action      : {decision.action.type} -> {decision.action.ability_id}")


def demo_events() -> None:
    """事件计分演示：正常增减 → 冷却防刷 → 每日上限 → 跨日重置。"""
    state = RelationshipState(value=20, stage="", day="2026-09-14", daily_net=0)
    print("\n" + "=" * 62)
    print("演示二：事件驱动与防刷（初始数值 20）")
    print("=" * 62)

    state, d = apply_relationship_event(state, "player_protected_companion", "2026-09-14T10:00:00Z")
    print(f"\n玩家替艾莉挡下攻击 (+6)  -> 计分 {d:+d}，数值 {state.value}（{state.stage}）")
    state, d = apply_relationship_event(state, "player_protected_companion", "2026-09-14T10:00:30Z")
    print(f"30 秒后重复上报同一事件  -> 计分 {d:+d}（冷却窗口内不计分），数值 {state.value}")
    state, d = apply_relationship_event(state, "promise_kept", "2026-09-14T11:00:00Z")
    print(f"玩家兑现承诺 (+8)      -> 计分 {d:+d}，数值 {state.value}（{state.stage}）")
    state, d = apply_relationship_event(state, "gift_given", "2026-09-14T12:00:00Z")
    print(f"赠送礼物 (+3)          -> 计分 {d:+d}（当日净 +17 超上限 15，截断 +1），数值 {state.value}")
    state, d = apply_relationship_event(state, "gift_given", "2026-09-14T13:00:00Z")
    print(f"再送礼物               -> 计分 {d:+d}（当日正向上限已用完），数值 {state.value}")
    state, d = apply_relationship_event(state, "promise_kept", "2026-09-15T09:00:00Z")
    print(f"次日兑现承诺 (+8)      -> 计分 {d:+d}，数值 {state.value}（{state.stage}，跨日额度重置）")


if __name__ == "__main__":
    demo_stages()
    if "--events" in sys.argv:
        demo_events()
    else:
        print("\n（加 --events 查看事件计分/防刷/日上限演示）")
