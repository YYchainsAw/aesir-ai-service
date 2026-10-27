"""dialogue_signal_report 离线报告测试（#54 切片 A）。

覆盖：正常统计、空目录、坏行跳过、分桶聚合、reward 触发率计算。
"""

from __future__ import annotations

import json

from scripts.rl.dialogue_signal_report import build_report


def _write(root, game, companion, rows):
    path = root / game / f"{companion}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _turn(**overrides) -> dict:
    base = {
        "ts": "2026-10-21T00:30:00+00:00",
        "companion_id": "companion.alice",
        "game_state": "conversation",
        "source": "llm",
        "player_text": "在吗",
        "reply_text": "在呀。",
        "signals": {"negative_feedback": None, "repetition_score": 0.0, "topic_continued": None},
        "repetitive": False,
        "style_violations": [],
        "relationship_stage": "neutral",
        "sentiment": "none",
        "relationship_delta": 0,
        "relationship_reason": "no_signal",
    }
    base.update(overrides)
    return base


def test_empty_dir_returns_zero_report(tmp_path):
    report = build_report(tmp_path)
    assert report["total_records"] == 0
    assert report["reward_signal_rates"]["negative_feedback_hit_pct"] == 0.0


def test_basic_counts_and_rates(tmp_path):
    _write(tmp_path, "aesir", "companion.alice", [
        _turn(signals={"negative_feedback": "没说过", "repetition_score": 0.0, "topic_continued": None},
              repetitive=False),
        _turn(repetitive=True, relationship_delta=2, sentiment="warm",
              relationship_reason="scored", memory_cited=True),
    ])
    report = build_report(tmp_path)
    assert report["total_records"] == 2
    assert report["by_companion"] == {"companion.alice": 2}
    # 2 条里 1 条负反馈 = 50%
    assert report["reward_signal_rates"]["negative_feedback_hit_pct"] == 50.0
    assert report["reward_signal_rates"]["repetitive_pct"] == 50.0
    assert report["reward_signal_rates"]["relationship_delta_nonzero_pct"] == 50.0
    assert report["sentiment_dist"] == {"none": 1, "warm": 1}
    assert report["relationship_reason_dist"] == {"no_signal": 1, "scored": 1}


def test_bad_lines_are_skipped(tmp_path):
    path = tmp_path / "aesir" / "companion.alice.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write(json.dumps(_turn()) + "\n")
        f.write("\n")  # 空行
    report = build_report(tmp_path)
    assert report["total_records"] == 1


def test_stage_x_state_buckets(tmp_path):
    _write(tmp_path, "aesir", "companion.alice", [
        _turn(relationship_stage="neutral", game_state="conversation"),
        _turn(relationship_stage="neutral", game_state="conversation"),
        _turn(relationship_stage="distant", game_state="exploration"),
    ])
    report = build_report(tmp_path)
    assert report["stage_x_state_buckets"] == {
        "neutral | conversation": 2,
        "distant | exploration": 1,
    }


def test_span_uses_min_and_max_ts(tmp_path):
    _write(tmp_path, "aesir", "companion.alice", [
        _turn(ts="2026-10-21T00:30:00+00:00"),
        _turn(ts="2026-10-21T01:36:05+00:00"),
    ])
    report = build_report(tmp_path)
    assert report["span"]["earliest"] == "2026-10-21T00:30:00+00:00"
    assert report["span"]["latest"] == "2026-10-21T01:36:05+00:00"
