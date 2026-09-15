"""按总策划书 §9 的 UE 伪流程，把全链路端点跑一遍（联调前演示/自检）。

覆盖：非战斗聊天 → 文本解析（parse）→ 上下文决策（resolve，四类战况同一意图）
→ 战斗事件（combat/events，含幂等重试）→ 执行回执（executions）
→ v0.3 骨架：主入口心跳（含限流）→ 世界事件（幂等）→ 调试台。
相当于一个「不会写 C++ 的假 UE」：UE 同学可以在写代码前看到完整闭环的响应长什么样。

用法（先起服务）：
    .venv/Scripts/python -m uvicorn app.main:app --reload
    .venv/Scripts/python -m scripts.command_service.mock_ue_flow
    .venv/Scripts/python -m scripts.command_service.mock_ue_flow --url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx

# Windows 终端默认 GBK，中文 JSON 输出会乱码
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "data" / "golden"
SNAPSHOTS = [
    ("A 濒危贴脸", "snapshot_a_critical.json"),
    ("B 稳态消耗", "snapshot_b_steady.json"),
    ("C 眩晕窗口", "snapshot_c_stun_window.json"),
    ("D 资源枯竭", "snapshot_d_resource_dry.json"),
]


def _rid() -> str:
    return str(uuid4())


def _show(title: str, status_code: int, body: dict) -> None:
    print(f"\n=== {title}  [HTTP {status_code}] ===")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def main(url: str) -> int:
    client = httpx.Client(base_url=url, timeout=5.0)

    # 0. 健康检查
    health = client.get("/health")
    _show("GET /health", health.status_code, health.json())
    if health.status_code != 200:
        print("服务不可用，中止。", file=sys.stderr)
        return 1

    # 1. 非战斗聊天
    chat = client.post(
        "/v1/companion/chat",
        json={
            "text": "艾莉，今天心情怎么样？",
            "companion_id": "companion.alice",
            "game_state": "conversation",
        },
    )
    _show("POST /v1/companion/chat", chat.status_code, chat.json())

    # 2. 文本解析（v0.1 前半段）
    parse = client.post(
        "/v1/commands/parse",
        json={
            "protocol_version": "0.1",
            "request_id": _rid(),
            "text": "艾莉，等 Boss 眩晕时使用爆裂魔法",
            "context": {
                "catalog_revision": "dev-001",
                "locale": "zh-CN",
                "agents": [
                    {
                        "id": "companion.alice",
                        "ability_ids": [
                            "ability.alice.explosion",
                            "ability.alice.basic_attack",
                        ],
                    }
                ],
                "target_selectors": ["encounter.primary_hostile", "party.player"],
                "state_tags": ["state.stunned", "state.phase_two"],
            },
        },
    )
    _show("POST /v1/commands/parse（等 Boss 眩晕时用爆裂魔法）", parse.status_code, parse.json())

    # 3. 上下文决策：同一治疗意图 × 四类战况（v0.2 核心卖点）
    intent = {
        "intent_id": "support_heal_player",
        "target_id": "party.player",
        "timing": "immediate",
        "preferences": {"strength": "unspecified", "resource_conservation": "normal"},
        "normalized_text": "艾莉，治疗玩家",
        "parse_confidence": 0.92,
    }
    print("\n=== POST /v1/tactical/resolve × 4 战况（同一句\"帮我回一下血\"）===")
    last_order_id = None
    for label, filename in SNAPSHOTS:
        snapshot = json.loads((GOLDEN_DIR / filename).read_text(encoding="utf-8"))
        resolve = client.post(
            "/v1/tactical/resolve",
            json={"protocol_version": "0.2", "request_id": _rid(), "intent": intent,
                  "combat_context": snapshot},
        )
        body = resolve.json()
        decision = body.get("decision") or {}
        action = decision.get("action")
        print(
            f"\n--- {label}（{filename}）"
            f"\n    status={decision.get('status')}"
            f"  action={action['ability_id'] if action else None}"
            f"  priority={action['priority'] if action else '-'}"
            f"\n    reasons={decision.get('reason_codes')}"
        )
        if label.startswith("A") and action:
            last_order_id = action["order_id"]

    # 3b. 组合端点：文本 + 快照一次到位（UE 可省一次往返）
    combo = client.post(
        "/v1/tactical/command",
        json={
            "protocol_version": "0.2",
            "request_id": _rid(),
            "text": "艾莉，帮我回一下血",
            "combat_context": json.loads(
                (GOLDEN_DIR / "snapshot_a_critical.json").read_text(encoding="utf-8")
            ),
        },
    )
    body = combo.json()
    decision = body.get("decision") or {}
    action = decision.get("action")
    print(
        f"\n=== POST /v1/tactical/command（\"艾莉，帮我回一下血\" + 快照A）===\n"
        f"    status={decision.get('status')}"
        f"  action={action['ability_id'] if action else None}"
        f"  reasons={decision.get('reason_codes')}"
    )

    # 4. 战斗事件：Boss 眩晕 + 网络重试（幂等）
    stun_snapshot = json.loads(
        (GOLDEN_DIR / "snapshot_c_stun_window.json").read_text(encoding="utf-8")
    )
    event_payload = {
        "protocol_version": "0.2",
        "request_id": _rid(),
        "event": {
            "event_id": "event.encounter.001.boss_stunned.001",
            "event_type": "boss_stunned",
            "occurred_at": "2026-09-09T12:00:00Z",
            "sequence": 1,
        },
        "combat_context": stun_snapshot,
    }
    first = client.post("/v1/combat/events", json=event_payload)
    _show("POST /v1/combat/events（boss_stunned 首次）", first.status_code, first.json())
    retry = client.post("/v1/combat/events", json=event_payload)
    retry_body = retry.json()
    _show("POST /v1/combat/events（同一 event_id 重试 → 幂等回放）", retry.status_code, retry_body)
    print(
        f"\n    duplicate={retry_body.get('duplicate')}  "
        f"order_id 与首次一致：{retry_body.get('companion_action', {}).get('order_id') == first.json().get('companion_action', {}).get('order_id')}"
    )
    if retry_body.get("companion_action"):
        last_order_id = last_order_id or retry_body["companion_action"]["order_id"]

    # 5. 执行回执
    if last_order_id:
        receipt = client.post(
            "/v1/tactical/executions",
            json={
                "protocol_version": "0.2",
                "request_id": _rid(),
                "receipt": {
                    "order_id": last_order_id,
                    "encounter_id": stun_snapshot["encounter_id"],
                    "result": "executed",
                },
            },
        )
        _show("POST /v1/tactical/executions（executed 回执）", receipt.status_code, receipt.json())

    print("\n全链路完成：chat → parse → resolve ×4 → events（含幂等）→ executions。")

    # 6. 主入口心跳（v0.3 骨架：空动作路径；SDD T018）
    heartbeat_request = json.loads(
        (GOLDEN_DIR / "agent_step_heartbeat_request.json").read_text(encoding="utf-8")
    )
    heartbeat_request["request_id"] = _rid()
    heartbeat = client.post("/v1/agent/step", json=heartbeat_request)
    _show("POST /v1/agent/step（心跳，探索快照）", heartbeat.status_code, heartbeat.json())
    throttled = client.post("/v1/agent/step", json=heartbeat_request)
    print(f"\n    立即重复心跳 → HTTP {throttled.status_code}（限流生效，FR-022）")

    # 7. 世界事件（v0.3 骨架：region_first_entered + 幂等重试）
    world_event = json.loads(
        (GOLDEN_DIR / "world_event_region_first_entered.json").read_text(encoding="utf-8")
    )
    world_event["request_id"] = _rid()
    we_first = client.post("/v1/world/events", json=world_event)
    _show("POST /v1/world/events（region_first_entered 首次）", we_first.status_code, we_first.json())
    we_retry = client.post("/v1/world/events", json=world_event)
    print(f"\n    重复上报 duplicate={we_retry.json().get('duplicate')}（幂等回放，FR-033）")

    # 8. 调试台：状态查询与记忆重置（v0.3 骨架）
    state = client.get("/v1/console/state", params={"companion_id": "companion.alice"})
    _show("GET /v1/console/state", state.status_code, state.json())
    reset = client.post("/v1/console/memory/reset", json={"companion_id": "companion.alice"})
    _show("POST /v1/console/memory/reset", reset.status_code, reset.json())

    print("\nv0.3 骨架链路完成：agent/step（心跳+限流）→ world/events（幂等）→ console。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="mock UE 全链路演示")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="服务地址")
    args = parser.parse_args()
    raise SystemExit(main(args.url))
