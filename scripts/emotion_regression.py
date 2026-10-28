"""情感桶回归回放：标准种子 → 喂 chat 端点 → 对比 LLM 判定 vs 期望桶。

用途：新人格 yaml 出场验收。换人格后跑同一批种子，输出混淆矩阵——
判定桶与期望桶对角线命中率 ≥80% 视为合格。

用法：
    .venv/Scripts/python -m scripts.emotion_regression                  # 跑全部 75 条
    .venv/Scripts/python -m scripts.emotion_regression --bucket deep     # 只跑某一桶
    .venv/Scripts/python -m scripts.emotion_regression --limit 5        # 每桶限 5 条（快速冒烟）

前置：.env 需有真实 LLM 配置（COMPANION_BACKEND=llm + API key）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

# Windows GBK 控制台中文乱码防护（与 style_regression_report 同套路）
for stream in (sys.stdout, sys.stderr):
    if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
        stream.reconfigure(encoding="utf-8", errors="replace")

SEEDS_PATH = Path(__file__).resolve().parents[1] / "data" / "test_scripts" / "emotion_seeds.json"
SIGNALS_PATH = Path(__file__).resolve().parents[1] / "data" / "runtime" / "dialogue_signals" / "aesir" / "companion.alice.jsonl"

BUCKETS = ("deep", "warm", "cold", "hurtful", "none")


def load_seeds(bucket: str | None, limit: int | None) -> list[dict]:
    data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    seeds = data["seeds"]
    if bucket:
        seeds = [s for s in seeds if s["expected"] == bucket]
    if limit:
        # 每桶取前 limit 条
        by_bucket: dict[str, list[dict]] = defaultdict(list)
        for s in seeds:
            by_bucket[s["expected"]].append(s)
        seeds = []
        for b in BUCKETS:
            seeds.extend(by_bucket[b][:limit])
    return seeds


def run(client: TestClient, seeds: list[dict]) -> list[dict]:
    """逐条喂 chat，返回每条的 response 摘要。"""
    results = []
    for i, seed in enumerate(seeds, 1):
        session_id = str(uuid.uuid4())  # 每条独立 session，避免会话记忆串
        t0 = time.time()
        r = client.post(
            "/v1/companion/chat",
            json={"text": seed["input"], "session_id": session_id, "companion_id": "companion.alice"},
            timeout=90.0,
        )
        elapsed = time.time() - t0
        if r.status_code != 200:
            print(f"  [{i}/{len(seeds)}] FAIL {r.status_code}: {r.text[:120]}")
            results.append({"input": seed["input"], "expected": seed["expected"],
                            "error": f"HTTP {r.status_code}", "elapsed": elapsed})
            continue
        body = r.json()
        results.append({
            "input": seed["input"],
            "expected": seed["expected"],
            "reply_text": body.get("reply_text", "")[:80],
            "source": body.get("source"),
            "emotion_id": body.get("emotion_id"),
            "relationship_delta": body.get("relationship_delta"),
            "elapsed": elapsed,
        })
        print(f"  [{i}/{len(seeds)}] {seed['expected']:8s} -> {body.get('source','?'):8s} "
              f"delta={body.get('relationship_delta',0):+d} ({elapsed:.1f}s)")
    return results


def read_signals(since_line: int) -> list[dict]:
    """读 signals 文件从 since_line 开始的新增行。"""
    if not SIGNALS_PATH.exists():
        return []
    lines = SIGNALS_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines[since_line:] if l.strip()]


def report(results: list[dict], signals: list[dict]) -> None:
    """对比 expected vs LLM 判定 sentiment，输出混淆矩阵。"""
    # 按 player_text 匹配 signals
    sig_by_text = {s["player_text"]: s for s in signals if "player_text" in s}

    # 混淆矩阵：行=期望，列=判定
    confusion: dict[str, Counter] = {b: Counter() for b in BUCKETS}
    unmatched = 0
    for r in results:
        sig = sig_by_text.get(r["input"])
        if sig is None:
            unmatched += 1
            continue
        judged = sig.get("sentiment", "none")
        confusion[r["expected"]][judged] += 1

    print("\n" + "=" * 60)
    print("混淆矩阵（行=期望桶，列=LLM 判定桶）")
    print("=" * 60)
    header = f"{'期望＼判定':>10s} |" + "".join(f"{b:>8s}" for b in BUCKETS) + f"{'  命中':>6s}"
    print(header)
    print("-" * len(header))
    total_correct = 0
    total = 0
    for expected in BUCKETS:
        row = confusion[expected]
        correct = row[expected]
        n = sum(row.values())
        total_correct += correct
        total += n
        pct = f"{correct/n*100:.0f}%" if n else "-"
        line = f"{expected:>10s} |" + "".join(f"{row[b]:>8d}" for b in BUCKETS) + f"{pct:>7s}"
        print(line)
    print("-" * len(header))
    overall = f"{total_correct/total*100:.0f}%" if total else "-"
    print(f"{'总体命中':>10s} |{'':>40s}{overall:>7s}  ({total_correct}/{total})")
    if unmatched:
        print(f"\n⚠ {unmatched} 条未匹配到 signals（可能被 style_guard 拦截未落盘）")

    # 误判详情
    print("\n误判详情（期望 ≠ 判定）：")
    for r in results:
        sig = sig_by_text.get(r["input"])
        if sig is None:
            print(f"  [无信号] {r['expected']:8s} | {r['input'][:30]}")
            continue
        judged = sig.get("sentiment", "none")
        if judged != r["expected"]:
            print(f"  {r['expected']:8s} -> {judged:8s} | {r['input'][:30]} "
                  f"| delta={sig.get('relationship_delta',0):+d}({sig.get('relationship_reason','?')})")

    # relationship_delta 统计
    print("\nrelationship_delta 分布：")
    delta_by_bucket: dict[str, list[int]] = defaultdict(list)
    for r in results:
        sig = sig_by_text.get(r["input"])
        if sig:
            delta_by_bucket[r["expected"]].append(sig.get("relationship_delta", 0))
    for b in BUCKETS:
        deltas = delta_by_bucket[b]
        if deltas:
            scored = sum(1 for d in deltas if d != 0)
            print(f"  {b:8s}: {len(deltas)} 条, 计分 {scored} 条, "
                  f"delta 分布 {dict(Counter(deltas))}")


def main():
    parser = argparse.ArgumentParser(description="情感桶回归回放")
    parser.add_argument("--bucket", choices=BUCKETS, default=None, help="只跑指定桶")
    parser.add_argument("--limit", type=int, default=None, help="每桶限 N 条（快速冒烟）")
    args = parser.parse_args()

    seeds = load_seeds(args.bucket, args.limit)
    print(f"加载 {len(seeds)} 条种子（bucket={args.bucket or 'all'}, limit={args.limit}）")

    # 记录 signals 文件当前行数，跑完只读新增
    baseline_lines = len(SIGNALS_PATH.read_text(encoding="utf-8").splitlines()) if SIGNALS_PATH.exists() else 0
    print(f"signals 基线行: {baseline_lines}")

    from app.main import app
    client = TestClient(app)
    print("开始回放...\n")
    results = run(client, seeds)

    print("\n读取 signals...")
    signals = read_signals(baseline_lines)
    print(f"本次新增 signals: {len(signals)} 条")

    report(results, signals)


if __name__ == "__main__":
    main()
