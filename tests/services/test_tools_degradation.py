"""查证工具的降级路径（SDD T066 / FR-037、FR-038、FR-041）。

查证是「锦上添花」的一环：任何故障——工具没注册、handler 炸了、超时、模型
给了一段非法调用——都只允许产出「查不到」，绝不允许把异常抛给玩家流程，
更不允许在查不到时改用模型记忆补一段像事实的话。
"""

import time

import pytest

from app.schemas.combat_context import make_combat_context
from app.schemas.world_context import (
    WorldCompanionState,
    WorldContext,
    WorldPlayerState,
)
from app.services.skills import tools as tools_module
from app.services.skills.tools import ToolRequest, ToolResult, run_lookup, run_tool


def _world_context() -> WorldContext:
    return WorldContext(
        snapshot_id="snap.test.001",
        captured_at="2026-09-17T12:00:00Z",
        scene="combat",
        player=WorldPlayerState(id="party.player", hp_percent=62),
        companion=WorldCompanionState(id="companion.alice", hp_percent=88, mp_percent=41),
        combat=make_combat_context(player_hp=62),
    )


# ---------------------------------------------------------------------------
# 未注册工具
# ---------------------------------------------------------------------------


def test_unknown_tool_is_reported_not_raised() -> None:
    result = run_tool("tool.does_not_exist", request=ToolRequest())

    assert result.found is False
    assert "TOOL_UNKNOWN" in result.reason_codes


def test_lookup_with_unknown_tool_is_reported() -> None:
    result = run_lookup(
        {"tool": "tool.does_not_exist", "query": "随便问问"},
        companion_id="companion.alice",
        world_context=_world_context(),
    )

    assert result.found is False
    assert "TOOL_UNKNOWN" in result.reason_codes


# ---------------------------------------------------------------------------
# handler 抛异常 → TOOL_ERROR（FR-041：任一子系统故障都要保持可用）
# ---------------------------------------------------------------------------


def test_handler_exception_becomes_tool_error(monkeypatch) -> None:
    def _boom(_request: ToolRequest) -> ToolResult:  # pragma: no cover - 必抛
        raise RuntimeError("工具内部炸了")

    monkeypatch.setitem(
        tools_module.TOOL_SPECS,
        "tool.lore.query",
        tools_module.ToolSpec(
            name="tool.lore.query",
            description="测试替身",
            scenes=frozenset({"conversation"}),
            handler=_boom,
        ),
    )

    result = run_tool("tool.lore.query", request=ToolRequest(query="艾莉是谁"))

    assert result.found is False
    assert "TOOL_ERROR" in result.reason_codes
    assert result.content  # 仍要有可展示的「查不到」文案，而不是空字符串


def test_memory_store_failure_degrades_the_memory_tool(monkeypatch) -> None:
    """记忆体系故障时，查证降级为「想不起来了」，不影响本轮对话（FR-011）。"""
    from app.services.memory import store as memory_store_module
    from app.services.memory.store import MemoryStoreError

    def _boom(_companion_id: str):
        raise MemoryStoreError("记忆存储不可用")

    monkeypatch.setattr(memory_store_module, "get_memory_store", _boom)
    monkeypatch.setattr(tools_module, "get_memory_store", _boom, raising=False)

    result = run_tool(
        "tool.memory.recall",
        request=ToolRequest(query="怕黑", companion_id="companion.alice"),
    )

    assert result.found is False
    assert result.reason_codes  # 明确标了降级原因，不是静默空结果


# ---------------------------------------------------------------------------
# 超时（FR-038：查证有时间上限，超限降级为直接回应）
# ---------------------------------------------------------------------------


def test_expired_deadline_skips_the_tool_without_running_it(monkeypatch) -> None:
    calls: list[str] = []

    def _spy(request: ToolRequest) -> ToolResult:
        calls.append(request.query)
        return ToolResult(tool="tool.lore.query", found=True, content="不该跑到这里")

    monkeypatch.setitem(
        tools_module.TOOL_SPECS,
        "tool.lore.query",
        tools_module.ToolSpec(
            name="tool.lore.query",
            description="测试替身",
            scenes=frozenset({"conversation"}),
            handler=_spy,
        ),
    )

    result = run_tool(
        "tool.lore.query",
        request=ToolRequest(query="艾莉是谁"),
        deadline=time.monotonic() - 1.0,  # 预算已耗尽
    )

    assert result.found is False
    assert "TOOL_TIMEOUT" in result.reason_codes
    assert calls == []  # 预算耗尽时连工具都不该跑


def test_lookup_respects_the_deadline() -> None:
    result = run_lookup(
        {"tool": "tool.lore.query", "query": "艾莉是谁"},
        companion_id="companion.alice",
        world_context=_world_context(),
        deadline=time.monotonic() - 1.0,
    )

    assert result.found is False
    assert "TOOL_TIMEOUT" in result.reason_codes


# ---------------------------------------------------------------------------
# 非法调用 JSON（模型输出不可信，FR-002 同款纪律）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "not a dict",
        None,
        [],
        {},
        {"tool": 123},
        {"tool": ""},
        {"query": "艾莉是谁"},  # 缺 tool
    ],
)
def test_invalid_lookup_request_is_rejected(raw) -> None:
    result = run_lookup(
        raw, companion_id="companion.alice", world_context=_world_context()
    )

    assert result.found is False
    assert "TOOL_INVALID_REQUEST" in result.reason_codes


# ---------------------------------------------------------------------------
# 轮次上限（FR-038：上限 2 轮）
# ---------------------------------------------------------------------------


class _AlwaysLookupClient:
    """两轮都要求查证的模型：用来验证服务端不会无限查下去。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        self.calls += 1
        return {"action": "lookup", "tool": "tool.lore.query", "query": "艾莉是谁"}

    def stream_completion(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        raise AssertionError("本用例不走流式路径")


def test_lookup_round_limit_stops_after_two_model_calls() -> None:
    """上限 2 轮：一轮查证 + 一轮正式回复，绝不出现第三轮。"""
    from app.schemas.companion_dialogue import CompanionDialogueRequest
    from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
    from app.services.llm.client import LLMClientError

    client = _AlwaysLookupClient()
    service = LLMCompanionDialogueService(client=client)

    with pytest.raises(LLMClientError):
        service.reply(
            CompanionDialogueRequest(text="艾莉，你知道这个遗迹是谁建的吗"),
            world_context=_world_context(),
        )

    assert client.calls == 2
