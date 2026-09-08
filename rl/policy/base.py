"""策略协议定义（仅 typing，不引入任何重依赖）。"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from app.schemas.combat_context import CombatContext
    from app.schemas.tactical_decision import TacticalDecision
    from rl.sim.core import SimState


@runtime_checkable
class ActingPolicy(Protocol):
    """环境层策略：给定观测与 sim 状态，返回动作索引（Discrete(N)）。"""

    def select_action(self, obs: "np.ndarray", state: "SimState") -> int:
        ...


@runtime_checkable
class TacticalPolicy(Protocol):
    """服务层策略：CombatContext → TacticalDecision。

    RL 接入 ``/v1/tactical/resolve`` 时实现本协议（配合
    ``AESIR_TACTICAL_POLICY`` 开关与规则回退）；本阶段不接入。
    """

    def decide(self, ctx: "CombatContext") -> "TacticalDecision":
        ...
