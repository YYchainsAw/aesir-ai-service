"""离线对话信号评估报告（#54 / T39 切片 A）。

扫 ``data/runtime/dialogue_signals/<game_id>/<companion_id>.jsonl``，把埋点里
「以为有信号」变成可见数字：reward 触发率、context 分桶样本数、sentiment vs
relationship_reason 分布。不接在线学习、不改对话主流程。

用法::

    .\\.venv\\Scripts\\python.exe -m scripts.rl.dialogue_signal_report
    .\\.venv\\Scripts\\python.exe -m scripts.rl.dialogue_signal_report --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 不依赖 get_settings()：本地默认 coordination_backend=redis 与 scope_storage=json
# 触发硬边界校验直接抛错。报告脚本自包含，默认扫项目相对路径。
_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "runtime" / "dialogue_signals"


def _iter_records(root: Path):
    for path in sorted(root.glob("*/*.jsonl")):
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield path, json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 坏行跳过，不阻塞报告
        except OSError:
            continue


def _percent(part: int, total: int) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def build_report(root: Path) -> dict:
    total = 0
    by_companion: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    sentiments: Counter[str] = Counter()
    rel_reasons: Counter[str] = Counter()
    rel_stages: Counter[str] = Counter()
    game_states: Counter[str] = Counter()
    buckets: Counter[tuple[str, str]] = Counter()  # (relationship_stage, game_state)

    neg_hits = 0
    repetitive_hits = 0
    style_viol_hits = 0
    rel_delta_nonzero = 0
    memory_cited_true = 0
    memory_cited_false = 0
    earliest_ts: str | None = None
    latest_ts: str | None = None

    for path, rec in _iter_records(root):
        total += 1
        by_companion[rec.get("companion_id", path.stem)] += 1
        sources[rec.get("source", "unknown")] += 1

        ts = rec.get("ts")
        if ts:
            earliest_ts = ts if earliest_ts is None or ts < earliest_ts else earliest_ts
            latest_ts = ts if latest_ts is None or ts > latest_ts else latest_ts

        signals = rec.get("signals") or {}
        if signals.get("negative_feedback") is not None:
            neg_hits += 1
        if rec.get("repetitive"):
            repetitive_hits += 1
        sv = rec.get("style_violations") or []
        if sv:
            style_viol_hits += 1
        if rec.get("relationship_delta", 0) != 0:
            rel_delta_nonzero += 1
        mc = rec.get("memory_cited")
        if mc is True:
            memory_cited_true += 1
        elif mc is False:
            memory_cited_false += 1

        sentiments[rec.get("sentiment", "none") or "none"] += 1
        rel_reasons[rec.get("relationship_reason", "none") or "none"] += 1
        stage = rec.get("relationship_stage", "") or "(empty)"
        rel_stages[stage] += 1
        gs = rec.get("game_state", "") or "(empty)"
        game_states[gs] += 1
        buckets[(stage, gs)] += 1

    return {
        "total_records": total,
        "span": {"earliest": earliest_ts, "latest": latest_ts},
        "by_companion": dict(by_companion),
        "sources": dict(sources),
        "reward_signal_rates": {
            "negative_feedback_hit_pct": _percent(neg_hits, total),
            "repetitive_pct": _percent(repetitive_hits, total),
            "style_violation_pct": _percent(style_viol_hits, total),
            "relationship_delta_nonzero_pct": _percent(rel_delta_nonzero, total),
            "memory_cited_true_pct": _percent(memory_cited_true, total),
            "memory_cited_false_pct": _percent(memory_cited_false, total),
        },
        "reward_event_counts": {
            "negative_feedback": neg_hits,
            "repetitive": repetitive_hits,
            "style_violation": style_viol_hits,
            "relationship_delta_nonzero": rel_delta_nonzero,
            "memory_cited_true": memory_cited_true,
            "memory_cited_false": memory_cited_false,
        },
        "sentiment_dist": dict(sentiments),
        "relationship_reason_dist": dict(rel_reasons),
        "relationship_stage_dist": dict(rel_stages),
        "game_state_dist": dict(game_states),
        "stage_x_state_buckets": {f"{s} | {g}": n for (s, g), n in sorted(buckets.items())},
    }


def _print_human(report: dict) -> None:
    print("=== 对话信号离线报告（#54 切片 A）===")
    print(f"总样本: {report['total_records']}  跨度: {report['span']['earliest']} ~ {report['span']['latest']}")
    print(f"按角色: {report['by_companion']}")
    print(f"source 分布: {report['sources']}")
    print()
    print("--- reward 触发率（bandit 正负例来源）---")
    for k, v in report["reward_signal_rates"].items():
        print(f"  {k}: {v}%")
    print()
    print("--- sentiment 分布 ---")
    print(f"  {report['sentiment_dist']}")
    print("--- relationship_reason 分布 ---")
    print(f"  {report['relationship_reason_dist']}")
    print()
    print("--- context 分桶（relationship_stage × game_state）---")
    for k, v in report["stage_x_state_buckets"].items():
        print(f"  {k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description="对话信号离线评估报告")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument(
        "--root", type=Path, default=_DEFAULT_ROOT,
        help=f"信号根目录（默认 {_DEFAULT_ROOT}）",
    )
    args = parser.parse_args()

    root = args.root
    report = build_report(root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)


if __name__ == "__main__":
    main()
