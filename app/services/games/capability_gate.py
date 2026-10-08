"""L0/L3 能力门控（S4 / T029）。

按当前游戏档案（``data/games/<game_id>/capability.yaml``）对端点做显式门控：

- **L0**：只开放对话 / 记忆 / 关系链路；战斗、战术、自主行为、执行回执等
  完整链路一律 403 显式拒绝，并在响应体给出原因（不静默降级、不产生越界下发）。
- **L3**：按档案子集启用全部链路。
- **未知等级**：按 -1 处理，门控功能同样拒绝（等效「未知等级拒绝」）。
- **事件门禁**：世界事件按 ``event_type`` 必须落在档案 ``events`` 声明内，
  未声明的事件 403 拒绝并给出原因。

门控在路由层调用，失败抛 ``HTTPException(403)``，detail 为结构化字典：

```
{
  "reason_code": "CAPABILITY_LEVEL_INSUFFICIENT" | "EVENT_NOT_DECLARED",
  "feature": "tactical.command",
  "game_id": "demo-vn",
  "capability_level": "L0",
  "required": "L3",                # 仅等级不足时
  "event_type": "promise_kept"     # 仅事件未声明时
}
```
"""

from __future__ import annotations

from fastapi import HTTPException

from app.services.companion.profile_repository import get_current_capability
from app.services.companion.persona_pack_validator import Capability

_LEVEL_ORDER = {"L0": 0, "L3": 1}

FEATURE_COMMANDS_PARSE = "commands.parse"
FEATURE_TACTICAL_RESOLVE = "tactical.resolve"
FEATURE_TACTICAL_COMMAND = "tactical.command"
FEATURE_TACTICAL_EXECUTIONS = "tactical.executions"
FEATURE_COMBAT_EVENTS = "combat.events"
FEATURE_AGENT_STEP = "agent.step"
FEATURE_WORLD_EVENTS = "world.events"


def _level_rank(level: str) -> int:
    return _LEVEL_ORDER.get(level, -1)


def _reject(detail: dict) -> None:
    raise HTTPException(status_code=403, detail=detail)


def require_level(required: str, feature: str) -> Capability:
    """要求当前游戏能力等级不低于 ``required``；不足时 403 显式拒绝。"""
    capability = get_current_capability()
    if _level_rank(capability.level) < _level_rank(required):
        _reject(
            {
                "reason_code": "CAPABILITY_LEVEL_INSUFFICIENT",
                "feature": feature,
                "game_id": capability.game_id,
                "capability_level": capability.level,
                "required": required,
            }
        )
    return capability


def require_l3(feature: str) -> Capability:
    """完整链路（战斗/战术/自主行为/回执）的 L3 门控。"""
    return require_level("L3", feature)


def require_event_declared(event_type: str, feature: str) -> Capability:
    """世界/战斗事件必须落在当前游戏档案声明内；未声明 403 显式拒绝。"""
    capability = get_current_capability()
    if event_type not in capability.events:
        _reject(
            {
                "reason_code": "EVENT_NOT_DECLARED",
                "feature": feature,
                "game_id": capability.game_id,
                "capability_level": capability.level,
                "event_type": event_type,
            }
        )
    return capability
