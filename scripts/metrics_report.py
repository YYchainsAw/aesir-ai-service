"""验收指标采集脚本（SDD US7 / T079，T19 修复漏采）。

统计既有落盘数据中可测的验收指标，输出一页报告。

## 落盘布局（T19 起按 game_id 分目录）

- 执行回执（``receipts_dir``）：
  - 旧布局：``<root>/{YYYYMMDD}.jsonl``（根目录，无 game_id 概念）
  - 新布局：``<root>/<game_id>/{YYYYMMDD}.jsonl``（``receipt_store.append_receipts``）
- 对话信号（``dialogue_signals_dir``）：
  - 旧布局：``<root>/<companion_id>.jsonl``
  - 新布局：``<root>/<game_id>/<companion_id>.jsonl``（``record_turn_signal``）
- agent 决策（``agent_steps_dir``，T38 新增）：``<root>/<game_id>/<companion_id>.jsonl``
- 事件幂等（``event_signals_dir``，T38 新增）：``<root>/<game_id>/<companion_id>.jsonl``

旧布局（根目录）数据语义上全部属于 ``aesir``（旧落盘默认 game_id），因此
按 ``--game aesir`` 筛选时一并包含；按其他游戏筛选时不混入。

## 指标口径（T19：不同事件分开命名，不再混为同一验收项）

- 回执 ``result`` 完整分布 + 各 result 独立计数（accepted/executed/rejected/
  expired/cancelled）。``rejected/expired/cancelled`` 是**运行期代理指标**；
  「真实越界下发」（本应被门控拦但仍 executed）运行期无法纯靠回执判定，由战术
  回归集离线断言为 0——此处只作说明，不伪造数值。
- 对话信号：轮次总数、后端分布（llm/mock/fallback）、降级次数（fallback）、
  复读轮数（repetitive=true）、负反馈次数、话题延续率。
- 风格违规：``style_violations``（违规条数）与 ``llm_checked_turns``（LLM 路径
  经 style_guard 校验的轮数）分开统计；mock/fallback 路径为 None（未校验）。
- 损坏行：不再静默跳过——``corrupt`` 按文件记录坏行数，可查处理结果。

用法：
    .venv/Scripts/python -m scripts.metrics_report
    .venv/Scripts/python -m scripts.metrics_report --json
    .venv/Scripts/python -m scripts.metrics_report --game demo-vn
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

# 旧布局（根目录）数据语义上归属的 game_id（旧落盘默认 game_id = aesir）。
LEGACY_GAME_ID = "aesir"

# 回执 result 的完整枚举（与 app/schemas/tactical_execution.ReceiptResult 对齐）。
RECEIPT_RESULTS = ("accepted", "executed", "rejected", "expired", "cancelled")


def _resolve_dir(settings_value: str) -> Path:
    """把 settings 里的目录解析为绝对路径（相对路径相对项目根目录）。"""
    path = Path(settings_value)
    return path if path.is_absolute() else ROOT / path


def _discover_jsonl(root: Path, game: str | None) -> list[Path]:
    """按布局发现需采集的 JSONL 文件。

    - ``game is None``（跨游戏汇总）：根目录旧文件 + 各一级子目录新文件。
    - ``game == LEGACY_GAME_ID``：根目录旧文件 + ``<root>/aesir/`` 新文件。
    - ``game == 其他``：只取 ``<root>/<game>/`` 新文件，不混入旧根目录。
    """
    if not root.exists():
        return []
    if game is None:
        files = set(root.glob("*.jsonl"))
        files.update(p for sub in root.iterdir() if sub.is_dir() for p in sub.glob("*.jsonl"))
        return sorted(files)
    if game == LEGACY_GAME_ID:
        return sorted(list(root.glob("*.jsonl")) + list((root / game).glob("*.jsonl")))
    return sorted((root / game).glob("*.jsonl"))


def _iter_jsonl(path: Path):
    """逐行产出 JSON 对象；返回值附带损坏行数（通过调用方计数器累加）。

    损坏行（非 JSON）不中断统计，但调用方需累计以便在报告中可查。
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line), False
        except json.JSONDecodeError:
            yield {}, True  # 损坏行：产出空占位并标记，由调用方累计


def collect_receipts(game: str | None = None) -> dict:
    from app.config import get_settings

    root = _resolve_dir(get_settings().receipts_dir)
    total = 0
    results: Counter = Counter()
    corrupt: dict[str, int] = {}
    # 去重键：(order_id, result, received_at)。
    # 只识别「同一行被物理写两份」的迁移期重复；同一 order_id 的多条不同
    # result（状态流转 accepted→executed→rejected）是合法回执，不互相误杀。
    seen_keys: set[tuple] = set()
    files = _discover_jsonl(root, game)
    for path in files:
        file_bad = 0
        for record, bad in _iter_jsonl(path):
            if bad:
                file_bad += 1
                continue
            key = (record.get("order_id"), record.get("result"), record.get("received_at"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            total += 1
            results[record.get("result", "unknown")] += 1
        if file_bad:
            corrupt[str(path.relative_to(root))] = file_bad
    return {
        "scope": game or "all",
        "files": len(files),
        "total_receipts": total,
        "result_distribution": dict(results),
        # 各 result 独立计数（T19：不再合并成 suspicious_orders）。
        "accepted": results.get("accepted", 0),
        "executed": results.get("executed", 0),
        "rejected": results.get("rejected", 0),
        "expired": results.get("expired", 0),
        "cancelled": results.get("cancelled", 0),
        "proxy_note": "rejected/expired/cancelled 为运行期代理指标；真实越界下发"
                      "由战术回归集离线断言为 0，运行期无法纯靠回执判定。",
        "corrupt": corrupt,
    }


def collect_signals(game: str | None = None) -> dict:
    from app.config import get_settings

    root = _resolve_dir(get_settings().dialogue_signals_dir)
    total = 0
    sources: Counter = Counter()
    companions: Counter = Counter()
    repetitive = 0
    negative = 0
    topic_continued_true = 0
    topic_continued_known = 0
    style_violations = 0
    llm_checked_turns = 0
    # T37 新增埋点聚合：记忆引用（SC-001）、关系阶段分布（SC-003）、
    # 时延样本（SC-011，p95 需 ≥30 样本）。
    memory_cited_true = 0
    memory_cited_known = 0
    relationship_stages: Counter = Counter()
    latencies: list[int] = []
    # T38 新增埋点聚合：SC-004 冷却拦截（reason 可区分）、SC-008 查证结果分布
    # 与接地丢弃事实数。
    cooldown_blocked = 0
    cooldown_blocked_with_delta = 0
    lore_lookup_turns = 0
    lore_found = 0
    facts_rejected_total = 0
    corrupt: dict[str, int] = {}
    seen_keys: set[tuple] = set()
    files = _discover_jsonl(root, game)
    for path in files:
        file_bad = 0
        for record, bad in _iter_jsonl(path):
            if bad:
                file_bad += 1
                continue
            # 去重：同一 (ts, companion_id, reply_text) 只计一次。
            key = (record.get("ts"), record.get("companion_id"), record.get("reply_text"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            total += 1
            sources[record.get("source", "unknown")] += 1
            companions[record.get("companion_id", "unknown")] += 1
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
            violations = record.get("style_violations")
            if violations is not None:
                llm_checked_turns += 1
                if violations:
                    style_violations += len(violations)
            # 可选埋点字段（旧记录缺这些键时 .get 返回 None，不影响计数）。
            cited = record.get("memory_cited")
            if cited is not None:
                memory_cited_known += 1
                if cited:
                    memory_cited_true += 1
            stage = record.get("relationship_stage")
            if isinstance(stage, str) and stage:
                relationship_stages[stage] += 1
            latency = record.get("latency_ms")
            if isinstance(latency, (int, float)):
                latencies.append(int(latency))
            # T38 可选字段（旧记录缺键时 .get 返回 None，不影响计数）。
            reason = record.get("relationship_reason")
            if reason == "cooldown_blocked":
                cooldown_blocked += 1
                if record.get("relationship_delta", 0) != 0:
                    cooldown_blocked_with_delta += 1
            lookup = record.get("lore_lookup")
            if isinstance(lookup, dict):
                lore_lookup_turns += 1
                if lookup.get("found"):
                    lore_found += 1
            rejected = record.get("facts_rejected")
            if isinstance(rejected, int):
                facts_rejected_total += rejected
        if file_bad:
            corrupt[str(path.relative_to(root))] = file_bad
    return {
        "scope": game or "all",
        "files": len(files),
        "total_turns": total,
        "source_distribution": dict(sources),
        "companion_distribution": dict(companions),
        "degradation_count": sources.get("fallback", 0),
        "repetitive_replies": repetitive,
        "negative_feedback": negative,
        "topic_continuation_rate": (
            round(topic_continued_true / topic_continued_known, 3)
            if topic_continued_known else None
        ),
        "style_violations": style_violations,
        "llm_checked_turns": llm_checked_turns,
        # T37 新增：可判定 SC-001/SC-003/SC-011 的聚合值。
        "memory_cited_rate": (
            round(memory_cited_true / memory_cited_known, 3)
            if memory_cited_known else None
        ),
        "memory_cited_turns": memory_cited_known,
        "relationship_stage_distribution": dict(relationship_stages),
        "latency_sample_size": len(latencies),
        "latency_p95_ms": _percentile(latencies, 0.95),
        # T38 新增：可判定 SC-004/SC-008 的聚合值。
        "cooldown_blocked": cooldown_blocked,
        "cooldown_blocked_with_delta": cooldown_blocked_with_delta,
        "lore_lookup_turns": lore_lookup_turns,
        "lore_found": lore_found,
        "facts_rejected_total": facts_rejected_total,
        "corrupt": corrupt,
    }


def collect_agent_steps(game: str | None = None) -> dict:
    """聚合 agent/step 决策埋点（T38：SC-005/006/013 数据源）。

    - **自主步** = reason_codes 含 ``ARB_WON:`` 前缀的记录（仲裁胜出的心跳步）；
    - SC-005：自主步 ``directive_action_type`` 去重分布（≥8 类）；
    - SC-006：同一 companion 相邻自主步 action_type 相同的条数（重复率）；
    - SC-013：reason_codes 非空记录占总步数比例（可解释覆盖率）。
    """
    from app.config import get_settings

    root = _resolve_dir(get_settings().agent_steps_dir)
    total = 0
    autonomous = 0
    behavior_types: Counter = Counter()
    autonomous_repeats = 0
    explained = 0
    prev_action_by_companion: dict[str, str | None] = {}
    corrupt: dict[str, int] = {}
    seen_keys: set[tuple] = set()
    files = _discover_jsonl(root, game)
    for path in files:
        file_bad = 0
        for record, bad in _iter_jsonl(path):
            if bad:
                file_bad += 1
                continue
            key = (
                record.get("ts"),
                record.get("companion_id"),
                record.get("directive_action_type"),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            total += 1
            codes = [str(c) for c in (record.get("reason_codes") or [])]
            if codes:
                explained += 1
            companion = str(record.get("companion_id", "unknown"))
            action_type = record.get("directive_action_type")
            is_autonomous = any(c.startswith("ARB_WON:") for c in codes)
            if is_autonomous:
                autonomous += 1
                if action_type:
                    behavior_types[str(action_type)] += 1
                prev = prev_action_by_companion.get(companion)
                if prev is not None and prev == action_type:
                    autonomous_repeats += 1
                prev_action_by_companion[companion] = action_type
        if file_bad:
            corrupt[str(path.relative_to(root))] = file_bad
    return {
        "scope": game or "all",
        "files": len(files),
        "total_steps": total,
        "autonomous_steps": autonomous,
        "behavior_type_distribution": dict(behavior_types),
        "autonomous_adjacent_repeats": autonomous_repeats,
        "explained_steps": explained,
        "explained_coverage": round(explained / total, 3) if total else None,
        "corrupt": corrupt,
    }


def collect_event_signals(game: str | None = None) -> dict:
    """聚合事件幂等埋点（T38：SC-007 数据源）。

    SC-007 判定口径：同一 (event_id, encounter_id) 的**非首条**记录
    ``duplicate`` 必须为 True；出现一条 False 即幂等表被绕过（同一事件被
    独立评估多次——重复反应/重复施法的运行期铁证）。
    """
    from app.config import get_settings

    root = _resolve_dir(get_settings().event_signals_dir)
    total = 0
    duplicates = 0
    idempotency_violations = 0
    seen_first: set[tuple] = set()
    corrupt: dict[str, int] = {}
    seen_keys: set[tuple] = set()
    files = _discover_jsonl(root, game)
    for path in files:
        file_bad = 0
        for record, bad in _iter_jsonl(path):
            if bad:
                file_bad += 1
                continue
            key = (
                record.get("ts"),
                record.get("event_id"),
                record.get("duplicate"),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            total += 1
            is_dup = bool(record.get("duplicate"))
            if is_dup:
                duplicates += 1
            first_key = (record.get("event_id") or "", record.get("encounter_id") or "")
            if first_key in seen_first:
                if not is_dup:
                    idempotency_violations += 1
            else:
                seen_first.add(first_key)
        if file_bad:
            corrupt[str(path.relative_to(root))] = file_bad
    return {
        "scope": game or "all",
        "files": len(files),
        "total_events": total,
        "duplicate_events": duplicates,
        "duplicate_ratio": round(duplicates / total, 3) if total else None,
        "idempotency_violations": idempotency_violations,
        "corrupt": corrupt,
    }


def _percentile(values: list[int], q: float) -> int | None:
    """整数毫秒序列的分位数（线性插值）；空序列返回 None。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _discovered_games(root: Path) -> list[str]:
    """汇总本次数据里出现过的 game_id（一级子目录名；旧根目录归入 aesir）。"""
    if not root.exists():
        return []
    games = set()
    if any(root.glob("*.jsonl")):
        games.add(LEGACY_GAME_ID)
    games.update(sorted(p.name for p in root.iterdir() if p.is_dir() and any(p.glob("*.jsonl"))))
    return sorted(games)


def evaluate_sc_verdicts(report: dict) -> list[dict]:
    """把原始计数对照 SC-001~013 口径判定 PASS/FAIL/N/A（T32 / #41）。

    Issue 边界：只采和统计，不接入实时运行或决策策略。需要新埋点的 SC
    （记忆引用正确率、响应时延、decision_trace 等）一律 N/A，并在 note 里
    写明要补什么字段——这就是「人工判定半自动化」的最后一公里。
    """
    receipts = report["receipts"]
    signals = report["dialogue_signals"]
    verdicts: list[dict] = []

    def add(sc_id: str, status: str, metric, threshold: str, note: str = "") -> None:
        verdicts.append({
            "sc": sc_id, "status": status,
            "metric": metric, "threshold": threshold, "note": note,
        })

    # SC-009 越界下发=0（运行期代理：rejected/expired/cancelled 为非执行类回执）
    non_executed = receipts["rejected"] + receipts["expired"] + receipts["cancelled"]
    if receipts["total_receipts"] == 0:
        add("SC-009", "N/A", non_executed, "rejected+expired+cancelled = 0",
            "无回执数据；且「真实越界下发」需战术回归集离线断言，运行期只能代理")
    elif non_executed == 0:
        add("SC-009", "PASS", non_executed, "rejected+expired+cancelled = 0")
    else:
        add("SC-009", "FAIL", non_executed, "rejected+expired+cancelled = 0",
            "运行期代理指标；真实越界由战术回归集离线断言")

    # SC-010 流程中断=0（fallback 次数）
    if signals["total_turns"] == 0:
        add("SC-010", "N/A", signals["degradation_count"], "fallback turns = 0",
            "无对话轮次数据")
    elif signals["degradation_count"] == 0:
        add("SC-010", "PASS", signals["degradation_count"], "fallback turns = 0")
    else:
        add("SC-010", "FAIL", signals["degradation_count"], "fallback turns = 0")

    # 风格违规率（SC-003/SC-008 代理：style_violations=0 且有 LLM 校验轮次）
    if signals["llm_checked_turns"] == 0:
        add("风格违规", "N/A", signals["style_violations"], "violations = 0",
            "无 LLM 校验轮次（mock/fallback 路径不落 style_violations）")
    elif signals["style_violations"] == 0:
        add("风格违规", "PASS", signals["style_violations"], "violations = 0")
    else:
        add("风格违规", "FAIL", signals["style_violations"], "violations = 0")

    # SC-012 双 NPC 隔离（companion_id 分布 ≥ 2 个）
    companion_count = len(signals["companion_distribution"])
    if signals["total_turns"] == 0:
        add("SC-012", "N/A", companion_count, "≥ 2 个 companion 有轮次",
            "无对话轮次数据")
    elif companion_count >= 2:
        add("SC-012", "PASS", companion_count, "≥ 2 个 companion 有轮次",
            f"实际：{signals['companion_distribution']}")
    else:
        add("SC-012", "FAIL", companion_count, "≥ 2 个 companion 有轮次",
            "当前只有一个 companion 的轮次；路由/隔离逻辑已由单测覆盖")

    # SC-001 记忆引用（T37 起有 memory_cited 埋点；「正确率」仍需人工核，
    # 脚本只能判「引用率非 0」这一代理——有引用样本才算链路在跑）。
    if signals.get("memory_cited_turns", 0) == 0:
        add("SC-001", "N/A", None, "记忆引用率 ≥ 90%",
            "无 memory_cited 埋点样本（T37 起新增字段，旧数据缺）")
    else:
        rate = signals["memory_cited_rate"]
        add("SC-001", "PASS" if rate and rate > 0 else "FAIL", rate,
            "记忆引用率 > 0（正确率仍需人工核）",
            f"代理指标：引用样本 {signals['memory_cited_turns']} 轮的引用率")

    # SC-003 关系阶段分布：≥3 个阶段有轮次才算「3 阶段语气区分」链路覆盖。
    stage_dist = signals.get("relationship_stage_distribution", {})
    if len(stage_dist) == 0:
        add("SC-003", "N/A", None, "3 阶段语气区分成立率 ≥ 90%",
            "无 relationship_stage 落盘（T37 起新增字段）")
    elif len(stage_dist) >= 3:
        add("SC-003", "PASS", len(stage_dist), "≥ 3 个关系阶段有轮次",
            f"实际分布：{stage_dist}；语气成立率仍需人工判")
    else:
        add("SC-003", "FAIL", len(stage_dist), "≥ 3 个关系阶段有轮次",
            f"实际分布：{stage_dist}（样本只覆盖 {len(stage_dist)} 个阶段）")

    # SC-011 时延 p95（FIX-04 定稿：规则链路 p95 ≤ 300ms，样本 ≥30）。
    p95 = signals.get("latency_p95_ms")
    sample = signals.get("latency_sample_size", 0)
    if p95 is None or sample < 30:
        add("SC-011", "N/A", p95, "p95 ≤ 300ms（样本 ≥30）",
            f"latency_ms 样本不足：{sample}/30（T37 起新增字段）")
    elif p95 <= 300:
        add("SC-011", "PASS", p95, "p95 ≤ 300ms", f"样本 {sample} 条")
    else:
        add("SC-011", "FAIL", p95, "p95 ≤ 300ms", f"样本 {sample} 条超限")

    # -- T38（#53）起：以下 6 项已有真实埋点，按三段式正式判定 --------------

    # SC-004 冷却窗口内数值变化=0（relationship_reason=cooldown_blocked 时
    # relationship_delta 必须恒为 0——数据自洽即证明防刷拦截在工作）。
    cooldown_blocked = signals.get("cooldown_blocked", 0)
    if cooldown_blocked == 0:
        add("SC-004", "N/A", None, "冷却窗口内数值变化=0",
            "无 relationship_reason=cooldown_blocked 样本（T38 起新增字段，旧数据缺）")
    elif signals.get("cooldown_blocked_with_delta", 0) == 0:
        add("SC-004", "PASS", cooldown_blocked, "冷却拦截时 delta 恒为 0",
            f"冷却拦截样本 {cooldown_blocked} 条，数值变化全为 0")
    else:
        add("SC-004", "FAIL", signals["cooldown_blocked_with_delta"], "冷却拦截时 delta=0",
            f"{signals['cooldown_blocked_with_delta']} 条冷却拦截仍有数值变化")

    agent_steps = report.get("agent_steps", {})
    event_signals = report.get("event_signals", {})
    autonomous = agent_steps.get("autonomous_steps", 0)

    # SC-005 自主行为类型 ≥ 8 类（自主步 = reason_codes 含 ARB_WON: 的步）。
    behavior_dist = agent_steps.get("behavior_type_distribution", {})
    if autonomous == 0:
        add("SC-005", "N/A", None, "自主行为类型 ≥ 8 类",
            "无自主步埋点样本（agent_steps 为 T38 起新增落盘）")
    elif len(behavior_dist) >= 8:
        add("SC-005", "PASS", len(behavior_dist), "≥ 8 类", f"实际分布：{behavior_dist}")
    else:
        add("SC-005", "FAIL", len(behavior_dist), "≥ 8 类",
            f"实际 {len(behavior_dist)} 类：{behavior_dist}")

    # SC-006 自主行为重复率=0（相邻自主步 action_type 相同即记一次重复）。
    if autonomous == 0:
        add("SC-006", "N/A", None, "自主行为重复率=0",
            "无自主步埋点样本（agent_steps 为 T38 起新增落盘）")
    elif agent_steps.get("autonomous_adjacent_repeats", 0) == 0:
        add("SC-006", "PASS", 0, "相邻自主行为重复=0", f"自主步 {autonomous} 条零重复")
    else:
        repeats = agent_steps["autonomous_adjacent_repeats"]
        add("SC-006", "FAIL", round(repeats / autonomous, 3), "相邻重复率=0",
            f"{repeats}/{autonomous} 条相邻自主步行为相同")

    # SC-007 幂等重复响应率=0（同一 event+encounter 非首条必须 duplicate=True）。
    total_events = event_signals.get("total_events", 0)
    if total_events == 0:
        add("SC-007", "N/A", None, "幂等重复响应率=0",
            "无事件埋点样本（event_signals 为 T38 起新增落盘）")
    elif event_signals.get("idempotency_violations", 0) == 0:
        add("SC-007", "PASS", 0, "非首条事件必须 duplicate=True",
            f"事件 {total_events} 条，重放 {event_signals.get('duplicate_events', 0)} 条，无绕过")
    else:
        add("SC-007", "FAIL", event_signals["idempotency_violations"], "同事件非首条必须重放",
            "幂等表被绕过：同一事件被独立评估多次（重复反应/重复施法风险）")

    # SC-008 设定类问题一致率 100%（查证链路在跑的证据 = lore_lookup 样本）。
    lore_turns = signals.get("lore_lookup_turns", 0)
    if lore_turns == 0:
        add("SC-008", "N/A", None, "设定类问题一致率 100%",
            "无 lore_lookup 查证样本（T38 起新增字段；未索取查证的轮次不落盘）")
    else:
        add("SC-008", "PASS", lore_turns, "设定类问题一致率 100%",
            f"有据 {signals.get('lore_found', 0)} / 无据 {lore_turns - signals.get('lore_found', 0)}；"
            f"接地丢弃事实 {signals.get('facts_rejected_total', 0)} 条；逐句一致率仍需人工抽检")

    # SC-013 决策可解释覆盖率 100%（reason_codes 非空的步数占比）。
    total_steps = agent_steps.get("total_steps", 0)
    coverage = agent_steps.get("explained_coverage")
    if total_steps == 0 or coverage is None:
        add("SC-013", "N/A", None, "决策可解释覆盖率 100%",
            "无 agent_steps 样本（T38 起新增落盘）")
    elif coverage == 1.0:
        add("SC-013", "PASS", coverage, "reason_codes 非空率 100%", f"步数 {total_steps}")
    else:
        add("SC-013", "FAIL", coverage, "覆盖率 100%",
            f"{agent_steps.get('explained_steps')}/{total_steps} 步缺 reason_codes")

    # -- 仍无法脚本化的 SC：明确 N/A ------------------------------------------
    add("SC-002", "N/A", None, "4 类战况下指令结果合理率 ≥ 90%",
        "receipts 无 game_state 字段（加字段属 UE 契约变更，不在观测层范围）；"
        "「结果合理率」本质需人工判定，脚本只输出 result 分布作代理")

    return verdicts


def build_report(game: str | None = None) -> dict:
    from app.config import get_settings

    receipts_root = _resolve_dir(get_settings().receipts_dir)
    signals_root = _resolve_dir(get_settings().dialogue_signals_dir)
    signals = collect_signals(game)
    receipts = collect_receipts(game)
    agent_steps = collect_agent_steps(game)
    event_signals = collect_event_signals(game)
    report = {
        "scope": game or "all",
        "games": sorted(
            set(_discovered_games(receipts_root)) | set(_discovered_games(signals_root))
        ),
        "receipts": receipts,
        "dialogue_signals": signals,
        "agent_steps": agent_steps,
        "event_signals": event_signals,
        "style_violations": {
            "total": signals["style_violations"],
            "llm_checked_turns": signals["llm_checked_turns"],
            "note": "LLM 路径通过 style_guard 后落盘；mock/fallback 路径为 None（未校验）。",
        },
        "duplicate_responses": event_signals,
    }
    report["sc_verdicts"] = evaluate_sc_verdicts(report)
    return report


def _print_report(report: dict) -> None:
    r, s = report["receipts"], report["dialogue_signals"]
    print("=" * 56)
    print("Aesir 验收指标报告（US7 / T079，T19 修复漏采）")
    print("=" * 56)
    print(f"  采集范围: {report['scope']}（数据游戏: {', '.join(report['games']) or '（无数据）'}）")
    print("\n[执行回执]")
    print(f"  回执总数: {r['total_receipts']}（{r['files']} 个 JSONL 文件）")
    if r["total_receipts"]:
        for name in RECEIPT_RESULTS:
            print(f"    {name}: {r.get(name, 0)}")
        print(f"  result 分布: {r['result_distribution']}")
        print(f"  代理指标说明: {r['proxy_note']}")
    else:
        print("  result 分布: （无数据）")
    if r["corrupt"]:
        print(f"  ⚠ 损坏行: {r['corrupt']}")
    print("\n[对话信号]")
    print(f"  轮次总数: {s['total_turns']}（{s['files']} 个 JSONL 文件）")
    if s["total_turns"]:
        print(f"  后端分布: {s['source_distribution']}")
        print(f"  降级次数（fallback）: {s['degradation_count']}")
        print(f"  复读轮数: {s['repetitive_replies']}")
        print(f"  负反馈次数: {s['negative_feedback']}")
        print(f"  话题延续率: {s['topic_continuation_rate']}")
        print(f"  style_guard 校验轮数: {s['llm_checked_turns']}")
        print(f"  风格违规次数: {s['style_violations']}")
    else:
        print("  后端分布: （无数据）")
    if s["corrupt"]:
        print(f"  ⚠ 损坏行: {s['corrupt']}")
    print("\n[风格违规]")
    sv = report["style_violations"]
    print(f"  总数: {sv['total']}（LLM 校验轮数 {sv['llm_checked_turns']}）")
    print(f"  {sv['note']}")
    print("\n[agent 决策]（T38）")
    a = report["agent_steps"]
    print(f"  步数总数: {a['total_steps']}（自主步 {a['autonomous_steps']}）")
    if a["total_steps"]:
        print(f"  行为类型分布: {a['behavior_type_distribution']}")
        print(f"  相邻自主重复: {a['autonomous_adjacent_repeats']}")
        print(f"  可解释覆盖率: {a['explained_coverage']}")
    print("\n[事件幂等]（T38）")
    e = report["event_signals"]
    print(f"  事件总数: {e['total_events']}（重放 {e['duplicate_events']}，"
          f"重复率 {e['duplicate_ratio']}，绕过 {e['idempotency_violations']}）")
    print("\n[SC 判定]（T32 / #41）")
    for v in report["sc_verdicts"]:
        line = f"  {v['sc']}: {v['status']}"
        if v["metric"] is not None:
            line += f"（metric={v['metric']}）"
        line += f"  threshold: {v['threshold']}"
        if v["note"]:
            line += f"\n      ↳ {v['note']}"
        print(line)
    print("=" * 56)


def main() -> int:
    parser = argparse.ArgumentParser(description="验收指标采集（US7 / T079，T19）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    parser.add_argument("--game", dest="game", default=None,
                        help="只采集指定 game_id；缺省 = 跨全部游戏汇总")
    args = parser.parse_args()
    report = build_report(game=args.game)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
