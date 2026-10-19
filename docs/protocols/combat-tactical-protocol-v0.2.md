# 战斗事件与上下文感知战术协议 v0.2

> 状态：**正式版（2026-09-09 定稿）。** Schema 层（§3~§5）、`/v1/tactical/resolve`（规则策略 v1）、`/v1/tactical/executions`（回执落 JSONL）与 `/v1/combat/events`（事件策略 v1 + `event_id` 幂等）均已实现并有测试。v0.1 端点全部保留可用。UE 侧可按本协议开发；字段删除或语义变化必须升级 `protocol_version`。
>
> 目标：在不破坏 v0.1 的前提下，增加战斗状态快照、自动事件、上下文战术决策、可观察字段和 UE 执行回执。
>
> 校对日期：2026-10-19；源码基线`a2dd426`。接口存在、测试材料与UE实际执行分别记录，本轮未运行服务。
>
> **当前分工：**本页定义仍兼容的战斗快照、意图与决策；统一代理、世界事件、调试和回执边界见[NPC契约v0.3](npc-contract-v0.3.md)。需求主文为[SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)。v0.2保持规则决策，关系调制在agent/step编排，不能由此推断旧端点已经接入关系调制。

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

`/v1/commands/parse` 可以在 v0.2 中继续承担“文本到意图”的前半段；`/v1/tactical/resolve` 负责决定具体技能。当前可直接调用`/v1/tactical/command`；v0.1 parse返回的是TacticalOrder，不是本页TacticalIntent，不能把其响应原样当resolve请求。若分步调用，调用方须形成符合§4的意图。

---

## 2. 共同规范

### 2.1 ID、关联与时间

| 字段 | 生成方 | 规则 |
| --- | --- | --- |
| `request_id` | UE | 建议UUID v4；v0.2模型实际按字符串接收并回显 |
| `encounter_id` | UE | 本场 Boss 战唯一 ID；战斗结束后失效 |
| `snapshot_id` | UE | 状态快照唯一 ID；用于排查时效性 |
| `event_id` | UE | 一次状态边沿唯一 ID；重试必须复用同一 ID |
| `order_id` | Python | UUID v4；单一动作候选的关联 ID |
| `decision_id` | Python | UUID v4；一次策略决策的关联 ID |
| `ability_id` | UE DataAsset | 稳定白名单 ID，禁止使用中文名做逻辑键 |

时间字段用 ISO-8601 UTC，例如 `2026-09-03T12:00:00Z`；格式非法按 HTTP 422 拒绝（`captured_at` 与 `occurred_at` 均校验）。游戏内时间或剩余秒数用 number（秒）。

### 2.2 状态快照不是指令

- `CombatContext` 只描述 UE 观测到的事实；Python 不得对其修改后当作权威状态。
- 本页战斗链路在玩家命令或边沿事件发生时上传，不逐Tick请求。v0.3自主行为有单独的限频心跳，不与本页事件链路混淆。
- UE 接收响应时应比较 `encounter_id`；战斗已经结束、目标死亡或快照明显过期时，丢弃动作但仍可显示文本。
- UE 必须以当前本地状态重验动作，即使服务声明 `status:"actionable"`。

### 2.3 枚举与错误

- 已声明且受校验的类型、枚举、必填字段错误：HTTP`422`。v0.2多项ID仍是普通字符串，部分模型默认忽略额外字段；实际边界见末节，不保证所有UUID/额外字段都被拒绝。
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

战斗意图的主要取值如下；实际`TacticalIntent`还保留`inspect_interactable/pickup_item/rest_here/wait_here`四项，用于v0.3非战斗分流。v0.2 CombatContext仍仅适用于combat，不能因意图枚举存在就认定其支持非战斗场景。

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
- 文本先经规则意图解析（`app/services/tactical/intent_parser.py`），由关键词匹配当前11项意图白名单，并按角色配置检查唤醒词（例如艾莉/Alice），
  再走同一份上下文策略；`AESIR_INTENT_BACKEND=llm`已可选择LLM解析，失败回退规则，具体配置见[LLM指南](../guides/llm-integration.md)。
- 文本不可识别时按当前SDD回复澄清：HTTP 200 + `recognized:false` +
  `decision:null` + 澄清台词——不猜测、不施放。
- 多意图冲突按意图优先级判序（撤退 > 等眩晕爆发 > 治疗 > 保护 > 爆发 > 集火 > 跟随），
  与 v0.1 规则解析器同一纪律。

---

## 6. `POST /v1/combat/events`（服务端已实现）

> **实现注记（2026-09-08）**：`app/api/v1/combat.py`、`app/schemas/combat_event.py`、
> `app/services/tactical/event_policy.py`。事件反应从data/personas人格包reactions.yaml的
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

### 6.3 事件幂等与UE执行去重

服务使用`(companion_id, encounter_id, event_id)`作为战斗事实幂等键，与v0.3世界事件通道共享缓存；生活事件的遭遇部分为空串。

- 首次处理返回`duplicate:false`；相同键重试回放首次反应/候选动作并标`duplicate:true`，请求ID回显本次请求，order_id不重新生成。
- 缓存是单进程内存的1024项有界表，淘汰最旧项；进程重启不保留。它不承诺跨重启或淘汰后的永久恰好一次，冷却也不代替幂等。
- 同一event_id在不同角色/遭遇中是不同作用域。UE重试同一事实应保留ID，并对回放的order_id另外做执行去重；相同order_id本身不能证明世界动作不重复。
- 返回候选建议不等于已经启动或命中。旧游玩、结束遭遇或过期建议必须由UE拒绝。

---

## 7. 执行回执（单条兼容与批量）

`POST /v1/tactical/executions`支持`{"receipt":{...}}`或`{"receipts":[...]}`，二选一且批量非空。单条兼容v0.2，批量为后来增加的能力；实际信封没有顶层protocol_version字段，每条ExecutionReceipt的protocol_version固定0.2。完整字段及示例集中见[NPC契约回执节](npc-contract-v0.3.md#4-执行回执)。

`result`实际只允许`accepted/executed/rejected/expired/cancelled`。accepted表示登记/受理，不是命中或完成；202仅表示记录受理。当前仅追加JSONL，没有按order维护状态机、重复/乱序合并或验证真实动作。需要的开始、命中、完成阶段是需求目标，不能无版本设计就改成已支持的新枚举。

按UTC日期写入`data/runtime/command_service/executions/<game_id>/<YYYYMMDD>.jsonl`。旧文中缺game_id层的路径不再是当前默认。请求game_id尚未绑定当前进程游戏，是待修差距；回执不自动用于训练，也不能反向制造战斗事实。

---

## 8. 语音、规范化与安全

### 8.1 音频传输

语音命令入口`/v1/voice/command`使用multipart字段`file`、可选UUID `request_id`和`context_json`，返回v0.1 ParseCommandResponse；纯转写入口`/v1/speech/transcribe`使用`audio`、可选request_id/locale，实际返回`request_id/text/language`，没有协议版本、置信度或source字段。二者完整格式见[v0.1契约](ue-protocol-contract-v0.1.md#53-语音转写)。

传输约定为16kHz、单声道、16-bit PCM WAV。当前入口未统一限制大小/时长或验证全部音频参数，不能把建议格式当已实现门禁。闲聊语音使用`/v1/companion/chat/voice`，不把语音命令入口当对话分流器。

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
  1. 获取一次当前CombatContext（非Tick）
  2. 调/v1/speech/transcribe得到文本
  3. 以text + combat_context调/v1/tactical/command；不把v0.1 order误当TacticalIntent
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

1. v0.1的`/v1/commands/parse`、TacticalOrder和golden JSON继续按兼容契约维护，不由v0.2或v0.3的存在推断删除。
2. `companion.eirin` 是旧默认样例，v0.2 联调统一改为 `companion.alice`；修改默认目录、规则解析和 UE DataAsset 时必须一起提交。
3. 不修改旧响应字段语义；新能力采用新端点和 `protocol_version:"0.2"`。
4. 先写 Pydantic schema、golden tests 和 mock response，再实现策略，最后接 UE。
5. 正式升级前，以“同一治疗命令、至少四份状态快照”的回归集验证行为稳定。


## 11. 当前验证与实现边界

- `ResolveRequest/TacticalCommandRequest`校验版本0.2，request_id为普通字符串；CombatContext.snapshot_id等也不是UUID类型。它们及若干决策模型未设置extra=forbid，额外字段可能被忽略，严格拒绝仍需实现与兼容评估。
- L3端点等级门控已经存在，但v0.2 resolver没有完整统一执行“已注册角色404、当前游戏逐能力授权”的入口校验；能力ready检查不等同人格注册或游戏能力目录全验证。UE最终复核仍必需。
- 策略YAML、配置及JSONL存储仍可能失败；LLM解析有回退不等于整条链路保证永无500。按实际响应和日志处理故障，未验收能力列入SDD实现差距。
- 本页示例是契约/历史样例，不是当前UE联调结果；当前配置、分阶段检查与历史样本见[联调指南](integration-alignment-v0.3.md)。Boss RL为独立服务，训练/部署/评估见[RL入口](../../rl/README.md)。
