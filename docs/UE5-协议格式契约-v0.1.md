# Aesir Combat Prototype｜UE5 × 模型服务 协议格式契约 v0.1

> 状态：**格式化金标准（golden）**，作为 UE / Python / LLM 三者共同的反序列化契约
> 配套：《UE5_模型服务联调技术规范_v0.1.md》的本体；本文只聚焦 §5–§7 的**返回类型与格式**，把类型穷尽定义，消除对端只能靠猜的歧义。
> 更新日期：2026-09-03
>
> **实现状态说明：** 本文是当前代码已经实现的 v0.1 格式基线。战斗状态快照、自动事件、上下文技能选择、执行回执不属于本版本；请参见设计草案《[战斗事件与上下文感知战术协议 v0.2](战斗事件与上下文感知战术协议_v0.2-草案.md)》。草案接口尚未实现，不能用于当前联调。

---

## 0. 本文要回答的五个问题

1. 一个 order 到底有哪些合法形态？（按 `intent` 判别 → 5 份 golden JSON）
2. `when` / `then` / `expires` 各有哪些合法形态？（按 `type` 判别）
3. `priority` 是数字，范围 / 默认 / 排序规则？
4. 协议版本在哪一层校验？（外层 or order 内）
5. 哪些 ID 合法、越界怎么回？（能力目录白名单约束）

---

## 1. 判别联合总策略

- **`order`** 按 `order.intent` 判别，5 个分支。
- **`when`** 按 `when.type` 判别，`v0.1` 交付 `state_entered` 一种，接口可扩展。
- **`then`** 按 `then.type` 判别，与现有动作词表一一对应。
- **`expires`** 按 `expires.type` 判别，`v0.1` 交付 `encounter_end` 一种。
- 未知 `type` / 未知 `intent` / 未知 `then.type` → **目的地拒绝**（两端都必须校验，§6.1 原则 1）。

---

## 2. 顶层响应（`ParseCommandResponse`）

```json
{
  "protocol_version": "0.1",
  "request_id": "<uuid4 回显，来自请求>",
  "recognized": true,
  "message": "<给 UE HUD 的中文说明，仅展示用途，不作为逻辑字段>",
  "source": "rule | llm | rule_fallback",
  "order": { "order_id": "<uuid4>", "...see §3" },
  "companion_reply": { "reply_text": "...", "emotion_id": "..." }
}
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `protocol_version` | string | 固定 `"0.1"`，**只在响应外层校验**（见 §7.1） |
| `request_id` | string(uuid4) | 必须原样回显请求的 `request_id`；格式校验失败按 422 |
| `recognized` | boolean | `false` 时 `order` 必须为 `null`，且仍 HTTP 200 |
| `message` | string | 仅 UI 用，不含可被 UE/LLM 逻辑依赖的内容 |
| `source` | string | `rule` / `llm` / `rule_fallback`（LLM 失败回退规则的标记），供 UE 日志与降级观测 |
| `order` | order 判别联合 \| null | `recognized=false` 时必为 `null` |
| `companion_reply` | object \| null | 队友人设确认回复 `{reply_text, emotion_id}`（见 `data/companions/` YAML）；`recognized=false` 时为 `null`。UE 可仅取 `reply_text`/`emotion_id` 做字幕与表情 |

---

## 3. `order` 判别联合（按 `order.intent`）

### 3.1 共享字段（所有意图）

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `order_id` | string(uuid4) | 服务端生成，跨端日志关联 |
| `agent_id` | string(ID) | 必须在请求 `context.agents[].id` 内 |
| `intent` | string(枚举) | 判别的判段字段 |
| `when` | when 判别联合 \| null | 见 §4；`null` = 立即生效 / 持续性指令 |
| `then` | then 判别联合 | 见 §5 |
| `priority` | int | `[0,100]`，默认 `50`，**数值高者优先覆盖**（见 §6） |
| `expires` | expires 判别联合 | 见 §5.4，默认 `{type:"encounter_end"}` |

### 3.2 分支总览

| `intent` | `when` | `then` | 语义 |
| --- | --- | --- | --- |
| `conditional_cast` | `state_entered`(subject+tag) | `cast_ability`(ability_id+target) | 条件满足时施法一次 |
| `hold_ability` | `null` | `hold_ability`(ability_id, active) | 这一整段不释放某技能 |
| `prioritize_attack` | `null` | `set_priority`(mode) | 持续性：调整输出优先级 |
| `follow_keep_distance` | `null` | `follow`(target, keep_distance) | 持续性：跟随并维持距离 |
| `retreat` | `null` | `retreat` | 持续性：撤离、降进攻优先级 |

---

## 4. `when` 判别联合（按 `when.type`）

`v0.1` 交付一种：

| `type` | 字段 | 类型 | 约束 |
| --- | --- | --- | --- |
| `state_entered` | `subject` | string(目标选择器ID) | 必须在请求 `context.target_selectors` 内 |
| | `tag` | string(状态Tag) | 必须在请求 `context.state_tags` 内 |

> 持久/Tick 级调度不在本层表达：`when` 只描述“何时条件达成”，达成判断交给 `TacticalOrderComponent` + Boss 状态事件，不放进 `order`。

---

## 5. `then` 判别联合（按 `then.type`）

各 `then.type` 与现有动作词表**一比一映射**，UE `USTRUCT` 可平滑对应：

| `then.type` | 字段 | 类型 | 对应理论意图 |
| --- | --- | --- | --- |
| `cast_ability` | `ability_id` | string(ID) | `conditional_cast` |
| | `target` | 引用对象 或 目标选择器ID | 见 §7.2 |
| `hold_ability` | `ability_id` | string(ID) | `hold_ability` |
| | `active` | boolean | 默认 `true` |
| `set_priority` | `mode` | string(枚举) | `prioritize_attack` |
| `follow` | `target` | string(目标选择器ID) | `follow_keep_distance` |
| | `keep_distance` | boolean | 默认 `true` |
| `retreat` | — | — | `retreat` |

**`set_priority.mode` 枚举字典（v0.1）：**

| 值 | 含义 |
| --- | --- |
| `basic_attack_first` | 优先普通攻击 |
| `ability_first` | 优先技能（保留） |

### 5.4 `expires` 判别联合

| `type` | 字段 | 说明 |
| --- | --- | --- |
| `encounter_end` | — | 本场遭遇结束前保持有效（默认） |

---

## 6. `priority` 语义

- 范围 `[0,100]`，默认 `50`。
- **数值高者覆盖低者**（`TacticalOrderComponent` 只在接到更高 `priority` 或 `expires` 到期时才替换当前命令）。
- 同源意图（如两次 `retreat`）不互相覆盖，用 `order_id` 区分。
- 越界（`<0` 或 `>100`）→ 422。

---

## 7. 格式约束收口

### 7.1 `protocol_version` 归属

只在**响应外层**校验（`"0.1"`）。`order` 对象内**不**携带 `protocol_version`，避免两端在两处各校验一份、版本漂移。UE 校验清单第 1 步的“版本不支持”只针对响应最外层字段。

### 7.2 `then.target` 的两种合法形态

1. **目标选择器 ID 字符串**：引用请求 `context.target_selectors`（如 `"party.player"`）。
2. **引用对象**：`{ "ref": "when.subject" }`——引用 `when.subject` 已在条件里解析过的对象，避免重复解析。

> 不允许多义字符串自引用（如裸写 `"when.subject"`）。UE 端对 `{ref:...}` 只有「解析成功 / 报错」两种结果，无字符串前缀猜测逻辑。

### 7.3 能力目录白名单（硬约束）

**响应 `order` 只能引用请求 `context` 里出现过的 ID：**

- `agent_id` ∈ `context.agents[].id`
- `when.subject` / `then.target`（字符串形态）∈ `context.target_selectors`
- `when.tag` ∈ `context.state_tags`
- `then.ability_id` ∈ `context.agents[agent_id].ability_ids`

**越界边界（错误表划清）：**

| 情况 | 返回 |
| --- | --- |
| 请求 JSON 结构非法（缺字段 / 非 uuid / priority 越界） | HTTP `422` |
| 文本不可识别 / 意图落不到目录内 ID | HTTP `200` + `recognized:false` + `order:null` |

> 即：**“请求本身不合法”回 422；“合法请求但语义落空”回 200+recognized:false**。绝不把“目录外的 ID”当成 422，也不把“结构非法”静默降级成 recognized:false。

---

## 8. Golden JSON（5 份完整示例）

以下请求均使用同一能力目录：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "text": "<不同意图的不同输入>",
  "context": {
    "catalog_revision": "dev-001",
    "locale": "zh-CN",
    "agents": [
      {
        "id": "companion.alice",
        "ability_ids": ["ability.alice.explosion", "ability.alice.basic_attack"]
      }
    ],
    "target_selectors": ["encounter.primary_hostile", "party.player"],
    "state_tags": ["state.stunned", "state.phase_two"]
  }
}
```

### 8.1 `conditional_cast`（唯一带 `when` 的意图）

**请求 text：** `艾莉，等 Boss 眩晕时使用爆裂魔法。`

**响应 order：**

```json
{
  "order_id": "ea876be5-d861-4064-8f64-4ccb8a74db99",
  "agent_id": "companion.alice",
  "intent": "conditional_cast",
  "when": {
    "type": "state_entered",
    "subject": "encounter.primary_hostile",
    "tag": "state.stunned"
  },
  "then": {
    "type": "cast_ability",
    "ability_id": "ability.alice.explosion",
    "target": { "ref": "when.subject" }
  },
  "priority": 80,
  "expires": { "type": "encounter_end" }
}
```

### 8.2 `hold_ability`

**请求 text：** `艾莉，这一整场都不要放爆裂魔法。`

**响应 order：**

```json
{
  "order_id": "9f1b8c3a-c2d4-4f6e-8a0b-5e3d7f9c11a2",
  "agent_id": "companion.alice",
  "intent": "hold_ability",
  "when": null,
  "then": {
    "type": "hold_ability",
    "ability_id": "ability.alice.explosion",
    "active": true
  },
  "priority": 60,
  "expires": { "type": "encounter_end" }
}
```

### 8.3 `prioritize_attack`

**请求 text：** `艾莉，优先普通攻击。`

**响应 order：**

```json
{
  "order_id": "4d7a2ef1-9b3c-4c5d-8e6f-0a2b4c6d8e10",
  "agent_id": "companion.alice",
  "intent": "prioritize_attack",
  "when": null,
  "then": {
    "type": "set_priority",
    "mode": "basic_attack_first"
  },
  "priority": 50,
  "expires": { "type": "encounter_end" }
}
```

### 8.4 `follow_keep_distance`

**请求 text：** `艾莉，跟着我并保持距离。`

**响应 order：**

```json
{
  "order_id": "b1c2d3e4-5f67-489a-bcde-f01234567890",
  "agent_id": "companion.alice",
  "intent": "follow_keep_distance",
  "when": null,
  "then": {
    "type": "follow",
    "target": "party.player",
    "keep_distance": true
  },
  "priority": 40,
  "expires": { "type": "encounter_end" }
}
```

### 8.5 `retreat`

**请求 text：** `艾莉，撤退并优先保命。`

**响应 order：**

```json
{
  "order_id": "c3d4e5f6-7089-4bcd-ef01-234567890123",
  "agent_id": "companion.alice",
  "intent": "retreat",
  "when": null,
  "then": {
    "type": "retreat"
  },
  "priority": 90,
  "expires": { "type": "encounter_end" }
}
```

### 8.6 不可识别（golden 负例）

**响应：**

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": false,
  "message": "当前无法确认该技能或目标。",
  "order": null
}
```

---

## 9. 两张必须同步的映射表

| 现有动作类型（模型服务旧式） | `then.type`（本契约） |
| --- | --- |
| `CastAbility` | `cast_ability` |
| `HoldAbility` | `hold_ability` |
| `Attack` | `set_priority`(`basic_attack_first`) |
| `Follow` | `follow` |
| `Retreat` | `retreat` |

| 现有 intent 名（旧式） | `intent`（本契约，不变） |
| --- | --- |
| `conditional_cast` | `conditional_cast` |
| `hold_ability` | `hold_ability` |
| `prioritize_attack` | `prioritize_attack` |
| `follow_keep_distance` | `follow_keep_distance` |
| `retreat` | `retreat` |

---

## 10. 落地清单

- [ ] Python：`TacticalOrder` 改为按 `intent` 判别 + `when`/`then`/`expires` 判别联合 + ID 字符串 + `priority:int`
- [ ] Python：`ParseCommandResponse` 增加 `request_id`/`order_id`；`order` 内移除硬编码 `protocol_version`
- [ ] Python：解析时校验 ID ∈ `context`；目录外 ID → `recognized:false`
- [ ] LLM prompt：改喂 `context` 的 ID 目录 + 判别联合结构说明 + 5 份 golden 示例
- [ ] UE：`FTacticalOrder` 实现判别反序列化 + `{ref:...}` 解析 + UUID 校验
- [ ] 测试：5 份 golden JSON 各配 1 例合法 + 1 例未知 type/越界 ID 负例
