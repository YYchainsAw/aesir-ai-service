"""style_guard 词表定夺分析（#55 / T40）。

从 ``data/runtime/dialogue_signals/**/*.jsonl`` 抽 style_violations 相关字段，
产出词表定夺依据：已拦截的违规分布、潜在漏网词、候选扩展词频次。

用户用 chat_console 正常对话即自动攒数据（record_turn_signal 已落盘
style_violations）；本脚本离线分析，不跑对话、不调 LLM。

用法::

    .\\.venv\\Scripts\\python.exe -m scripts.style_regression_report
    .\\.venv\\Scripts\\python.exe -m scripts.style_regression_report --json
    .\\.venv\\Scripts\\python.exe -m scripts.style_regression_report --root data/runtime/dialogue_signals
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.companion.style_guard import get_style_policy

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "runtime" / "dialogue_signals"

# 候选扩展词表：现有 meta_terms 未收录但常见的出戏术语。
# 扫描 reply_text 出现频次，作为词表定夺的补充依据（不是自动加入）。
CANDIDATE_EXTENSION_TERMS = (
    "人工智能", "算法", "程序", "数据", "内存", "输出", "输入",
    "提示词", "prompt", "神经网络", "训练", "学习", "大脑",
    "终端", "屏幕", "按钮", "菜单", "选项", "鼠标", "键盘",
    "虚拟", "代码", "编程", "编译", "调试", "日志", "报错",
)


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
                        continue
        except OSError:
            continue


def build_report(root: Path) -> dict:
    policy = get_style_policy()
    total = 0
    by_companion: Counter[str] = Counter()
    by_scene: Counter[str] = Counter()

    # 已拦截违规（style_violations 非空）
    intercepted_categories: Counter[str] = Counter()
    intercepted_terms: Counter[str] = Counter()
    intercepted_examples: dict[str, list[str]] = {}

    # 潜在漏网：reply 含词表词但 violations 空（style_guard 应拦未拦）
    missed_terms: Counter[str] = Counter()
    missed_examples: list[dict] = []

    # 候选扩展词在 reply 里的出现频次（词表未收录但出现了）
    candidate_hits: Counter[str] = Counter()

    for path, rec in _iter_records(root):
        total += 1
        companion = rec.get("companion_id", path.stem)
        by_companion[companion] += 1
        by_scene[rec.get("game_state", "(empty)")] += 1

        reply = rec.get("reply_text", "") or ""
        violations = rec.get("style_violations") or []

        # 1. 已拦截
        for v in violations:
            cat = v.get("category", "?") if isinstance(v, dict) else "?"
            term = v.get("matched_term", "?") if isinstance(v, dict) else str(v)
            intercepted_categories[cat] += 1
            intercepted_terms[term] += 1
            intercepted_examples.setdefault(term, []).append(
                reply[:80]
            )

        # 2. 潜在漏网：reply 仍含词表词但 violations 空
        if not violations and reply:
            for term in policy.meta_terms | policy.forbidden_expressions:
                if term in reply:
                    missed_terms[term] += 1
                    if len(missed_examples) < 20:
                        missed_examples.append({
                            "term": term,
                            "companion": companion,
                            "scene": rec.get("game_state"),
                            "reply": reply[:120],
                        })

        # 3. 候选扩展词扫描（无论 violations 是否空）
        for term in CANDIDATE_EXTENSION_TERMS:
            if term.lower() in reply.lower():
                candidate_hits[term] += 1

    return {
        "total_turns": total,
        "by_companion": dict(by_companion),
        "by_scene": dict(by_scene),
        "intercepted": {
            "category_dist": dict(intercepted_categories),
            "term_dist": dict(intercepted_terms),
            "examples": {k: v[:3] for k, v in intercepted_examples.items()},
        },
        "potential_misses": {
            "term_dist": dict(missed_terms),
            "examples": missed_examples,
        },
        "candidate_extension_hits": dict(candidate_hits),
    }


def _utf8_stdio() -> None:
    """Windows 控制台默认 GBK：✅/⚠️ 等字符直接崩 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _print_human(report: dict) -> None:
    print("=== style_guard 词表定夺报告（#55 / T40）===")
    print(f"总轮数: {report['total_turns']}  按角色: {report['by_companion']}  按场景: {report['by_scene']}")
    print()
    print("--- 1. 已拦截违规（词表生效中）---")
    intc = report["intercepted"]
    if not intc["term_dist"]:
        print("  （无违规被拦截）")
    else:
        print(f"  category: {intc['category_dist']}")
        for term, n in sorted(intc["term_dist"].items(), key=lambda x: -x[1]):
            print(f"  拦截 {term!r} × {n}")
    print()
    print("--- 2. 潜在漏网（reply 含词表词但未被拦截）---")
    pm = report["potential_misses"]
    if not pm["term_dist"]:
        print("  （无漏网）")
    else:
        for term, n in sorted(pm["term_dist"].items(), key=lambda x: -x[1]):
            print(f"  漏网 {term!r} × {n}")
        print("  样例:")
        for ex in pm["examples"][:5]:
            print(f"    [{ex['term']}] {ex['reply']!r}")
    print()
    print("--- 3. 候选扩展词在 reply 出现频次（词表未收录）---")
    ch = report["candidate_extension_hits"]
    if not ch:
        print("  （候选词均未出现）")
    else:
        for term, n in sorted(ch.items(), key=lambda x: -x[1]):
            print(f"  {term!r} × {n}")
    print()
    print("=== 定夺依据 ===")
    if report["total_turns"] < 26:
        print(f"⚠️  当前 {report['total_turns']} 轮，未达 26 轮回归门槛。")
        print("   用 chat_console 正常对话攒数据（自动落盘），达标后重跑本报告。")
    else:
        print(f"✅ 已达 {report['total_turns']} 轮门槛。")
        print("   结合以上三类分布，决定词表：拦截分布正常、漏网清零、候选词无显著出现 = 词表定夺。")


def main() -> None:
    parser = argparse.ArgumentParser(description="style_guard 词表定夺分析")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT, help="信号根目录")
    args = parser.parse_args()

    _utf8_stdio()
    report = build_report(args.root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)


if __name__ == "__main__":
    main()
