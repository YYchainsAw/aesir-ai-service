"""世界事件 → 共同经历（摘要层接线）。

对话之外的第二条长期记忆来源。UE 上报的世界事件里有一类带**共同经历**语义
（第一次踏进某地、收到礼物、玩家替她挡刀、承诺兑现、击败强敌）——这些写进
**经历摘要层**，检索时按重要性 + 时间注入，让「我们一起经历过什么」成为她
可以主动提起的素材；而不是写进档案层（那是关于玩家本人的事实）。

只收录确有共同经历语义的事件类型：瞬时的战斗状态（血量告急、蓝量过低、
Boss 眩晕）是当下要处理的情况，不是回忆，不入记忆。

细节一律取自事件 ``details`` / 快照，**不做任何推断**——记忆里写下的每个
名词都必须是上报方给过的（与「模型输出不可信」同一原则，宁可写泛一点）。
写记忆失败静默降级：记忆坏了不能影响事件响应（FR-011）。
"""

from __future__ import annotations

from app.schemas.memory import MemoryEntry
from app.services.memory.store import MemoryStoreError, get_memory_store

_DEFAULT_GAME_ID = "aesir"

# 事件类型 → (带细节的文案模板, 无细节时的兜底文案)。``{detail}`` 由
# _DETAIL_KEYS 指定的字段填充；取不到就整句回退到兜底，不拼半截话。
_EXPERIENCE_TEMPLATES: dict[str, tuple[str, str]] = {
    "region_first_entered": (
        "和玩家一起第一次踏进{detail}",
        "和玩家一起第一次踏进陌生的地方",
    ),
    "gift_given": ("收到了玩家送的{detail}", "收到了玩家送的礼物"),
    "player_protected_companion": (
        "玩家替她挡下了危险",
        "玩家替她挡下了危险",
    ),
    "promise_kept": ("玩家兑现了承诺：{detail}", "玩家兑现了一个承诺"),
    "companion_recovered": ("她受了伤，玩家一直守到她恢复", "她受了伤，玩家一直守到她恢复"),
    "boss_defeated": ("和玩家一起击败了{detail}", "和玩家一起击败了强敌"),
}

# 细节字段候选（按顺序取第一个非空值）；取不到用兜底文案。
_DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    "region_first_entered": ("region_id",),
    "gift_given": ("item_id", "item_name"),
    "promise_kept": ("promise_id", "promise"),
    "boss_defeated": ("boss_id", "boss_name"),
}

# 情感分量更重的事件按 high 记，检索排序与淘汰都优先保住它们。
_HIGH_IMPORTANCE = frozenset({"player_protected_companion", "promise_kept"})


def build_experience(
    event_type: str,
    *,
    details: dict[str, str] | None = None,
    occurred_at: str = "",
    region_id: str = "",
) -> MemoryEntry | None:
    """把一个世界事件转成共同经历条目；非共同经历类事件返回 ``None``。

    ``region_id`` 为快照里的当前地区：地区事件没有 ``details`` 时也能说清
    「第一次踏进哪里」。
    """
    template = _EXPERIENCE_TEMPLATES.get(event_type)
    if template is None:
        return None
    with_detail, fallback = template
    content = fallback
    for key in _DETAIL_KEYS.get(event_type, ()):
        value = (details or {}).get(key) or (region_id if key == "region_id" else "")
        if value:
            content = with_detail.format(detail=value)
            break
    return MemoryEntry(
        content=f"{content}。",
        importance="high" if event_type in _HIGH_IMPORTANCE else "normal",
        source="shared_experience",
        game_time=occurred_at,
        tags=["world_event", event_type],
    )


def record_world_event_experience(
    companion_id: str,
    event_type: str,
    *,
    game_id: str = _DEFAULT_GAME_ID,
    details: dict[str, str] | None = None,
    occurred_at: str = "",
    region_id: str = "",
) -> bool:
    """把事件写进该角色的经历摘要层；非共同经历类或写入失败返回 ``False``。

    调用方须保证**幂等**（同一事件重放不重复写），因为摘要是追加语义；
    存储层另按内容去重兜底（``MemoryStore.record_experience``）。
    """
    entry = build_experience(
        event_type, details=details, occurred_at=occurred_at, region_id=region_id
    )
    if entry is None:
        return False
    try:
        get_memory_store(companion_id, game_id=game_id).record_experience([entry])
    except MemoryStoreError:
        return False
    return True
