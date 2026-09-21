"""能力注册表（SDD T067 / FR-035）。

把 NPC 的全部可用能力收敛到**一张注册表**，覆盖战斗行为、生活行为、信息
查询三类。注册表本身不持有任何配置——它是对既有单一配置源的**投影**：

============ ==========================================================
战斗行为      ``data/policy/tactical_policy.yaml`` 的 ``abilities``
生活行为      ``data/policy/agency_policy.yaml`` 的 ``behaviors``
信息工具      ``app/services/skills/tools.py`` 的 ``TOOL_SPECS``
============ ==========================================================

这样做的意义在于「能力清单」永远不会与真正生效的策略漂移（章程原则 I：
配置只有一份）。如果哪天注册表说某项能力存在、而策略层不认，那不是配置
写错了，而是有人绕开这里另建了一份目录——``tests/services/test_skill_registry.py``
会当场拆穿。

信息工具的场景白名单刻意不含 ``combat``（T071）：战斗链路要保延迟，不查证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.agency.behavior_catalog import get_agency_policy
from app.services.skills.tools import TOOL_SPECS
from app.services.tactical.policy import get_policy

CapabilityKind = Literal["combat_action", "life_action", "info_tool"]

_COMBAT_SCENES = frozenset({"combat"})
_TACTICAL_POLICY_SOURCE = "data/policy/tactical_policy.yaml"
_AGENCY_POLICY_SOURCE = "data/policy/agency_policy.yaml"
_TOOLS_SOURCE = "app/services/skills/tools.py"


class SkillRegistryError(RuntimeError):
    """注册表用法错误（重名、空名）。"""


@dataclass(frozen=True)
class Capability:
    """注册表中的一个能力。

    ``name`` 是稳定 ID（战斗用 UE 能力 ID、生活行为用 ``behave.*``、工具用
    ``tool.*``）；``scenes`` 是允许使用它的活动场景白名单；``source`` 记录
    它从哪份配置投影而来，供可解释与归因使用（FR-042）。
    """

    name: str
    kind: CapabilityKind
    scenes: frozenset[str]
    description: str = ""
    source: str = ""


class SkillRegistry:
    """能力登记与查询；登记顺序不影响查询结果（``names`` 稳定排序）。"""

    def __init__(self) -> None:
        self._by_name: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if not capability.name:
            raise SkillRegistryError("能力名不能为空")
        if capability.name in self._by_name:
            raise SkillRegistryError(f"能力名重复登记：{capability.name}")
        self._by_name[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._by_name.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def by_kind(self, kind: CapabilityKind) -> tuple[Capability, ...]:
        return tuple(self._by_name[name] for name in self.names() if self._by_name[name].kind == kind)

    def for_scene(
        self, scene: str, *, kind: CapabilityKind | None = None
    ) -> tuple[Capability, ...]:
        """某场景下可用的能力；未登记的场景返回空元组（不是错误）。"""
        return tuple(
            capability
            for capability in (self.by_kind(kind) if kind else tuple(self._by_name[n] for n in self.names()))
            if scene in capability.scenes
        )


def build_registry() -> SkillRegistry:
    """从既有配置源构造注册表（每次调用都重新投影，不缓存配置本身）。"""
    registry = SkillRegistry()

    for ability in get_policy().abilities.values():
        registry.register(
            Capability(
                name=ability.id,
                kind="combat_action",
                scenes=_COMBAT_SCENES,
                description=ability.description,
                source=_TACTICAL_POLICY_SOURCE,
            )
        )

    for name, behavior in get_agency_policy().behaviors.items():
        registry.register(
            Capability(
                name=f"behave.{name}",
                kind="life_action",
                scenes=behavior.domains,
                description=behavior.description,
                source=_AGENCY_POLICY_SOURCE,
            )
        )

    for tool in TOOL_SPECS.values():
        registry.register(
            Capability(
                name=tool.name,
                kind="info_tool",
                scenes=tool.scenes,
                description=tool.description,
                source=_TOOLS_SOURCE,
            )
        )

    return registry


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """进程内缓存的注册表（配置是版本库资产，运行期不变）。"""
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


def reset_registry_cache() -> None:
    """清空缓存（仅测试用）。"""
    global _registry
    _registry = None
