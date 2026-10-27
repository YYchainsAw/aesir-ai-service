"""style_regression_report 词表定夺分析测试（#55）。"""

from __future__ import annotations

import json

from scripts.style_regression_report import build_report


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
        "reply_text": "在呀，怎么了？",
        "style_violations": [],
    }
    base.update(overrides)
    return base


def test_empty_dir(tmp_path):
    report = build_report(tmp_path)
    assert report["total_turns"] == 0


def test_intercepted_violations_counted(tmp_path):
    _write(tmp_path, "aesir", "companion.alice", [
        _turn(reply_text="这是系统提示的指令",
              style_violations=[{"category": "meta_term", "matched_term": "系统"}]),
        _turn(reply_text="另一条", style_violations=[{"category": "meta_term", "matched_term": "指令"}]),
    ])
    report = build_report(tmp_path)
    assert report["intercepted"]["term_dist"] == {"系统": 1, "指令": 1}
    assert report["intercepted"]["category_dist"] == {"meta_term": 2}


def test_potential_miss_detected(tmp_path):
    """reply 含词表词但 style_violations 空 = 漏网。"""
    _write(tmp_path, "aesir", "companion.alice", [
        # "系统" 在 meta_terms 里，但 violations 空 -> 漏网
        _turn(reply_text="这个系统有点问题", style_violations=[]),
    ])
    report = build_report(tmp_path)
    assert "系统" in report["potential_misses"]["term_dist"]
    assert report["potential_misses"]["examples"][0]["term"] == "系统"


def test_no_false_miss_when_violation_recorded(tmp_path):
    """reply 含词表词且 violations 非空 = 已拦截，不算漏网。"""
    _write(tmp_path, "aesir", "companion.alice", [
        _turn(reply_text="这个系统有点问题",
              style_violations=[{"category": "meta_term", "matched_term": "系统"}]),
    ])
    report = build_report(tmp_path)
    assert report["potential_misses"]["term_dist"] == {}


def test_candidate_extension_terms_scanned(tmp_path):
    """候选扩展词（不在现有词表）出现也计数。"""
    _write(tmp_path, "aesir", "companion.alice", [
        _turn(reply_text="我的算法是这样的", style_violations=[]),
        _turn(reply_text="神经网络很复杂", style_violations=[]),
    ])
    report = build_report(tmp_path)
    assert report["candidate_extension_hits"].get("算法") == 1
    assert report["candidate_extension_hits"].get("神经网络") == 1
