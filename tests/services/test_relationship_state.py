"""关系数值与阶段测试（SDD T032 / FR-015~FR-016）。"""

from __future__ import annotations

import pytest

from app.schemas.relationship import RelationshipState
from app.services.relationship.rules import stage_of
from app.services.relationship.state import RelationshipStore


@pytest.fixture()
def store(tmp_path) -> RelationshipStore:
    s = RelationshipStore("companion.alice", root=str(tmp_path))
    s.load()
    return s


def test_stage_boundaries() -> None:
    """阶段边界归属：24 疏远 / 25 平常 / 49 平常 / 50 友好 / 74 友好 / 75 亲密。"""
    assert stage_of(0) == "distant"
    assert stage_of(24) == "distant"
    assert stage_of(25) == "neutral"
    assert stage_of(49) == "neutral"
    assert stage_of(50) == "friendly"
    assert stage_of(74) == "friendly"
    assert stage_of(75) == "close"
    assert stage_of(100) == "close"


def test_initial_value_from_config(store: RelationshipStore) -> None:
    """新角色落到配置初值（默认 20 → neutral 段内 distant/neutral 边界由值决定）。"""
    state = store.state()
    assert state.value == 20
    assert state.stage == stage_of(20)


def test_clamp_to_bounds(store: RelationshipStore) -> None:
    """数值变化被钳制在 [min, max]，不越界（时间戳分散以绕开冷却与日上限）。"""
    # 每日净 +15（8+7），6 天 +90 远超 100-20 的差额
    for day in range(6):
        store.apply_event("promise_kept", f"2026-10-{day + 1:02d}T08:00:00Z")
        store.apply_event("promise_kept", f"2026-10-{day + 1:02d}T09:00:00Z")
    assert store.state().value == 100

    for day in range(20):  # -8/次（负向不受日上限），远超 100 的跌幅
        store.apply_event("promise_broken", f"2026-11-{day + 1:02d}T08:00:00Z")
    assert store.state().value == 0


def test_persistence_roundtrip(tmp_path) -> None:
    """写入后新实例（模拟重启）回读到相同数值与阶段。"""
    first = RelationshipStore("companion.alice", root=str(tmp_path))
    first.load()
    first.apply_event("player_protected_companion")
    value = first.state().value

    second = RelationshipStore("companion.alice", root=str(tmp_path))
    second.load()
    assert second.state().value == value
    assert second.state().stage == stage_of(value)


def test_state_model_clamps_on_construction() -> None:
    """模型层：越界数值构造时即钳制（防御性，持久化文件被手改也不产生越界状态）。"""
    assert RelationshipState(value=999).value == 100
    assert RelationshipState(value=-5).value == 0


def test_partitions_by_npc(tmp_path) -> None:
    """按角色分区：不同 NPC 的关系互不影响。"""
    alice = RelationshipStore("companion.alice", root=str(tmp_path))
    alice.load()
    alice.apply_event("gift_given")

    bob = RelationshipStore("companion.bob", root=str(tmp_path))
    bob.load()
    assert bob.state().value != alice.state().value
