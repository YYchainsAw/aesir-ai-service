"""验收指标采集脚本（SDD US7 / T079）。

统计既有落盘数据中可测的验收指标，输出一页报告：

- 执行回执（data/runtime/command_service/executions/*.jsonl）：
  回执总数、result 分布、越界可疑（rejected/failed 计数）。
- 对话信号（data/runtime/dialogue_signals/*.jsonl）：
  轮次总数、后端分布（llm / mock / fallback）、降级次数（fallback）、
  复读轮数（repetitive=true）、负反馈次数、话题延续率。
- 重复响应：幂等重复在响应内标记（duplicate=true），不落盘——此处以
  「重复回复检测」（repetitive）作为可测代理指标。
- 风格违规：style_guard（T083）尚未实现，如实报告「暂无数据源」。

用法：
    .venv/Scripts/python -m scripts.metrics_report
    .venv/Scripts/python -m scripts.metrics_report --json   # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

# Windows 终端默认 GBK，中文输出会乱码
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue  # 损坏行跳过：指标统计不因个别坏行中断


def collect_receipts() -> dict:
    receipts_dir = ROOT / "data" / "runtime" / "command_service" / "executions"
    total = 0
    results: Counter = Counter()
    for path in sorted(receipts_dir.glob("*.jsonl")):
        for record in _iter_jsonl(path):
            total += 1
            results[record.get("result", "unknown")] += 1
    return {
        "files": len(list(receipts_dir.glob("*.jsonl"))),
        "total_receipts": total,
        "result_distribution": dict(results),
        # 越界/失败的可测代理：rejected + failed 计数（真正「越界下发」
        # 由战术回归集断言为 0，此处为运行期数据佐证）
        "suspicious_orders": results.get("rejected", 0) + results.get("failed", 0),
    }


def collect_signals() -> dict:
    signals_dir = ROOT / "data" / "runtime" / "dialogue_signals"
    total = 0
    sources: Counter = Counter()
    repetitive = 0
    negative = 0
    topic_continued_true = 0
    topic_continued_known = 0
    for path in sorted(signals_dir.glob("*.jsonl")):
        for record in _iter_jsonl(path):
            total += 1
            sources[record.get("source", "unknown")] += 1
            if record.get("repetitive"):
                repetitive += 1
            signals = record.get("signals") or {}
            if signals.get("negative_feedback"):
                negative += 1
            continued = signals.get("topic_continued")
            if continued is not None:
                topic_continued_known += 1
                if continued:
                    topic_continued_true += 1
    return {
        "files": len(list(signals_dir.glob("*.jsonl"))),
        "total_turns": total,
        "source_distribution": dict(sources),
        "degradation_count": sources.get("fallback", 0),
        "repetitive_replies": repetitive,
        "negative_feedback": negative,
        "topic_continuation_rate": (
            round(topic_continued_true / topic_continued_known, 3)
            if topic_continued_known else None
        ),
    }


def build_report() -> dict:
    return {
        "receipts": collect_receipts(),
        "dialogue_signals": collect_signals(),
        "style_violations": "暂无数据源（style_guard 为 SDD T083，尚未实现）",
        "duplicate_responses": "幂等重复在响应内标记（duplicate=true），不落盘；"
                               "复读轮数见 dialogue_signals.repetitive_replies",
    }


def _print_report(report: dict) -> None:
    r, s = report["receipts"], report["dialogue_signals"]
    print("=" * 56)
    print("Aesir 验收指标报告（US7 / T079）")
    print("=" * 56)
    print("\n[执行回执]")
    print(f"  回执总数: {r['total_receipts']}（{r['files']} 个 JSONL 文件）")
    print(f"  result 分布: {r['result_distribution'] or '（无数据）'}")
    print(f"  可疑指令（rejected+failed）: {r['suspicious_orders']}")
    print("\n[对话信号]")
    print(f"  轮次总数: {s['total_turns']}（{s['files']} 个角色文件）")
    print(f"  后端分布: {s['source_distribution'] or '（无数据）'}")
    print(f"  降级次数（fallback）: {s['degradation_count']}")
    print(f"  复读轮数: {s['repetitive_replies']}")
    print(f"  负反馈次数: {s['negative_feedback']}")
    print(f"  话题延续率: {s['topic_continuation_rate']}")
    print("\n[风格违规]")
    print(f"  {report['style_violations']}")
    print("\n[重复响应]")
    print(f"  {report['duplicate_responses']}")
    print("=" * 56)


def main() -> int:
    parser = argparse.ArgumentParser(description="验收指标采集（US7 / T079）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
