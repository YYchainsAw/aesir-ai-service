"""metrics_report 采集回归（T19 / Issue #32）。

覆盖 Issue 要求的五类布局 + 按游戏筛选 + 指标拆分：
旧布局、新布局、混合布局（同记录去重）、空目录、损坏行。
"""

from __future__ import annotations

import json

import pytest

from scripts import metrics_report as mr


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """把 receipts/signals 根目录指到临时目录，返回 (receipts_root, signals_root)。"""
    receipts_root = tmp_path / "executions"
    signals_root = tmp_path / "signals"
    receipts_root.mkdir()
    signals_root.mkdir()
    monkeypatch.setenv("AESIR_RECEIPTS_DIR", str(receipts_root))
    monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(signals_root))
    return receipts_root, signals_root


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            text = row if isinstance(row, str) else json.dumps(row, ensure_ascii=False)
            f.write(text + "\n")


def _receipt(order_id, result, received_at="2026-10-08T00:00:00+00:00"):
    return {"order_id": order_id, "result": result, "received_at": received_at}


def _signal(companion="companion.alice", ts="2026-10-08T00:00:00+00:00", reply="你好",
            source="llm", violations=None):
    return {
        "ts": ts, "companion_id": companion, "reply_text": reply, "source": source,
        "signals": {"negative_feedback": None, "topic_continued": None},
        "repetitive": False, "style_violations": violations,
    }


# ---- 旧布局（根目录）被采到 -------------------------------------------------

def test_legacy_layout_root_files_collected(isolated_dirs):
    receipts_root, signals_root = isolated_dirs
    _write(receipts_root / "20260924.jsonl", [_receipt("o1", "executed")])
    _write(signals_root / "companion.alice.jsonl", [_signal()])

    r, s = mr.collect_receipts(), mr.collect_signals()
    assert r["total_receipts"] == 1
    assert r["executed"] == 1
    assert s["total_turns"] == 1
    assert s["source_distribution"] == {"llm": 1}


# ---- 新布局（game_id 子目录）被采到（修复前为 0）----------------------------

def test_new_layout_game_subdir_collected(isolated_dirs):
    receipts_root, signals_root = isolated_dirs
    _write(receipts_root / "aesir" / "20261008.jsonl", [
        _receipt("o1", "executed"), _receipt("o2", "rejected"), _receipt("o3", "expired"),
    ])
    _write(signals_root / "demo-vn" / "companion.narrator.jsonl", [
        _signal(companion="companion.narrator", source="fallback"),
    ])

    r, s = mr.collect_receipts(), mr.collect_signals()
    assert r["total_receipts"] == 3
    assert r["executed"] == 1 and r["rejected"] == 1 and r["expired"] == 1
    assert s["total_turns"] == 1
    assert s["degradation_count"] == 1  # fallback 不再被漏


# ---- 混合布局：同一行写两份不重复统计；状态流转同 order_id 不被误杀 ----------

def test_mixed_layout_dedup_same_row_keeps_state_transitions(isolated_dirs):
    receipts_root, _ = isolated_dirs
    same = _receipt("o-same", "executed", "2026-10-08T00:00:00+00:00")
    # 同一行（同 order_id+result+received_at）写进旧根目录和新子目录两份。
    _write(receipts_root / "20260924.jsonl", [same])
    _write(receipts_root / "aesir" / "20261008.jsonl", [
        same,
        # 同一 order_id 的不同 result = 合法状态流转，必须都保留。
        _receipt("o-flow", "executed"), _receipt("o-flow", "rejected"),
    ])

    r = mr.collect_receipts()
    # o-same 只计一次；o-flow 的 executed+rejected 两条都在。
    assert r["total_receipts"] == 3
    assert r["executed"] == 2  # o-same + o-flow/executed
    assert r["rejected"] == 1  # o-flow/rejected


def test_mixed_signal_dedup(isolated_dirs):
    _, signals_root = isolated_dirs
    same = _signal(reply="同一句")
    _write(signals_root / "companion.alice.jsonl", [same])
    _write(signals_root / "aesir" / "companion.alice.jsonl", [same, _signal(reply="另一句")])

    s = mr.collect_signals()
    assert s["total_turns"] == 2  # 同一句去重一次 + 另一句


# ---- 空目录：比例字段为 None，不报 0.0 --------------------------------------

def test_empty_dir_reports_no_data(isolated_dirs):
    r, s = mr.collect_receipts(), mr.collect_signals()
    assert r["total_receipts"] == 0
    assert s["total_turns"] == 0
    assert s["topic_continuation_rate"] is None  # 无数据 → null，不是 0.0
    report = mr.build_report()
    assert report["games"] == []


# ---- 损坏行：可查、不中断、其余行仍统计 -------------------------------------

def test_corrupt_lines_reported_and_not_aborting(isolated_dirs):
    receipts_root, signals_root = isolated_dirs
    _write(receipts_root / "20260924.jsonl", [
        "这不是合法 JSON {{{",
        _receipt("o1", "executed"),
        "",  # 空行应被跳过，不算坏行
        "also broken",
    ])
    _write(signals_root / "companion.alice.jsonl", [
        "{{{",
        _signal(),
    ])

    r, s = mr.collect_receipts(), mr.collect_signals()
    assert r["total_receipts"] == 1  # 坏行跳过，好行仍统计
    assert r["executed"] == 1
    assert r["corrupt"] == {"20260924.jsonl": 2}  # 两行坏行可查
    assert s["total_turns"] == 1
    assert s["corrupt"] == {"companion.alice.jsonl": 1}


# ---- 按游戏筛选：不跨游戏混入 ----------------------------------------------

def test_game_filter_isolates_games(isolated_dirs):
    receipts_root, signals_root = isolated_dirs
    _write(receipts_root / "aesir" / "d.jsonl", [_receipt("o1", "executed")])
    _write(receipts_root / "demo-vn" / "d.jsonl", [_receipt("o2", "executed")])
    _write(signals_root / "aesir" / "companion.alice.jsonl", [_signal(companion="companion.alice")])
    _write(signals_root / "demo-vn" / "companion.narrator.jsonl", [
        _signal(companion="companion.narrator"),
    ])

    # 只采 demo-vn：回执只 o2、信号只 narrator，不混入 aesir。
    r = mr.collect_receipts(game="demo-vn")
    s = mr.collect_signals(game="demo-vn")
    assert r["total_receipts"] == 1
    assert s["total_turns"] == 1
    assert s["source_distribution"] == {"llm": 1}

    # aesir 筛选：不含 demo-vn 的回执。
    assert mr.collect_receipts(game="aesir")["total_receipts"] == 1


def test_game_filter_aesir_includes_legacy_root(isolated_dirs):
    """--game aesir 应同时包含旧根目录文件（历史语义）。"""
    receipts_root, _ = isolated_dirs
    _write(receipts_root / "20260924.jsonl", [_receipt("o-legacy", "executed")])
    _write(receipts_root / "aesir" / "d.jsonl", [_receipt("o-new", "executed")])
    _write(receipts_root / "demo-vn" / "d.jsonl", [_receipt("o-vn", "executed")])

    r = mr.collect_receipts(game="aesir")
    assert r["total_receipts"] == 2  # 旧根目录 + aesir 子目录，不含 demo-vn


# ---- 指标拆分：不再有合并的 suspicious_orders -----------------------------

def test_metrics_split_no_merged_suspicious(isolated_dirs):
    receipts_root, _ = isolated_dirs
    _write(receipts_root / "d.jsonl", [
        _receipt("o1", "executed"), _receipt("o2", "rejected"),
        _receipt("o3", "expired"), _receipt("o4", "cancelled"),
    ])
    r = mr.collect_receipts()
    for key in ("accepted", "executed", "rejected", "expired", "cancelled"):
        assert key in r
    assert "suspicious_orders" not in r  # 旧的合并字段已移除
    assert r["executed"] == 1 and r["rejected"] == 1
    assert r["expired"] == 1 and r["cancelled"] == 1
    assert "proxy_note" in r  # 真实越界下发的口径说明


def test_build_report_structure(isolated_dirs):
    receipts_root, signals_root = isolated_dirs
    _write(receipts_root / "aesir" / "d.jsonl", [_receipt("o1", "executed")])
    _write(signals_root / "demo-vn" / "n.jsonl", [_signal(source="fallback")])

    report = mr.build_report()
    assert report["scope"] == "all"
    assert set(report["games"]) == {"aesir", "demo-vn"}
    assert "receipts" in report and "dialogue_signals" in report
    assert "style_violations" in report
    assert "sc_verdicts" in report  # T32 / #41：SC 判定层


# ---- SC 判定层（T32 / Issue #41） -----------------------------------------

def _verdict_map(report: dict) -> dict[str, dict]:
    return {v["sc"]: v for v in report["sc_verdicts"]}


def test_sc009_pass_when_no_rejections(isolated_dirs):
    """回执全 executed → SC-009 PASS（越界下发=0 的运行期代理）。"""
    receipts_root, _ = isolated_dirs
    _write(receipts_root / "d.jsonl", [
        _receipt("o1", "executed"), _receipt("o2", "executed"),
    ])
    report = mr.build_report()
    v = _verdict_map(report)["SC-009"]
    assert v["status"] == "PASS"
    assert v["metric"] == 0


def test_sc009_fail_on_rejected_or_expired(isolated_dirs):
    """出现 rejected/expired/cancelled → SC-009 FAIL。"""
    receipts_root, _ = isolated_dirs
    _write(receipts_root / "d.jsonl", [
        _receipt("o1", "executed"), _receipt("o2", "rejected"),
        _receipt("o3", "expired"),
    ])
    report = mr.build_report()
    v = _verdict_map(report)["SC-009"]
    assert v["status"] == "FAIL"
    assert v["metric"] == 2  # rejected 1 + expired 1


def test_sc010_pass_when_no_fallback(isolated_dirs):
    """source 全 llm → SC-010 PASS。"""
    _, signals_root = isolated_dirs
    _write(signals_root / "companion.alice.jsonl", [_signal(source="llm")])
    report = mr.build_report()
    v = _verdict_map(report)["SC-010"]
    assert v["status"] == "PASS"
    assert v["metric"] == 0


def test_sc010_fail_on_fallback(isolated_dirs):
    """出现 fallback → SC-010 FAIL。"""
    _, signals_root = isolated_dirs
    _write(signals_root / "companion.alice.jsonl", [
        _signal(source="llm"),
        _signal(source="fallback", ts="2026-10-08T01:00:00+00:00", reply="回退话术"),
    ])
    report = mr.build_report()
    v = _verdict_map(report)["SC-010"]
    assert v["status"] == "FAIL"
    assert v["metric"] == 1


def test_sc012_pass_with_two_companions(isolated_dirs):
    """两个 companion 各有轮次 → SC-012 PASS。"""
    _, signals_root = isolated_dirs
    _write(signals_root / "companion.alice.jsonl", [_signal(companion="companion.alice")])
    _write(signals_root / "companion.bruno.jsonl", [_signal(companion="companion.bruno")])
    report = mr.build_report()
    v = _verdict_map(report)["SC-012"]
    assert v["status"] == "PASS"
    assert v["metric"] == 2


def test_sc_verdicts_na_when_no_data(isolated_dirs):
    """空目录 → 所有 SC 都是 N/A（不误报 PASS/FAIL）。"""
    report = mr.build_report()
    vmap = _verdict_map(report)
    # 四个可测项（SC-009/SC-010/风格违规/SC-012）都因无数据 → N/A
    for sc in ("SC-009", "SC-010", "风格违规", "SC-012"):
        assert vmap[sc]["status"] == "N/A", f"{sc} 空目录不应判 PASS/FAIL"
    # 10 个需新埋点的 SC 也是 N/A
    for sc in ("SC-001", "SC-002", "SC-003", "SC-004", "SC-005",
               "SC-006", "SC-007", "SC-008", "SC-011", "SC-013"):
        assert vmap[sc]["status"] == "N/A"
        assert vmap[sc]["note"]  # 必须写明要补什么埋点
