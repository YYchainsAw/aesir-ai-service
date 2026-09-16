"""关系状态损坏降级测试（SDD T035 / FR-018）。"""

from __future__ import annotations

from app.config import get_settings
from app.services.relationship.state import RelationshipStore


def test_missing_file_falls_back_to_initial(tmp_path) -> None:
    """无关系文件（新角色）→ 初值继续服务。"""
    store = RelationshipStore("companion.alice", root=str(tmp_path))
    store.load()
    assert store.state().value == get_settings().relationship_initial


def test_corrupt_file_quarantined_and_service_usable(tmp_path) -> None:
    """文件损坏 → 隔离现场、回退初值，且之后仍可正常计分（服务不中断）。"""
    path = tmp_path / "companion.alice" / "relationship.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ 这不是合法 JSON", encoding="utf-8")

    store = RelationshipStore("companion.alice", root=str(tmp_path))
    store.load()
    assert store.state().value == get_settings().relationship_initial
    assert (tmp_path / "companion.alice" / "relationship.json.corrupt").exists()

    # 降级后服务可用：事件仍可计分并落盘
    state, delta = store.apply_event("gift_given")
    assert delta == 3
    reloaded = RelationshipStore("companion.alice", root=str(tmp_path))
    reloaded.load()
    assert reloaded.state().value == state.value


def test_backup_survives_corrupt_main_file(tmp_path) -> None:
    """主文件损坏但备份在：恢复备份而非初值（单版本备份的价值）。"""
    import json

    d = tmp_path / "companion.alice"
    d.mkdir(parents=True)
    good = {"value": 80, "day": "2026-09-13", "daily_net": 3, "recent_events": []}
    (d / "relationship.json.bak").write_text(json.dumps(good), encoding="utf-8")
    (d / "relationship.json").write_text("broken", encoding="utf-8")

    store = RelationshipStore("companion.alice", root=str(tmp_path))
    store.load()
    assert store.state().value == 80


def test_reset_restores_initial(tmp_path) -> None:
    """关系重置（调试/新周目）：清空数值与事件留痕，回初值。"""
    store = RelationshipStore("companion.alice", root=str(tmp_path))
    store.load()
    store.apply_event("promise_kept")
    assert store.state().recent_events

    store.reset()
    assert store.state().value == get_settings().relationship_initial
    assert store.state().recent_events == []
