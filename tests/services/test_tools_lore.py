"""只读查证工具：命中一致、未命中明确不确定（SDD T065 / FR-036、FR-037）。

US6 的验收核心是「有据可查 → 与事实一致；无据可查 → 明确表示不确定」。
因此本文件对每个工具都成对验证：命中路径与未命中路径。未命中路径断言的是
**明确的「查不到」标记**，而不是「返回了一段听起来合理的文本」——编造在这里
必须是不可能的，而不是「不鼓励」。
"""

from app.schemas.combat_context import make_combat_context
from app.schemas.memory import MemoryEntry
from app.schemas.world_context import (
    WorldCompanionState,
    WorldContext,
    WorldInteractable,
    WorldPlayerState,
    WorldRegion,
    WorldTime,
)
from app.services.skills.tools import (
    ToolRequest,
    get_lore,
    run_tool,
)


def _world_context(
    *,
    combat=None,
    interactables: list[WorldInteractable] | None = None,
) -> WorldContext:
    return WorldContext(
        snapshot_id="snap.test.001",
        captured_at="2026-09-17T12:00:00Z",
        scene="combat" if combat is not None else "exploration",
        world_time=WorldTime(game_clock="21:30", time_of_day="night", weather="rain"),
        region=WorldRegion(region_id="region.old_ruins", first_visit=False),
        player=WorldPlayerState(id="party.player", hp_percent=62),
        companion=WorldCompanionState(
            id="companion.alice", hp_percent=88, mp_percent=41, current_behavior="follow"
        ),
        interactables=interactables or [],
        combat=combat,
    )


# ---------------------------------------------------------------------------
# lore.query：命中
# ---------------------------------------------------------------------------


def test_lore_query_hits_a_documented_topic() -> None:
    result = run_tool(
        "tool.lore.query",
        request=ToolRequest(query="艾莉擅长什么", companion_id="companion.alice"),
    )

    assert result.found is True
    assert result.content
    assert result.source  # FR-012：查证结果必须可追溯来源


def test_lore_query_is_deterministic() -> None:
    """命中一致：同一问题反复问，拿到的是同一份事实（FR-036）。"""
    first = run_tool(
        "tool.lore.query", request=ToolRequest(query="Boss 眩晕的时候该怎么办")
    )
    second = run_tool(
        "tool.lore.query", request=ToolRequest(query="Boss 眩晕的时候该怎么办")
    )

    assert first == second
    assert first.found is True


def test_lore_query_matches_by_keyword() -> None:
    result = run_tool("tool.lore.query", request=ToolRequest(query="护盾是什么效果"))

    assert result.found is True
    assert "护盾" in result.content


def test_lore_entries_all_declare_a_source() -> None:
    """知识库条目必须登记来源（FR-012 可追溯）；没来源的条目不许进库。"""
    lore = get_lore()

    assert lore.entries
    for entry in lore.entries:
        assert entry.source
        assert entry.content


# ---------------------------------------------------------------------------
# lore.query：未命中——明确不确定，绝不编造
# ---------------------------------------------------------------------------


def test_lore_query_miss_is_explicitly_uncertain() -> None:
    """「这个遗迹是谁建的」是设定库里没有答案的问题（US6 验收场景 2）。"""
    result = run_tool(
        "tool.lore.query", request=ToolRequest(query="这个遗迹是谁建的")
    )

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes
    # 未命中时内容只能是「查不到」的声明，不能是一段像事实的叙述
    assert "没有记载" in result.content or "不清楚" in result.content
    assert result.source == ""


def test_lore_query_with_blank_query_is_uncertain() -> None:
    result = run_tool("tool.lore.query", request=ToolRequest(query="   "))

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes


def test_lore_query_does_not_answer_unrelated_questions() -> None:
    """反向守住：库里没有的内容，不能因为「沾了同一个词」就被答出来。"""
    result = run_tool("tool.lore.query", request=ToolRequest(query="遗迹的建造者是哪个文明"))

    assert result.found is False


# ---------------------------------------------------------------------------
# world.snapshot：战况快照（US6 验收场景 3：与最新收到的世界状态一致）
# ---------------------------------------------------------------------------


def test_world_snapshot_summarizes_the_latest_combat_state() -> None:
    combat = make_combat_context(player_hp=24, boss_hp=37, stunned_remaining=4.0)

    result = run_tool(
        "tool.world.snapshot",
        request=ToolRequest(
            companion_id="companion.alice", world_context=_world_context(combat=combat)
        ),
    )

    assert result.found is True
    assert "24" in result.content  # 玩家血量
    assert "37" in result.content  # Boss 血量
    assert result.source == combat.snapshot_id  # 结果可归因到具体快照


def test_world_snapshot_without_combat_context_is_uncertain() -> None:
    """非战斗场景没有战况可言——必须说不知道，不能凭印象编一场仗。"""
    result = run_tool(
        "tool.world.snapshot",
        request=ToolRequest(
            companion_id="companion.alice", world_context=_world_context(combat=None)
        ),
    )

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes


def test_world_snapshot_without_any_snapshot_is_uncertain() -> None:
    result = run_tool("tool.world.snapshot", request=ToolRequest(world_context=None))

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes


# ---------------------------------------------------------------------------
# world.interactables：环境可交互物
# ---------------------------------------------------------------------------


def test_world_interactables_lists_snapshot_objects() -> None:
    items = [
        WorldInteractable(object_id="prop.old_altar", kind="prop", distance_m=6.0, notable=True),
        WorldInteractable(object_id="item.herb", kind="item", distance_m=2.0),
    ]

    result = run_tool(
        "tool.world.interactables",
        request=ToolRequest(world_context=_world_context(interactables=items)),
    )

    assert result.found is True
    assert "prop.old_altar" in result.content
    assert "item.herb" in result.content


def test_world_interactables_with_nothing_around_is_uncertain() -> None:
    result = run_tool(
        "tool.world.interactables",
        request=ToolRequest(world_context=_world_context(interactables=[])),
    )

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes


# ---------------------------------------------------------------------------
# self.status：自身状态
# ---------------------------------------------------------------------------


def test_self_status_reports_companion_state() -> None:
    result = run_tool(
        "tool.self.status",
        request=ToolRequest(
            companion_id="companion.alice", world_context=_world_context()
        ),
    )

    assert result.found is True
    assert "88" in result.content  # HP
    assert "41" in result.content  # MP


def test_self_status_without_snapshot_is_uncertain() -> None:
    result = run_tool("tool.self.status", request=ToolRequest(world_context=None))

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes


# ---------------------------------------------------------------------------
# memory.recall：记忆检索（US6 弱依赖 US1）
# ---------------------------------------------------------------------------


def test_memory_recall_finds_a_remembered_fact() -> None:
    from app.services.memory.store import get_memory_store

    store = get_memory_store("companion.alice")
    store.record_fact(
        MemoryEntry(
            content="玩家说过自己最怕黑",
            importance="high",
            source="player_statement",
            tags=["dialogue"],
        )
    )

    result = run_tool(
        "tool.memory.recall",
        request=ToolRequest(query="怕黑", companion_id="companion.alice"),
    )

    assert result.found is True
    assert "怕黑" in result.content


def test_memory_recall_miss_is_uncertain() -> None:
    result = run_tool(
        "tool.memory.recall",
        request=ToolRequest(query="完全没提过的话题", companion_id="companion.alice"),
    )

    assert result.found is False
    assert "TOOL_NO_RESULT" in result.reason_codes


# ---------------------------------------------------------------------------
# 输出裁剪（FR-009 同理：不把无限上下文塞给模型）
# ---------------------------------------------------------------------------


def test_tool_output_is_trimmed_to_the_configured_budget(monkeypatch) -> None:
    monkeypatch.setenv("AESIR_TOOLS_OUTPUT_MAX_CHARS", "40")

    result = run_tool(
        "tool.world.snapshot",
        request=ToolRequest(
            world_context=_world_context(combat=make_combat_context(player_hp=24))
        ),
    )

    assert len(result.content) <= 40
