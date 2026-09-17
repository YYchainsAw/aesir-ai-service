"""能力注册表（SDD T064 / FR-035）。

注册表是**既有配置源的视图**，不是第二份真相：战斗行为取自 resolver 的能力
目录、生活行为取自 ``agency_policy.yaml``、信息工具取自 ``skills.tools``。
本文件既验证注册表自身的登记/查询/过滤语义，也守住「不许另起一份目录」
这条架构约束（章程原则 I）。
"""

import pytest

from app.services.skills.registry import (
    Capability,
    SkillRegistry,
    SkillRegistryError,
    build_registry,
    get_registry,
)


def _capability(name: str, kind: str, scenes: set[str]) -> Capability:
    return Capability(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        scenes=frozenset(scenes),
        description="测试用能力",
        source="test",
    )


# ---------------------------------------------------------------------------
# 登记与查询
# ---------------------------------------------------------------------------


def test_register_then_get_returns_the_same_capability() -> None:
    registry = SkillRegistry()
    capability = _capability("tool.demo", "info_tool", {"conversation"})

    registry.register(capability)

    assert registry.get("tool.demo") is capability


def test_get_unknown_name_returns_none() -> None:
    assert SkillRegistry().get("tool.nope") is None


def test_duplicate_name_fails_fast() -> None:
    """重名登记必须立即报错：静默覆盖会让「单一注册表」失去意义。"""
    registry = SkillRegistry()
    registry.register(_capability("tool.demo", "info_tool", {"conversation"}))

    with pytest.raises(SkillRegistryError):
        registry.register(_capability("tool.demo", "life_action", {"camp"}))


def test_empty_name_is_rejected() -> None:
    registry = SkillRegistry()

    with pytest.raises(SkillRegistryError):
        registry.register(_capability("", "info_tool", {"conversation"}))


def test_names_are_sorted_for_stable_prompts() -> None:
    registry = SkillRegistry()
    registry.register(_capability("tool.b", "info_tool", {"conversation"}))
    registry.register(_capability("tool.a", "info_tool", {"conversation"}))

    assert registry.names() == ("tool.a", "tool.b")


# ---------------------------------------------------------------------------
# 按类别与场景过滤
# ---------------------------------------------------------------------------


def test_by_kind_filters() -> None:
    registry = SkillRegistry()
    registry.register(_capability("tool.a", "info_tool", {"conversation"}))
    registry.register(_capability("behave.b", "life_action", {"camp"}))

    assert [c.name for c in registry.by_kind("info_tool")] == ["tool.a"]
    assert [c.name for c in registry.by_kind("life_action")] == ["behave.b"]
    assert registry.by_kind("combat_action") == ()


def test_for_scene_filters_by_scene_and_optional_kind() -> None:
    registry = SkillRegistry()
    registry.register(_capability("tool.a", "info_tool", {"conversation", "camp"}))
    registry.register(_capability("tool.b", "info_tool", {"combat"}))
    registry.register(_capability("behave.c", "life_action", {"camp"}))

    assert {c.name for c in registry.for_scene("camp")} == {"tool.a", "behave.c"}
    assert {c.name for c in registry.for_scene("camp", kind="info_tool")} == {"tool.a"}
    assert {c.name for c in registry.for_scene("conversation")} == {"tool.a"}


def test_for_scene_with_unknown_scene_returns_empty() -> None:
    registry = SkillRegistry()
    registry.register(_capability("tool.a", "info_tool", {"conversation"}))

    assert registry.for_scene("nowhere") == ()


# ---------------------------------------------------------------------------
# 内建注册表：三类能力齐备，且与既有配置源一致
# ---------------------------------------------------------------------------


def test_builtin_registry_covers_all_three_kinds() -> None:
    registry = build_registry()

    assert registry.by_kind("combat_action")
    assert registry.by_kind("life_action")
    assert registry.by_kind("info_tool")


def test_life_actions_are_a_view_of_agency_policy() -> None:
    """生活行为目录唯一来源是 agency_policy.yaml——注册表只做投影。"""
    from app.services.agency.behavior_catalog import get_agency_policy

    registered = {c.name for c in build_registry().by_kind("life_action")}
    expected = {f"behave.{name}" for name in get_agency_policy().behaviors}

    assert registered == expected


def test_life_action_scenes_come_from_the_policy() -> None:
    from app.services.agency.behavior_catalog import get_agency_policy

    policy = get_agency_policy()
    by_name = {c.name: c for c in build_registry().by_kind("life_action")}

    for name, spec in policy.behaviors.items():
        assert by_name[f"behave.{name}"].scenes == spec.domains


def test_combat_actions_cover_the_resolver_catalog() -> None:
    from app.services.tactical import resolver

    registered = {c.name for c in build_registry().by_kind("combat_action")}

    assert {
        resolver.ABIL_MAJOR_HEAL,
        resolver.ABIL_QUICK_HEAL,
        resolver.ABIL_SHIELD,
        resolver.ABIL_EXPLOSION,
    } <= registered


def test_combat_actions_are_combat_scene_only() -> None:
    for capability in build_registry().by_kind("combat_action"):
        assert capability.scenes == frozenset({"combat"})


def test_info_tools_are_available_in_conversation() -> None:
    names = {c.name for c in build_registry().for_scene("conversation", kind="info_tool")}

    assert "tool.lore.query" in names
    assert "tool.memory.recall" in names


def test_info_tools_are_never_available_in_combat() -> None:
    """FR-038/T071：战斗链路禁用查证保延迟，注册表层面就不放行。"""
    assert build_registry().for_scene("combat", kind="info_tool") == ()


def test_every_capability_declares_its_source() -> None:
    """FR-042 归因：每条能力都要能说清自己来自哪份配置。"""
    for capability in build_registry().names():
        assert build_registry().get(capability).source


def test_get_registry_is_process_cached() -> None:
    assert get_registry() is get_registry()
