# NPC 服务契约 v0.3（独立成文）

> 本文件是 `protocol_version=0.3` 的**独立契约**（T18 / EXT-04 收口）：把此前散落在
> v0.1/v0.2 文档附录与注释中的 v0.3 内容（`/v1/agent/step`、`/v1/world/events`、
> `/v1/console/*`、批量执行回执）集中定义，并给出与 v0.1/v0.2 的兼容边界。
> 文中样例均为 **2026-10-08 对运行中实例（端口 8000）的实测抓取**。
>
> 关联文档：[v0.1 契约](ue-protocol-contract-v0.1.md)（聊天/语音/旧指令解析）、
> [v0.2 契约](combat-tactical-protocol-v0.2.md)（战斗快照/战术决策/单条回执）、
> [人格包与游戏档案 schema](persona-pack-schema-v0.2.md)、[联调对齐表](integration-alignment-v0.3.md)。

---

## 1. 版本与端点矩阵

| 端点 | 协议版本 | 状态 | 能力门控（S4） |
|------|----------|------|----------------|
| `POST /v1/companion/chat` / `/chat/stream` | 0.1 | 已实现 | 全等级可用 |
| `POST /v1/voice/command`、`/v1/speech/transcribe` | 0.1 | 已实现（mock / faster_whisper） | 全等级可用 |
| `POST /v1/commands/parse`、`/parse-command` | 0.1 | 已实现（保留兼容） | L3 |
| `POST /v1/tactical/resolve` / `/command` | 0.2 | 已实现 | L3 |
| `POST /v1/combat/events` | 0.2 | 已实现 | L3 |
| `POST /v1/tactical/executions` | 0.2/0.3 | 已实现（单条 v0.2 + 批量 v0.3） | L3 |
| `POST /v1/agent/step` | **0.3** | 已实现（自主行为主入口） | L3 |
| `POST /v1/world/events` | **0.3** | 已实现（生活事件 + 关系驱动） | 按档案事件声明 |
| `GET /v1/console/state`、`/v1/console/ui` 等 | 0.3 | 已实现（调试台） | 全等级可用 |

**分流口径（联调时按此路由玩家输入）**：

- 玩家**闲聊/提问/情感表达** → `/v1/companion/chat`（文本）或 `/v1/voice/command`（语音）；
- 玩家**战斗指令**（非战斗状态文本）→ `/v1/tactical/command`（v0.2 组合端点，一次调用）；
- **心跳/定时器驱动**的自主行为 → `/v1/agent/step`；
- **游戏内事实事件**（送礼/被保护/进入新区域等）→ `/v1/world/events`；
- **UE 执行结果回流** → `/v1/tactical/executions`。

**版本兼容边界**：v0.1/v0.2 端点行为冻结，只在 v0.3 做增量；破坏性变更提升 `protocol_version`。
请求里的 `protocol_version` 字段按上表填；服务端对旧版本请求保持兼容，不混用字段。

## 2. 共同规范

- **ID**：`request_id` / `order_id` / `snapshot_id` 为 UUID（字符串）；`companion_id` 形如 `companion.alice`；`game_id` 为游戏档案 ID（当前 `aesir`）。
- **时间**：事件类带 `occurred_at`（ISO-8601 UTC）；回执的 `received_at` 缺省时由服务端受理时间补齐。
- **终态**：执行回执 `result ∈ {accepted, executed, rejected, expired, cancelled}`，落盘即终态，幂等按 `order_id + encounter_id` 由 UE 保证不重复上报同一终态。
- **错误**：
  - `404` 未登记/跨游戏 `companion_id`（**不回退默认角色**），`{"detail": "Unregistered companion_id: ..."}`；
  - `403` 能力门控（L0 游戏访问完整链路 / 未声明事件），`detail` 为结构化字典（`reason_code` 等，见 schema 文档 §5.1）；
  - `422` 请求体不合 schema（`extra="forbid"`，多余字段同样拒绝）；
  - `503` 人设配置损坏（`detail` 含 `profile`）。
- **快照不是指令**：`world_context` / `combat_context` 只是状态陈述，服务绝不下发快照中未出现的 `ability_id` / `target_id`（FR-040）。

## 3. `POST /v1/agent/step`（v0.3 自主行为主入口）

心跳/定时器驱动；文本输入走「玩家指令」分支，空文本走「自主行为编排」分支。

**请求**

```json
{
  "protocol_version": "0.3",
  "request_id": "99d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "companion_id": "companion.alice",
  "world_context": {
    "snapshot_id": "22222222-2222-4222-8222-222222222222",
    "captured_at": "2026-10-08T12:00:00Z",
    "scene": "exploration",
    "player": {"id": "party.player", "hp_percent": 80},
    "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70}
  }
}
```

**响应（实测 200，31.8ms；空文本心跳 → 自主 `observe` 指令）**

```json
{
  "protocol_version": "0.3",
  "request_id": "99d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "companion_id": "companion.alice",
  "action": "directive",
  "directive": {
    "directive_id": "51eeec08-1c0c-484e-9255-ec4784b90861",
    "agent_id": "companion.alice",
    "domain": "exploration",
    "action_type": "observe",
    "priority": 25,
    "expires": {"type": "before_seconds", "remaining_seconds": 10.0},
    "source": "autonomy",
    "reason_codes": ["DEFAULT_OBSERVE", "ARB_WON:routine_autonomy"],
    "policy_revision": "agency-policy-002",
    "payload": {},
    "presentation": {"reply_text": "我在呢。想聊什么？", "emotion_id": "emotion.bright",
      "gesture_id": "gesture.cheerful_idle", "facial_expression_id": "face.bright_smile",
      "interruptible": true, "gaze_target_id": null}
  },
  "reply_text": "",
  "observability": {"source": "rule", "reason_codes": ["ARB_WON:routine_autonomy", "DEFAULT_OBSERVE"],
    "policy_revision": "agency-policy-002", "used_snapshot_id": "…",
    "relationship_stage": "distant", "relationship_stage_display": "疏远", "persona_revision": "0.2"}
}
```

- `action ∈ {directive, reply, idle}`；`directive` 为统一信封（`app/schemas/directives/`，`schema_version 0.3`）。
- 限流：心跳间隔小于 `AESIR_HEARTBEAT_MIN_INTERVAL_SECONDS`（默认 2s）时按限流响应，不产出新指令。

## 4. `POST /v1/world/events`（v0.3 生活事件 + 关系驱动）

**请求**

```json
{
  "protocol_version": "0.3",
  "request_id": "req.w.001",
  "companion_id": "companion.alice",
  "event": {"event_id": "ev.w.001", "event_type": "gift_given",
            "occurred_at": "2026-10-08T12:00:00Z", "sequence": 1, "details": {}},
  "world_context": {"snapshot_id": "44444444-4444-4444-8444-444444444444",
    "captured_at": "2026-10-08T12:00:00Z", "scene": "exploration",
    "player": {"id": "party.player", "hp_percent": 80},
    "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70}}
}
```

**响应（实测 200，27.5ms）**

```json
{
  "protocol_version": "0.3", "request_id": "req.w.001",
  "companion_id": "companion.alice", "event_id": "ev.w.001", "duplicate": false,
  "reaction": {"reply_text": "给我的？……那我就收下了，谢谢你。",
    "emotion_id": "emotion.shy", "gesture_id": "gesture.look_away", "facial_expression_id": "face.shy"},
  "recommendation_text": null, "companion_action": null,
  "observability": {"source": "rule", "policy_revision": "event-policy-001",
    "used_snapshot_id": "44444444-4444-4444-8444-444444444444",
    "reason_codes": ["GIFT_GIVEN", "RELATIONSHIP_UPDATED"],
    "relationship_stage": "neutral", "relationship_stage_display": "平常", "relationship_delta": 3}
}
```

- 幂等键：`companion_id + encounter_id + event_id`（生活类 encounter 为空串占位）；重复上报返回 `duplicate: true` 且不重复计分（FR-033 / SC-007）。
- `event_type` 必须落在当前游戏档案 `events` 声明内（S4 门禁），白名单外的类型值本身 422（schema 枚举）。
- 关系驱动：gift_given / companion_recovered / player_protected_companion / promise_kept 调整关系数值，幅度见 `data/policy/relationship_policy.yaml`。

## 5. `POST /v1/tactical/executions`（单条 v0.2 + 批量 v0.3）

**单条（实测 202，4.1ms）**

```json
// 请求
{"receipt": {"order_id": "99d7e6b4-f4f2-4d39-8c96-a23d293882f6",
             "result": "executed", "encounter_id": "enc.t18.001"}}
// 响应
{"stored": true, "order_id": "99d7e6b4-…",
 "path": "data/runtime/command_service/executions/aesir/20261008.jsonl"}
```

**批量（v0.3，实测 202，3.5ms）**

```json
// 请求
{"receipts": [
  {"order_id": "99d7e6b4-…", "result": "rejected", "encounter_id": "enc.t18.001", "reason_code": "UE_VETO"},
  {"order_id": "88d7e6b4-…", "result": "expired", "encounter_id": "enc.t18.001"}]}
// 响应
{"stored": true, "count": 2, "order_ids": ["99d7e6b4-…", "88d7e6b4-…"], "path": "…/aesir/20261008.jsonl"}
```

- `receipt` 与 `receipts` 二选一（schema `model_validator` 强制）；202 表示受理。
- 落盘：按 `game_id` + 天分文件 JSONL 追加；`received_at` 缺省时服务端补受理时间。
- 用途：RL 数据筛选前置素材，**不自动用于训练**。

## 6. `GET /v1/console/*`（调试台，v0.3）

| 端点 | 说明 |
|------|------|
| `GET /v1/console/state` | 当前场景/情绪/关系阶段（含中文 `relationship_stage_display`）/四层记忆计数/近期观测/策略版本 |
| `GET /v1/console/ui` | 内联单页 HTML 实时展示（无外部前端依赖） |
| `GET /v1/console/memory/*`、`/v1/console/relationship/*` | 记忆与关系调试读写（带 `game_id` 命名空间） |

## 7. 错误样例（实测）

```json
// 未登记 / 跨游戏角色（404，19.3ms）
{"detail": "Unregistered companion_id: companion.unknown"}

// 请求体违规（422，1.5ms；text 为空串）
{"detail": [{"type": "string_too_short", "loc": ["body", "text"],
             "msg": "String should have at least 1 character", "input": "", "ctx": {"min_length": 1}}]}

// L0 游戏访问完整链路（403；demo-vn 实测）
{"detail": {"reason_code": "CAPABILITY_LEVEL_INSUFFICIENT", "feature": "tactical.executions",
            "game_id": "demo-vn", "capability_level": "L0", "required": "L3"}}

// L0 游戏上报未声明事件（403；demo-vn 实测）
{"detail": {"reason_code": "EVENT_NOT_DECLARED", "feature": "world.events",
            "game_id": "demo-vn", "capability_level": "L0", "event_type": "promise_kept"}}
```

## 8. 变更记录

- **0.3（2026-10-08）**：独立成文（T18）。整合 agent/step、world/events、批量回执、调试台；补实测样例与版本兼容边界。
