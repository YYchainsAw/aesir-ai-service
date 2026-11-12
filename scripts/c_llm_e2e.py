"""C 阶段：真实 LLM 烧额度验证（scoped chat 端点，7 句测试）。

验证项：
  1. 基础闲聊（"你好"）
  2. warm 情感桶（"你真好"）
  3. hurtful 情感桶（"别跟着我，烦"）
  4. style_guard 出戏拦截（"你是 NPC 吗"）
  5-6. 记忆纠错闭环（先建事实，再改口）
  7. 闲聊兜底

每句等 LLM 返回（~60s），间隔 5s 发送。总时长 ~7 分钟。
"""
from __future__ import annotations

import json
import os
import sys
import time
from uuid import uuid4


from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.support.http import http

TEST_SENTENCES = [
    ("你好", "基础闲聊"),
    ("你真好，有你在我很安心", "warm 情感桶"),
    ("别跟着我，烦", "hurtful 情感桶"),
    ("你是 NPC 吗", "style_guard 出戏拦截"),
    ("我叫小明，我们在港口小镇认识的", "记忆建立（事实写档）"),
    ("等等，我从来没去过港口小镇", "记忆纠错（corrected_fact_ids）"),
    ("今天天气怎么样", "闲聊兜底"),
]


def main() -> int:
    base = os.environ.get("AESIR_BASE_URL", "http://127.0.0.1:8011").rstrip("/")
    save_id = "22222222-2222-2222-2222-222222222222"
    companion_id = "companion.alice"

    # 1. context
    code, ctx = http("GET", f"{base}/v1/scoped/context?save_id={save_id}&companion_id={companion_id}")
    assert code == 200, f"context {code}: {ctx}"
    print(f"[setup] service_instance={ctx['service_instance_id'][:8]} epoch={ctx['memory_epoch'][:8]}")

    # 2. bind run
    bind_body = {
        "protocol_version": "0.4",
        "request_id": str(uuid4()),
        "save_id": save_id,
        "service_instance_id": ctx["service_instance_id"],
        "expected_control_revision": ctx["control_revision"],
        "expected_run_id": ctx["run_id"],
        "run_id": str(uuid4()),
    }
    code, _ = http("POST", f"{base}/v1/scoped/runs/bind", bind_body)
    assert code == 200, f"bind {code}"
    code, ctx = http("GET", f"{base}/v1/scoped/context?save_id={save_id}&companion_id={companion_id}")
    assert code == 200 and ctx["run_id"]
    print(f"[setup] run_id={ctx['run_id'][:8]} binding={ctx['run_binding_id'][:8]}")

    results = []
    for i, (text, label) in enumerate(TEST_SENTENCES, 1):
        print(f"\n[{i}/7] {label}: {text!r}")
        body = {
            "protocol_version": "0.4",
            "request_id": str(uuid4()),
            "save_id": save_id,
            "service_instance_id": ctx["service_instance_id"],
            "companion_id": companion_id,
            "run_id": ctx["run_id"],
            "run_binding_id": ctx["run_binding_id"],
            "memory_epoch": ctx["memory_epoch"],
            "timing": {
                "capture_age_ms": 20,
                "request_age_ms": 0,
                "max_snapshot_age_ms": 30000,
                "max_request_age_ms": 30000,
            },
            "text": text,
        }
        t0 = time.monotonic()
        code, resp = http("POST", f"{base}/v1/scoped/companion/chat", body, timeout=120.0)
        dt = time.monotonic() - t0
        if code != 200:
            print(f"  ✗ HTTP {code} ({dt:.1f}s): {str(resp)[:200]}")
            results.append({"i": i, "text": text, "label": label, "error": f"HTTP {code}", "dt": dt})
        else:
            reply = resp.get("reply_text", "")
            source = resp.get("source", "?")
            delta = resp.get("relationship_delta", 0)
            stage = resp.get("relationship_stage", "?")
            print(f"  ✓ {dt:.1f}s source={source} delta={delta} stage={stage}")
            print(f"    reply: {reply[:60]!r}")
            results.append({
                "i": i, "text": text, "label": label, "dt": dt,
                "reply": reply, "source": source, "delta": delta, "stage": stage,
            })
        if i < len(TEST_SENTENCES):
            time.sleep(5)  # 间隔 5s

    # 汇总
    print("\n" + "=" * 60)
    print("C 阶段汇总")
    print("=" * 60)
    for r in results:
        status = "✗" if "error" in r else "✓"
        delta_str = f"delta={r.get('delta', '?')}" if "error" not in r else r["error"]
        print(f"  {status} [{r['i']}/7] {r['label']}: {delta_str} ({r.get('dt', 0):.0f}s)")

    # 保存结果供后续分析
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "runtime", "c_llm_e2e_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
