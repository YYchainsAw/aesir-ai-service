"""只读查证工具（SDD T068 / FR-035~FR-038）。

NPC 回答设定类与状态类问题前先查证权威信息源，**查证全部只读**：这些工具
只读配置、快照与记忆，绝不修改任何状态（章程原则 III：服务端不是权威端）。

三条硬纪律，由 ``tests/services/test_tools_lore.py`` 与
``test_tools_degradation.py`` 守住：

1. **查不到就明确查不到**（FR-037）。未命中返回 ``found=False`` +
   ``TOOL_NO_RESULT``，内容只能是「没有记载」的声明——不允许在查不到时
   退而用模型记忆补一段像事实的话。
2. **任何故障都降级**（FR-041）。未注册工具、handler 异常、预算耗尽都
   折算成一个带原因码的空结果，绝不把异常抛进玩家对话流程。
3. **输出必须裁剪**。工具产出会回填进 prompt，长度受
   ``AESIR_TOOLS_OUTPUT_MAX_CHARS`` 约束（与记忆注入预算同一纪律，FR-009）。

模型给出的查证请求经由 ``run_lookup`` 校验后才执行——模型输出不可信，
字段类型与工具名都要过一遍（与 FR-002 的表现 ID 白名单同一纪律）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from app.config import get_settings
from app.schemas.world_context import WorldContext
from app.services.memory.store import MemoryStoreError, get_memory_store

_LORE_PATH = Path(__file__).resolve().parents[3] / "data" / "world" / "lore.yaml"

# 查证工具只服务非战斗链路（T071）：战斗路径要保延迟，注册表层面就不放行。
_NON_COMBAT_SCENES = frozenset({"exploration", "camp", "conversation", "idle"})

# 原因码
NO_RESULT = "TOOL_NO_RESULT"
UNKNOWN = "TOOL_UNKNOWN"
ERROR = "TOOL_ERROR"
TIMEOUT = "TOOL_TIMEOUT"
INVALID_REQUEST = "TOOL_INVALID_REQUEST"

# 回填给模型的文本统一带前缀，让「这是查证结果」与「这是玩家说的」不可混淆。
_PREFIX = "查证结果："


class LoreError(RuntimeError):
    """知识库 YAML 缺失或不符合配置契约。"""


# ---------------------------------------------------------------------------
# 世界观知识库（data/world/lore.yaml）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoreEntry:
    """知识库条目；``source`` 登记出处，保证每条事实可追溯（FR-012）。"""

    id: str
    topic: str
    keywords: tuple[str, ...]
    content: str
    source: str


@dataclass(frozen=True)
class LoreBase:
    revision: str
    entries: tuple[LoreEntry, ...]


def _build_lore(path: Path) -> LoreBase:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LoreError(f"知识库文件不存在：{path}") from exc
    except yaml.YAMLError as exc:
        raise LoreError(f"知识库 YAML 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise LoreError("知识库 YAML 顶层必须是映射")

    revision = str(raw.get("revision", ""))
    entries_raw = raw.get("entries") or []
    if not isinstance(entries_raw, list):
        raise LoreError("entries 必须是列表")

    entries: list[LoreEntry] = []
    for index, entry_raw in enumerate(entries_raw):
        if not isinstance(entry_raw, dict):
            raise LoreError(f"entries[{index}] 必须是映射")
        content = str(entry_raw.get("content", ""))
        source = str(entry_raw.get("source", ""))
        # 没有出处的内容不许进库：查证的价值就在于「说得出来源」。
        if not content or not source:
            raise LoreError(f"entries[{index}] 缺少 content 或 source")
        keywords_raw = entry_raw.get("keywords") or []
        if not isinstance(keywords_raw, list):
            raise LoreError(f"entries[{index}].keywords 必须是列表")
        entries.append(
            LoreEntry(
                id=str(entry_raw.get("id", f"lore.entry.{index}")),
                topic=str(entry_raw.get("topic", "")),
                keywords=tuple(str(k).lower() for k in keywords_raw),
                content=content,
                source=source,
            )
        )
    return LoreBase(revision=revision, entries=tuple(entries))


_lore_cache: LoreBase | None = None


def get_lore() -> LoreBase:
    """进程内缓存的知识库；测试需要重新加载时调用 ``reset_lore_cache()``。"""
    global _lore_cache
    if _lore_cache is None:
        _lore_cache = _build_lore(_LORE_PATH)
    return _lore_cache


def reset_lore_cache() -> None:
    global _lore_cache
    _lore_cache = None


def search_lore(query: str) -> LoreEntry | None:
    """按关键词命中条目；命中多条时取命中数最多者，同分取先登记的那条。

    刻意不做模糊相似度：宁可查不到（走明确的「不确定」路径），也不要
    「沾边就算命中」——那正是编造的开始。
    """
    normalized = query.strip().lower()
    if not normalized:
        return None
    best: LoreEntry | None = None
    best_hits = 0
    for entry in get_lore().entries:
        hits = sum(1 for keyword in entry.keywords if keyword and keyword in normalized)
        if hits > best_hits:
            best, best_hits = entry, hits
    return best


# ---------------------------------------------------------------------------
# 工具契约
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolRequest:
    """一次查证的输入；全部字段只读，工具不得回写任何状态。"""

    query: str = ""
    companion_id: str = "companion.alice"
    world_context: WorldContext | None = None


@dataclass(frozen=True)
class ToolResult:
    tool: str
    found: bool
    content: str = ""
    source: str = ""
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    scenes: frozenset[str]
    handler: Callable[[ToolRequest], ToolResult] = field(repr=False)


def _miss(tool: str, text: str, reason: str = NO_RESULT) -> ToolResult:
    """查不到的统一形态：明确的原因码 + 一句「没有记载」。"""
    return ToolResult(tool=tool, found=False, content=_PREFIX + text, reason_codes=(reason,))


# ---------------------------------------------------------------------------
# 各工具的 handler
# ---------------------------------------------------------------------------


def _lore_query(request: ToolRequest) -> ToolResult:
    entry = search_lore(request.query)
    if entry is None:
        return _miss("tool.lore.query", "知识库里没有记载这件事。")
    return ToolResult(
        tool="tool.lore.query",
        found=True,
        content=f"{_PREFIX}{entry.topic}——{entry.content}",
        source=entry.source,
    )


def _combat_of(request: ToolRequest):
    if request.world_context is None:
        return None
    return request.world_context.combat


def _world_snapshot(request: ToolRequest) -> ToolResult:
    combat = _combat_of(request)
    if combat is None:
        return _miss("tool.world.snapshot", "没有可用的战况快照，说不清现在的局势。")
    stunned = (
        f"，Boss 处于眩晕，还剩 {combat.boss.stunned_remaining_seconds:g} 秒"
        if combat.boss.stunned_remaining_seconds
        else ""
    )
    ready = sorted(
        ability
        for ability, state in combat.companion.ability_states.items()
        if state == "ready"
    )
    return ToolResult(
        tool="tool.world.snapshot",
        found=True,
        content=(
            f"{_PREFIX}玩家血量 {combat.player.hp_percent:g}%，"
            f"Boss 血量 {combat.boss.hp_percent:g}%、眩晕值 {combat.boss.stun_percent:g}%"
            f"{stunned}；艾莉血量 {combat.companion.hp_percent:g}%、"
            f"蓝量 {combat.companion.mp_percent:g}%；可用能力：{'、'.join(ready) or '无'}。"
        ),
        source=combat.snapshot_id,
    )


def _world_interactables(request: ToolRequest) -> ToolResult:
    context = request.world_context
    if context is None or not context.interactables:
        return _miss("tool.world.interactables", "附近没有值得留意的可交互物。")
    described = "、".join(
        f"{item.object_id}（{item.kind}，{item.distance_m:g} 米"
        f"{'，值得注意' if item.notable else ''}）"
        for item in context.interactables
    )
    return ToolResult(
        tool="tool.world.interactables",
        found=True,
        content=f"{_PREFIX}附近有：{described}。",
        source=context.snapshot_id,
    )


def _self_status(request: ToolRequest) -> ToolResult:
    context = request.world_context
    if context is None:
        return _miss("tool.self.status", "没有收到自己的状态快照。")
    companion = context.companion
    doing = f"，正在{companion.current_behavior}" if companion.current_behavior else ""
    return ToolResult(
        tool="tool.self.status",
        found=True,
        content=(
            f"{_PREFIX}艾莉血量 {companion.hp_percent:g}%、蓝量 {companion.mp_percent:g}%"
            f"{doing}。"
        ),
        source=context.snapshot_id,
    )


def _memory_recall(request: ToolRequest) -> ToolResult:
    """从长期记忆里翻找与提问相关的条目；存储故障降级为「想不起来」。"""
    query = request.query.strip()
    if not query:
        return _miss("tool.memory.recall", "不知道该回想什么。")
    try:
        snapshot = get_memory_store(request.companion_id).snapshot()
    except MemoryStoreError:
        return _miss("tool.memory.recall", "这会儿想不起来什么。", reason=ERROR)

    hits = [
        entry.content
        for entry in (*snapshot.archive, *snapshot.summaries, *snapshot.short_term)
        if query in entry.content
    ]
    hits += [
        f"玩家常提起「{impression.topic}」" for impression in snapshot.impressions
        if query in impression.topic
    ]
    if not hits:
        return _miss("tool.memory.recall", "关于这个想不起来什么。")
    return ToolResult(
        tool="tool.memory.recall",
        found=True,
        content=_PREFIX + "；".join(hits) + "。",
        source="memory",
    )


#: 能力注册表（FR-035）与两轮调用共用的工具清单。场景白名单刻意不含 combat（T071）。
TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="tool.lore.query",
            description="查世界观设定（同伴、能力、Boss、战斗分工等已知事实）。",
            scenes=_NON_COMBAT_SCENES,
            handler=_lore_query,
        ),
        ToolSpec(
            name="tool.world.snapshot",
            description="查当前战况（双方血量、Boss 眩晕、可用能力）。",
            scenes=_NON_COMBAT_SCENES,
            handler=_world_snapshot,
        ),
        ToolSpec(
            name="tool.world.interactables",
            description="查附近的可交互物（物件、道具、地点）。",
            scenes=_NON_COMBAT_SCENES,
            handler=_world_interactables,
        ),
        ToolSpec(
            name="tool.self.status",
            description="查自己的当前状态（血量、蓝量、正在做什么）。",
            scenes=_NON_COMBAT_SCENES,
            handler=_self_status,
        ),
        ToolSpec(
            name="tool.memory.recall",
            description="回想与玩家有关的往事与常提话题。",
            scenes=_NON_COMBAT_SCENES,
            handler=_memory_recall,
        ),
    )
}


# ---------------------------------------------------------------------------
# 执行入口
# ---------------------------------------------------------------------------


def run_tool(
    name: str,
    *,
    request: ToolRequest,
    deadline: float | None = None,
) -> ToolResult:
    """执行一次只读查证；任何失败都折算为带原因码的未命中结果。

    ``deadline`` 为 ``time.monotonic()`` 口径的预算终点（FR-038）：预算已
    耗尽时连工具都不跑，直接降级——查证永远不许拖慢玩家的等待。
    """
    if deadline is not None and time.monotonic() >= deadline:
        return _miss(name, "来不及查了，先说我知道的。", reason=TIMEOUT)

    spec = TOOL_SPECS.get(name)
    if spec is None:
        return _miss(name, "这个我查不了。", reason=UNKNOWN)

    try:
        result = spec.handler(request)
    except Exception:  # noqa: BLE001 - 查证故障一律降级，绝不中断对话（FR-041）
        return _miss(name, "查证没能完成，不敢乱说。", reason=ERROR)

    limit = get_settings().tools_output_max_chars
    if limit > 0 and len(result.content) > limit:
        return ToolResult(
            tool=result.tool,
            found=result.found,
            content=result.content[:limit],
            source=result.source,
            reason_codes=result.reason_codes,
        )
    return result


def run_lookup(
    raw: Any,
    *,
    companion_id: str,
    world_context: WorldContext | None = None,
    deadline: float | None = None,
) -> ToolResult:
    """校验并执行模型给出的查证请求（模型输出不可信，先过类型与白名单）。"""
    if not isinstance(raw, dict):
        return _miss("tool.invalid", "没听懂要查什么。", reason=INVALID_REQUEST)

    tool = raw.get("tool")
    query = raw.get("query", "")
    if not isinstance(tool, str) or not tool.strip():
        return _miss("tool.invalid", "没听懂要查什么。", reason=INVALID_REQUEST)
    if not isinstance(query, str):
        return _miss(str(tool), "没听懂要查什么。", reason=INVALID_REQUEST)

    return run_tool(
        tool.strip(),
        request=ToolRequest(
            query=query, companion_id=companion_id, world_context=world_context
        ),
        deadline=deadline,
    )


def tool_menu(scenes: frozenset[str] | None = None) -> tuple[ToolSpec, ...]:
    """按场景列出可用工具（供 prompt 与能力注册表使用）；稳定排序。"""
    specs = sorted(TOOL_SPECS.values(), key=lambda spec: spec.name)
    if scenes is None:
        return tuple(specs)
    return tuple(spec for spec in specs if spec.scenes & scenes)


__all__ = [
    "ERROR",
    "INVALID_REQUEST",
    "LoreBase",
    "LoreEntry",
    "LoreError",
    "NO_RESULT",
    "TIMEOUT",
    "TOOL_SPECS",
    "ToolRequest",
    "ToolResult",
    "ToolSpec",
    "UNKNOWN",
    "get_lore",
    "reset_lore_cache",
    "run_lookup",
    "run_tool",
    "search_lore",
    "tool_menu",
]
