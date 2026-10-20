"""agent/step 决策埋点单元测试（T38：SC-005/006/013 数据源）。

覆盖：落盘字段齐全、game_id 分目录、故障静默不抛出。
API 层挂载（POST /step 后真实落盘）见 tests/api/test_agent_step_signals.py。
"""

from __future__ import annotations

import json

from app.services.companion.agent_step_signals import record_agent_step


def test_record_writes_full_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path))
    record_agent_step(
        "companion.alice",
        game_id="aesir",
        scene="combat",
        action="directive",
        directive_action_type="approach_enemy",
        reason_codes=["ARB_WON:roam", "CAT_FOLLOW"],
        observability_source="rule",
        degraded=False,
    )
    record = json.loads(
        (tmp_path / "aesir" / "companion.alice.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["companion_id"] == "companion.alice"
    assert record["scene"] == "combat"
    assert record["action"] == "directive"
    assert record["directive_action_type"] == "approach_enemy"
    assert record["reason_codes"] == ["ARB_WON:roam", "CAT_FOLLOW"]
    assert record["observability_source"] == "rule"
    assert record["degraded"] is False
    assert record["ts"]


def test_empty_step_has_null_action_type(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path))
    record_agent_step(
        "companion.alice",
        game_id="aesir",
        scene="exploration",
        action="none",
        directive_action_type=None,
        reason_codes=["NO_AUTONOMOUS_CANDIDATE"],
        observability_source="rule",
    )
    record = json.loads(
        (tmp_path / "aesir" / "companion.alice.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["action"] == "none"
    assert record["directive_action_type"] is None
    assert record["reason_codes"] == ["NO_AUTONOMOUS_CANDIDATE"]


def test_game_id_partitions_files(monkeypatch, tmp_path):
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path))
    record_agent_step("companion.alice", game_id="aesir", scene="combat")
    record_agent_step("companion.alice", game_id="demo-vn", scene="combat")
    assert (tmp_path / "aesir" / "companion.alice.jsonl").exists()
    assert (tmp_path / "demo-vn" / "companion.alice.jsonl").exists()


def test_failure_is_silent(monkeypatch, tmp_path):
    # 非法目录字符 → 埋点吞掉异常，绝不抛给调用方。
    monkeypatch.setenv("AESIR_AGENT_STEPS_DIR", str(tmp_path / "bad<>|dir"))
    record_agent_step("companion.alice", game_id="aesir", scene="combat")
