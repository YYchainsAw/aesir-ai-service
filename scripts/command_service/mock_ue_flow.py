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

from app.config import get_settings

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

    # 9. US3 自主行为演示（T056）：四个非战斗场景 × 主入口编排。
    #    心跳限流最小间隔 2s：每个分支之间稍作等待，保证各自独立判定。
    import time as _time

    print("\n=== US3 自主行为演示（T054 编排：禁打断 → 候选 → 仲裁 → 节流）===")

    def _agent_step(snapshot: dict, title: str, note: str = "") -> dict | None:
        _time.sleep(2.2)  # 心跳限流最小间隔 2s（AESIR_HEARTBEAT_MIN_INTERVAL_SECONDS）
        payload = {
            "protocol_version": "0.3",
            "request_id": _rid(),
            "companion_id": "companion.alice",
            "world_context": snapshot,
        }
        response = client.post("/v1/agent/step", json=payload)
        body = response.json()
        directive = body.get("directive")
        print(
            f"\n--- {title}{('（' + note + '）') if note else ''}"
            f"\n    HTTP {response.status_code}  action={body.get('action')}"
            f"  behavior={directive['action_type'] if directive else None}"
            f"  gaze={directive['presentation']['gaze_target_id'] if directive and directive.get('presentation') else None}"
            f"\n    reasons={body.get('observability', {}).get('reason_codes')}"
        )
        return body

    camp_snapshot = json.loads((GOLDEN_DIR / "world_snapshot_camp.json").read_text(encoding="utf-8"))
    idle_snapshot = json.loads((GOLDEN_DIR / "world_snapshot_idle.json").read_text(encoding="utf-8"))
    exploration_snapshot = json.loads(
        (GOLDEN_DIR / "world_snapshot_exploration.json").read_text(encoding="utf-8")
    )

    # 9a. camp 夜晚 + notable 篝火 → 休整优先（rest 40 > inspect 25，注视篝火）
    _agent_step(camp_snapshot, "营地夜晚：篝火旁", "US3：夜深在篝火旁休整")

    # 9b. idle 深夜 → 同为 night_rest 触发源 → 被 DEDUP_WINDOW 拦截（FR-022 演示）
    _agent_step(idle_snapshot, "深夜待机（同一触发源）", "FR-022：短期内不重复休整 → 静止")

    # 9c. 探索 + notable 遗迹路标 → inspect（注视路标）；首访告警已在前面演示过，
    #     此处用 first_visit=false 的副本展示日常观察类候选
    explore_copy = json.loads(json.dumps(exploration_snapshot))
    explore_copy["region"]["first_visit"] = False
    _agent_step(explore_copy, "探索：遗迹路标旁", "US3：好奇地查看路标")

    # 9d. 禁打断：cutscene_playing → 静止
    cutscene_snapshot = json.loads(json.dumps(camp_snapshot))
    cutscene_snapshot["cutscene_playing"] = True
    _agent_step(cutscene_snapshot, "剧情演出中", "FR-023：禁打断，静止观察")

    # 9e. 节流演示：同一快照立即重发（绕过心跳限流后由 DEDUP_WINDOW 拦截）
    #     —— 限流仍会先 429，此处直接展示服务端 THROTTLED 路径见 API 测试。

    print("\nUS3 演示完成：非战斗场景产出合理且不重复的自主行为。")

    # 10. US7 全链路可解释演示（T078）：输入 → 理解 → 关系阶段 → 决策 → 依据 → 结果。
    #    用主入口文本指令路径（T075：与 /v1/tactical 同一决策层）逐段打印。
    print("\n=== US7 可解释链路演示（输入 → 理解 → 关系 → 决策 → 依据 → 结果）===")

    def _explain_step(title: str, text: str, world_context: dict) -> None:
        _time.sleep(2.2)  # 心跳限流
        payload = {
            "protocol_version": "0.3",
            "request_id": _rid(),
            "companion_id": "companion.alice",
            "text": text,
            "world_context": world_context,
        }
        response = client.post("/v1/agent/step", json=payload)
        body = response.json()
        obs = body.get("observability", {})
        directive = body.get("directive")
        reasons = obs.get("reason_codes", [])
        # 抽出意图/关系码单独展示
        intent_codes = [c for c in reasons if c.startswith("INTENT:")]
        rel_codes = [c for c in reasons if c.startswith("RELATIONSHIP_")]
        other_codes = [c for c in reasons if not c.startswith(("INTENT:", "RELATIONSHIP_"))]
        print(
            f"\n--- {title}"
            f"\n  [输入]   \"{text}\""
            f"\n  [理解]   {intent_codes or '（未识别意图）'}"
            f"\n  [关系]   stage={obs.get('relationship_stage')!r} {rel_codes}"
            f"\n  [决策]   action={body.get('action')}"
            f"  behavior={directive['action_type'] if directive else None}"
            f"\n  [依据]   {other_codes}"
            f"  （策略 {obs.get('policy_revision')}，人设 {obs.get('persona_revision')}）"
            f"\n  [结果]   reply_text={body.get('reply_text')!r}"
            f"\n  [快照]   used_snapshot_id={obs.get('used_snapshot_id')}"
        )

    # 10a. 战斗指令：濒危快照 A + 治疗意图 → 强效治疗
    critical_combat = json.loads((GOLDEN_DIR / "snapshot_a_critical.json").read_text(encoding="utf-8"))
    combat_world = {
        "snapshot_id": "77777777-7777-4777-8777-777777777777",
        "captured_at": "2026-09-21T12:00:00Z",
        "scene": "combat",
        "player": {"id": "party.player", "hp_percent": critical_combat["player"]["hp_percent"]},
        "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
        "combat": critical_combat,
    }
    _explain_step("战斗指令（濒危快照）", "艾莉，快奶我一口", combat_world)

    # 10b. 非战斗指令：探索快照 + 查看意图 → inspect 指令（快照内目标）
    explore_world = json.loads(
        (GOLDEN_DIR / "world_snapshot_exploration.json").read_text(encoding="utf-8")
    )
    _explain_step("非战斗指令（探索快照）", "艾莉，看看那个路标", explore_world)

    # 10c. 调试台（T077）：场景 / 情绪 / 关系 / 近期记忆 / 版本一览
    state = client.get("/v1/console/state", params={"companion_id": "companion.alice"})
    _show("GET /v1/console/state（US7 调试台）", state.status_code, state.json())

    print("\nUS7 演示完成：每一次决策都可逐段解释。")
    return 0


if __name__ == "__main__":
    defaults = get_settings()
    parser = argparse.ArgumentParser(description="mock UE 全链路演示")
    parser.add_argument(
        "--url",
        default=f"http://{defaults.service_host}:{defaults.service_port}",
        help="服务地址（默认从 AESIR_SERVICE_HOST/AESIR_SERVICE_PORT 读取）",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.url))
