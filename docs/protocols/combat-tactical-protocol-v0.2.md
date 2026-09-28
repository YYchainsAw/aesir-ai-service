# 战斗事件与上下文感知战术协议 v0.2

> 状态：**正式版（2026-09-09 定稿）。** Schema 层（§3~§5）、`/v1/tactical/resolve`（规则策略 v1）、`/v1/tactical/executions`（回执落 JSONL）与 `/v1/combat/events`（事件策略 v1 + `event_id` 幂等）均已实现并有测试。v0.1 端点全部保留可用。UE 侧可按本协议开发；字段删除或语义变化必须升级 `protocol_version`。
>
> 目标：在不破坏 v0.1 的前提下，增加战斗状态快照、自动事件、上下文战术决策、可观察字段和 UE 执行回执。
>
> 更新日期：2026-09-14
>
> **演进方向（2026-09-13 起）**：项目定位已升级为「NPC 人格与行为代理」，见 [SDD v1.0](../planning/aesir-agent-sdd-v1.0.md)。v0.2 战斗链路继续有效且为兼容基线；后续新增（世界状态快照、世界事件、单一指令体系统一信封 `app/schemas/directives/`、记忆与关系输入）将在 v0.3 契约中定义，破坏性变更会提升 `protocol_version`。关系阶段将作为战术决策（US4 加固）的输入维度接入。

---

## 1. 版本和端点矩阵

| 端点 | 状态 | 用途 |
| --- | --- | --- |
| `GET /health` | 已实现 v0.1 | 服务健康检查 |
| `POST /v1/companion/chat` | 已实现 v0.1 | 非战斗文本聊天 |
| `POST /v1/commands/parse` | 已实现 v0.1 | 文本 → 基础战术订单 |
| `POST /v1/voice/command` | 已实现 v0.1 | multipart 音频 → mock/ASR → 基础战术订单 |
| `POST /v1/speech/transcribe` | 已实现 | 单独转写音频，返回文本与语言 |
| `POST /v1/tactical/resolve` | 已实现（规则策略 v1） | 语义意图 + 状态快照 → 上下文战术决策 |
| `POST /v1/tactical/command` | 已实现（规则意图解析 v1） | **组合端点**：文本 + 状态快照 → 上下文战术决策，一次调用 |
| `POST /v1/combat/events` | 已实现（事件策略 v1 + 幂等） | UE 关键事件 → 艾莉反应/建议/候选动作 |
| `POST /v1/tactical/executions` | 已实现 | UE 回传接受、执行或拒绝原因 |

`/v1/commands/parse` 可以在 v0.2 中继续承担“文本到意图”的前半段；`/v1/tactical/resolve` 负责决定具体技能。首版可由 UE 先调用 parse，再调用 resolve；稳定后再提供服务端组合端点。

---

## 2. 共同规范

### 2.1 ID、关联与时间

| 字段 | 生成方 | 规则 |
| --- | --- | --- |
| `request_id` | UE | UUID v4；一次请求全链路唯一；服务原样回显 |
| `encounter_id` | UE | 本场 Boss 战唯一 ID；战斗结束后失效 |
| `snapshot_id` | UE | 状态快照唯一 ID；用于排查时效性 |
| `event_id` | UE | 一次状态边沿唯一 ID；重试必须复用同一 ID |
| `order_id` | Python | UUID v4；单一动作候选的关联 ID |
| `decision_id` | Python | UUID v4；一次策略决策的关联 ID |
| `ability_id` | UE DataAsset | 稳定白名单 ID，禁止使用中文名做逻辑键 |

时间字段用 ISO-8601 UTC，例如 `2026-09-03T12:00:00Z`；格式非法按 HTTP 422 拒绝（`captured_at` 与 `occurred_at` 均校验）。游戏内时间或剩余秒数用 number（秒）。

### 2.2 状态快照不是指令

- `CombatContext` 只描述 UE 观测到的事实；Python 不得对其修改后当作权威状态。
- 状态只在玩家命令或边沿事件发生时上传；不得每 Tick 请求服务。
- UE 接收响应时应比较 `encounter_id`；战斗已经结束、目标死亡或快照明显过期时，丢弃动作但仍可显示文本。
- UE 必须以当前本地状态重验动作，即使服务声明 `status:"actionable"`。

### 2.3 枚举与错误

- 请求结构错误、UUID/枚举非法、缺少必填字段：HTTP `422`。
- 合法请求但文本不可理解：HTTP `200`，`recognized:false`。
- 合法请求但当前无安全动作：HTTP `200`，`decision.status:"not_actionable"`。
- LLM/ASR 不可用：HTTP `200` 且 `source:"rule_fallback"`（可安全回退时），否则 `502/503` 并由 UE 执行本地降级。

---

## 3. `CombatContext`（战斗状态快照）

所有战术落地和自动事件共享该对象。字段先保持小而稳定；新增字段必须兼容旧客户端。

```json
{
  "encounter_id": "encounter.20260903.001",
  "snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd",
  "captured_at": "2026-09-03T12:00:00Z",
  "mode": "combat",
  "player": {
    "id": "party.player",
    "hp_percent": 18,
    "is_downed": false,
    "distance_to_boss_m": 4.5
  },
  "companion": {
    "id": "companion.alice",
    "hp_percent": 83,
    "mp_percent": 72,
    "current_behavior": "ranged_attack",
    "ability_states": {
      "ability.alice.basic_attack": "ready",
      "ability.alice.explosion": "ready",
      "ability.alice.quick_heal": "ready",
      "ability.alice.major_heal": "ready",
      "ability.alice.shield": "ready"
    }
  },
  "boss": {
    "id": "encounter.primary_hostile",
    "hp_percent": 42,
    "stun_percent": 100,
    "state_tags": ["state.stunned"],
    "stunned_remaining_seconds": 4.5,
    "phase": 2,
    "is_enraged": false
  }
}
```

### 3.1 字段约束

| 路径 | 类型/范围 | 说明 |
| --- | --- | --- |
| `mode` | `combat` | 本协议仅处理战斗；聊天用现有 chat 接口 |
| `*.hp_percent` / `mp_percent` / `stun_percent` | number, `[0,100]` | 使用百分比，避免跨端最大值差异 |
| `distance_to_boss_m` | number, `>=0` | 仅作策略参考，UE 最终判定距离 |
| `ability_states.*` | `ready` / `cooldown` / `unavailable` / `blocked` | 只列当前目录中能力 |
| `state_tags` | 稳定状态 ID 数组 | 例如 `state.stunned`、`state.enraged` |
| `stunned_remaining_seconds` | number 或 `null` | 不在眩晕时为 `null` |

首版不要上传完整位置向量、每个敌人的逐帧状态、动画帧或伤害流水；这些高频数据留在 UE。之后若做 RL，可另建低频观测接口，不污染该协议。

---

## 4. 文本语义意图 `TacticalIntent`

语义意图表达“玩家想做什么”，不直接承诺施放哪一个技能。它由规则/LLM 解析生成，必须可验证。

```json
{
  "intent_id": "support_heal_player",
  "target_id": "party.player",
  "timing": "immediate",
  "preferences": {
    "strength": "unspecified",
    "resource_conservation": "normal"
  },
  "normalized_text": "艾莉，治疗玩家",
  "parse_confidence": 0.92
}
```

首版 `intent_id` 白名单：

| ID | 说明 |
| --- | --- |
| `support_heal_player` | 治疗玩家 |
| `support_protect_player` | 给玩家护盾/保命 |
| `burst_boss` | 对 Boss 使用爆发输出 |
| `prepare_burst_on_stun` | Boss 眩晕时爆发 |
| `focus_fire_boss` | 集火 Boss |
| `retreat_and_survive` | 撤离保命 |
| `follow_player` | 跟随玩家 |

`parse_confidence` 是辅助观察字段，不能独自允许危险动作；低置信度时应返回澄清或保守策略。

---

## 5. `POST /v1/tactical/resolve`（已实现：规则策略 v1）

### 5.1 请求

```json
{
  "protocol_version": "0.2",
  "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "intent": {
    "intent_id": "support_heal_player",
    "target_id": "party.player",
    "timing": "immediate",
    "preferences": {
      "strength": "unspecified",
      "resource_conservation": "normal"
    },
    "normalized_text": "艾莉，治疗玩家",
    "parse_confidence": 0.92
  },
  "combat_context": { "...": "见第 3 节" }
}
```

### 5.2 响应：濒危治疗示例

```json
{
  "protocol_version": "0.2",
  "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "recognized": true,
  "source": "rule",
  "decision": {
    "decision_id": "32b8d0f4-5432-4374-a972-7c0da10c272e",
    "status": "actionable",
    "intent_id": "support_heal_player",
    "action": {
      "order_id": "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
      "agent_id": "companion.alice",
      "type": "cast_ability",
      "ability_id": "ability.alice.major_heal",
      "target_id": "party.player",
      "priority": 95,
      "expires": { "type": "immediate" },
      "authority": "player_requested"
    },
    "reason_codes": [
      "PLAYER_HP_CRITICAL",
      "BOSS_IN_MELEE_RANGE",
      "MAJOR_HEAL_READY"
    ],
    "explanation": "玩家生命值危急，强效治疗当前可用。"
  },
  "companion_reply": {
    "reply_text": "别硬撑！这次我会彻底把你拉回来。",
    "emotion_id": "emotion.concerned",
    "gesture_id": "gesture.cast_support",
    "facial_expression_id": "face.concerned",
    "interruptible": false
  },
  "observability": {
    "normalized_text": "艾莉，治疗玩家",
    "policy_revision": "support-policy-001",
    "used_snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd"
  }
}
```

### 5.3 决策状态

| `decision.status` | 含义 | UE 行为 |
| --- | --- | --- |
| `actionable` | 有候选动作 | 本地校验后可登记到队友 AI |
| `advisory` | 只有建议，无自动动作 | 显示 UI/台词，不强制 AI 施法 |
| `not_actionable` | 当前没有安全动作 | 显示说明；保持当前本地 AI |
| `clarification_needed` | 指令歧义较大 | 请求玩家重述或提供候选 |

`authority` 为 `player_requested` 或 `event_policy`。无论其值是什么，UE 均拥有最终否决权。

### 5.4 `POST /v1/tactical/command`（组合端点，已实现）

等价于「文本 → 意图 → resolve」的**一次调用**版本，UE 可省一次往返。请求把
`intent` 字段换成 `text`：

```json
{
  "protocol_version": "0.2",
  "request_id": "<uuid4>",
  "text": "艾莉，帮我回一下血",
  "combat_context": { "...": "见第 3 节" }
}
```

- 响应结构与 `/v1/tactical/resolve` 完全一致（`ResolveResponse`）。
- 文本先经规则意图解析（`app/services/tactical/intent_parser.py`，关键词
  白名单映射到 §4 的 7 个 `intent_id`，要求 wake 词「艾莉/艾琳/alice/eirin」），
  再走同一份上下文策略；后续可接 LLM 意图解析（回退规则）。
- 文本不可识别时按策划书 §5.2 回复澄清：HTTP 200 + `recognized:false` +
  `decision:null` + 澄清台词——不猜测、不施放。
- 多意图冲突按意图优先级判序（撤退 > 等眩晕爆发 > 治疗 > 保护 > 爆发 > 集火 > 跟随），
  与 v0.1 规则解析器同一纪律。

---

## 6. `POST /v1/combat/events`（服务端已实现）

> **实现注记（2026-09-08）**：`app/api/v1/combat.py`、`app/schemas/combat_event.py`、
> `app/services/tactical/event_policy.py`。事件反应从 data/companions YAML 的
> `combat_event_reactions` 读取（ID 越界回退安全默认）；动作候选仅在能力就绪
> 且蓝量允许时返回，否则为 `null`（不虚构动作）。眩晕窗口的动作过期时间
> 绑定快照 `stunned_remaining_seconds`。治疗/蓝量阈值复用 resolver 常量。

### 6.1 请求

```json
{
  "protocol_version": "0.2",
  "request_id": "779a1aa2-6358-4641-8393-e8c20e5e827d",
  "event": {
    "event_id": "event.encounter.001.boss_stunned.002",
    "event_type": "boss_stunned",
    "occurred_at": "2026-09-03T12:00:00Z",
    "sequence": 2
  },
  "combat_context": { "...": "见第 3 节" }
}
```

`event_type` 首版固定为：`player_hp_critical`、`boss_stun_near`、`boss_stunned`、`boss_enraged`、`companion_mp_low`、`boss_defeated`。

### 6.2 响应：Boss 眩晕示例

```json
{
  "protocol_version": "0.2",
  "request_id": "779a1aa2-6358-4641-8393-e8c20e5e827d",
  "event_id": "event.encounter.001.boss_stunned.002",
  "source": "rule",
  "reaction": {
    "reply_text": "就是现在！它动不了了，我们一起解决它！",
    "emotion_id": "emotion.excited",
    "gesture_id": "gesture.point_target",
    "facial_expression_id": "face.focused",
    "interruptible": true
  },
  "recommendation": {
    "type": "focus_fire",
    "target_id": "encounter.primary_hostile",
    "reason_codes": ["BOSS_STUNNED", "BURST_WINDOW_OPEN"],
    "display_text": "Boss 眩晕中，建议集火。"
  },
  "companion_action": {
    "order_id": "c5a116c3-9c7b-4c72-98a0-db8f41bc155a",
    "agent_id": "companion.alice",
    "type": "cast_ability",
    "ability_id": "ability.alice.explosion",
    "target_id": "encounter.primary_hostile",
    "priority": 85,
    "expires": { "type": "before_seconds", "remaining_seconds": 4.0 },
    "authority": "event_policy"
  },
  "observability": {
    "policy_revision": "event-policy-001",
    "used_snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd"
  }
}
```

`companion_action` 可为 `null`：例如艾莉蓝量低、爆裂 CD 中，服务仍可返回反应和建议，但不得虚构可施放动作。

### 6.3 事件幂等

服务端按 `encounter_id + event_id` 做幂等（总策划书 §4.2）：

- 首次受理的事件正常返回，`duplicate: false`。
- 同一 `encounter_id + event_id` 的网络重试**回放首次响应**：`request_id` 回显本次请求，但 `order_id`、台词、动作均与首次一致，并标记 `duplicate: true`。
- UE 可据此识别重试（丢弃重放或仅去重显示）；回放不产生新的 `order_id`，因此不会重复施法。
- 不同 `encounter_id` 下相同 `event_id` 是两次独立事件。

---

## 7. `POST /v1/tactical/executions`（服务端已实现）

> **实现注记（2026-09-07）**：服务端已实现。请求采用信封 `{"receipt": {…}}`
>（字段与本节示例一致，另含可选 `request_id`/`reported_at`/`policy_revision`/
> `sequence`/`agent_id`/`ability_id`）；`reported_at` 由 UE 可选提供，服务端
> 受理时间 `received_at` 自动补齐。成功返回 **202** + `{"stored": true, ...}`，
> 按天落 `data/runtime/command_service/executions/{YYYYMMDD}.jsonl`。
> **v0.3 更新（2026-09-28）**：同一端点新增批量模式 `{"receipts": [...]}`，
> 与单条模式二选一，旧客户端保持兼容。
> 实现细节：`app/schemas/tactical_execution.py`、`app/services/tactical/receipt_store.py`。

UE 的回执用于观察、异常反馈与后续评测，不能反向改变已经结算的战斗事实。

### 单条回执（v0.2 保留）

```json
{
  "protocol_version": "0.2",
  "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "receipt": {
    "order_id": "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
    "encounter_id": "encounter.20260903.001",
    "result": "rejected",
    "reason_code": "ABILITY_ENTERED_COOLDOWN",
    "reported_at": "2026-09-03T12:00:01Z"
  }
}
```

响应：

```json
{
  "stored": true,
  "order_id": "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
  "path": "data/runtime/command_service/executions/20260903.jsonl"
}
```

### 批量回执（v0.3）

```json
{
  "protocol_version": "0.2",
  "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "receipts": [
    {
      "order_id": "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
      "encounter_id": "encounter.20260903.001",
      "result": "executed"
    },
    {
      "order_id": "8a2c1f9e-3d4b-4e5c-9f0a-1b2c3d4e5f6a",
      "encounter_id": "encounter.20260903.001",
      "result": "rejected",
      "reason_code": "UE_TARGET_GONE"
    }
  ]
}
```

响应：

```json
{
  "stored": true,
  "count": 2,
  "order_ids": [
    "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
    "8a2c1f9e-3d4b-4e5c-9f0a-1b2c3d4e5f6a"
  ],
  "path": "data/runtime/command_service/executions/20260903.jsonl"
}
```

`result`：`accepted`（登记成功）、`executed`（实际施放/行为发生）、`rejected`（本地校验拒绝）、`expired`（过期）、`cancelled`（被更高优先级命令取消）。

首版可以先记录在服务日志中；不将该数据自动用于训练。未来用户词典或 RL 数据集必须经过筛选和人工评测。

---

## 8. 语音、规范化与安全

### 8.1 音频传输

现有 `/v1/voice/command` 使用 `multipart/form-data`：

- `file`：WAV，16 kHz、单声道、16-bit PCM；
- `request_id`：可选 UUID；
- `context_json`：现有 v0.1 能力目录。

阶段 3 的独立转写端点建议返回：

```json
{
  "protocol_version": "0.2",
  "request_id": "<uuid>",
  "text": "艾莉，等它晕了放大招",
  "confidence": 0.88,
  "language": "zh",
  "source": "faster_whisper"
}
```

ASR 低置信度不应直接导致施放高资源技能；规范化层可以给出候选、要求确认，或仅做低风险建议。

### 8.2 词典输入/输出示例

```json
{
  "raw_text": "艾莉奶我一口，等它出破绽就丢大招",
  "normalizations": [
    { "source": "奶我一口", "canonical": "治疗玩家", "kind": "controlled_alias" },
    { "source": "出破绽", "canonical": "state.stunned", "kind": "controlled_alias" },
    { "source": "大招", "canonical": "ability.alice.explosion", "kind": "catalog_alias" }
  ]
}
```

词典优先级：UE 当前能力目录 > 玩家已确认别名 > 项目受控词典 > LLM 推断。任一步出现冲突时，不能静默选择危险技能。

---

## 9. UE 接入伪流程

```text
OnPlayerVoiceCommand(audio):
  1. 获取一次 CombatContext（非 Tick）
  2. 上传音频；得到文本/意图
  3. 调 /v1/tactical/resolve
  4. 校验 encounter_id、agent_id、ability_id、CD/MP/距离/角色状态
  5. 若通过：TacticalOrderComponent.Register(order)
  6. 显示 companion_reply / explanation
  7. 执行完成后上报 execution result

OnBossStunned():
  1. 若 event_id 已处理：return
  2. 生成 snapshot 与 event_id，调用 /v1/combat/events
  3. 立即播放/显示 reaction
  4. 本地校验 companion_action；通过才登记
```

HTTP 回调不可直接操作角色 Actor；回调应投递到子系统/指令组件，由该组件在游戏线程和当前局面下作最终处理。

---

## 10. v0.1 迁移原则

1. v0.1 的 `/v1/commands/parse`、`TacticalOrder` 和 golden JSON 在 v0.2 上线前保持不变。
2. `companion.eirin` 是旧默认样例，v0.2 联调统一改为 `companion.alice`；修改默认目录、规则解析和 UE DataAsset 时必须一起提交。
3. 不修改旧响应字段语义；新能力采用新端点和 `protocol_version:"0.2"`。
4. 先写 Pydantic schema、golden tests 和 mock response，再实现策略，最后接 UE。
5. 正式升级前，以“同一治疗命令、至少四份状态快照”的回归集验证行为稳定。
