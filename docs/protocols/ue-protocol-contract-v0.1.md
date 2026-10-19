# Aesir Combat Prototype｜UE5 × 模型服务 协议契约 v0.1

> 兼容契约：v0.1订单、对话及语音接口。2026-10-19按源码基线`a2dd426`校对；需求主文见[SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)。
> 适用范围：仍兼容的单机ARPG订单、语音解析和人格对话。Boss RL是独立工作流，不由本页规定其训练或部署。
> 本轮只修正文档说明，不升级接口或修改模型。Golden示例用于类型核对，不代表已完成UE执行验收。

本文由原《协议格式契约》与《UE5 × 模型服务联调技术规范》合并而成，只保留**类型穷尽定义**与**两端共同契约**，删除会随进度过期的「进度/目标」章节。

> **实现状态说明：** 本文是当前代码已经实现的 v0.1 格式基线。战斗状态快照、自动事件、上下文技能选择、执行回执不属于本版本；请参见[战斗事件与上下文感知战术协议v0.2](combat-tactical-protocol-v0.2.md)。v0.2 中 `/v1/tactical/resolve`（规则策略 v1）、`/v1/combat/events`、`/v1/tactical/executions` 均已在 Python 侧实现。
>
> **当前分工：**本页保留仍兼容的`TacticalOrder`和对话协议；统一指令、世界事件、调试及回执的当前说明见[NPC契约v0.3](npc-contract-v0.3.md)。API版本与人格包版本分开管理，不因存在v0.3删除旧端点。

---

## 1. 目标、边界与本契约要回答的问题

本项目让玩家以文本或语音下达战术命令；Python 服务将自然语言转换为受限的 `TacticalOrder`，UE5 验证并执行该命令。

典型体验：

> “艾莉，等 Boss 眩晕时使用爆裂魔法。”

```text
语音（可选） → ASR 转写 → LLM/规则解析 → TacticalOrder JSON
→ UE 再校验 → 队友任务队列 → Boss 状态触发 → 走位与施法
```

本文要明确回答五个问题：

1. 一个 order 到底有哪些合法形态？（按 `intent` 判别 → 5 份 golden JSON）
2. `when` / `then` / `expires` 各有哪些合法形态？（按 `type` 判别）
3. `priority` 是数字，范围 / 默认 / 排序规则？
4. 协议版本在哪一层校验？（外层 or order 内）
5. 哪些 ID 合法、越界怎么回？（能力目录白名单约束）

### 本契约不覆盖的事

- 不让 LLM 逐帧操控角色、移动、碰撞或技能伤害。
- 不让 Python 作为战斗规则的唯一裁决者。
- 不在首版引入向量数据库、长期记忆、多智能体编排或开放世界任务规划。
- 不让强化学习直接决定伤害、CD、资源消耗或技能是否合法。

---

## 2. 架构与职责划分

| 层 | 唯一职责 | 不得负责 |
| --- | --- | --- |
| UE5 / C++ | 战斗状态、命中、CD、蓝量、导航、动画、技能执行、最终校验 | 调用大模型进行逐帧决策 |
| Python API | 请求编排、Schema 校验、日志、规则/LLM/ASR 适配 | 修改游戏世界或绕过 UE 规则 |
| ASR | 音频转文字 | 解释战术语义 |
| LLM | 文本转受限战术命令 | 直接发出移动、伤害或 Tick 级操作 |
| Boss RL独立服务 | 由[RL入口](../../rl/README.md)定义观测、动作、冻结部署与评估 | 不属于本页NPC订单接口 |

### 运行时拓扑

```text
UE5 客户端                                        Python 本地服务
────────────────────────────                      ───────────────────────────
Push-to-Talk → Audio Capture → WAV/PCM ────────→  /v1/speech/transcribe
                                                    ASR → 转写文本
UE UI / 文本输入 ──────────────────────────────→  /v1/commands/parse
                                                    规则解析器或 LLM
                                                    Pydantic + 能力目录校验
             ←──── TacticalOrder JSON ─────────
UE 再校验 → TacticalOrderComponent → BT/StateTree → GAS/技能系统
```

语音、ASR、LLM 均必须异步。游戏主线程不等待网络响应；超时或服务故障时，队友回退到基础 AI。

---

## 3. 当前技术与权威位置

服务使用FastAPI/Pydantic、规则/可配置LLM解析和mock/本机faster_whisper转写。依赖版本与启动命令集中在[启动指南](../guides/getting-started.md)。UE使用异步HTTP及JSON解释本页类型，实际模块/组件和资产接线由UE仓维护；历史AudioCapture或组件布置建议不是本仓已接入事实。

LLM后端、数据出站与配置生命周期见[LLM指南](../guides/llm-integration.md)。Boss冻结PPO现由独立HTTP服务与UE共享动作执行器接入，见[RL入口](../../rl/README.md)；旧队友走位/ONNX设想不是当前Boss契约或启动前置。

---

## 4. 协议总则

### 4.1 核心原则

1. **LLM 输出不可信。** Python 和 UE 都必须校验。
2. **显示名不进入协议。** 协议只使用稳定 ID；“艾莉”“爆裂魔法”只用于 UI 与 Prompt 映射。
3. **能力目录与命令结构分离。** Schema 定义字段；UE 能力目录决定哪些 ID 当前可用。
4. **低频命令、事件驱动执行。** 仅在按住说话结束或文本提交时请求服务，禁止 Tick 请求。
5. **UE 最终裁决。** 即使命令合法，也必须检查目标存活、距离、资源、冷却和角色状态。

### 4.2 ID 命名

所有 ID 使用小写英文与点号分层：

```text
角色：companion.alice
技能：ability.alice.explosion
技能：ability.alice.basic_attack
状态：state.stunned
状态：state.phase_two
目标选择器：encounter.primary_hostile
目标选择器：party.player
```

这些 ID 应与 UE Gameplay Tag 或 Data Asset 的主键建立一对一映射；不要使用资产路径、动画名或中文显示名作 ID。

---

## 5. API 契约

### 5.1 健康检查

```text
GET /health
```

成功响应：

```json
{
  "status": "ok",
  "service": "aesir-ai-service",
  "protocol_version": "0.1",
  "service_commit": "<运行实例的short SHA，非Git环境为unknown>"
}
```

`/health.protocol_version`当前来自v0.1订单常量，不代表每个端点都使用0.1；端点版本见[v0.3入口矩阵](npc-contract-v0.3.md#1-端点与版本)。`service_commit`用于识别运行实例，不应写死成本地HEAD。

### 5.2 文本命令解析

```text
POST /v1/commands/parse
Content-Type: application/json
```

请求：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "text": "艾莉，等 Boss 眩晕时使用爆裂魔法。",
  "context": {
    "catalog_revision": "dev-001",
    "locale": "zh-CN",
    "agents": [
      {
        "id": "companion.alice",
        "ability_ids": [
          "ability.alice.explosion",
          "ability.alice.basic_attack"
        ]
      }
    ],
    "target_selectors": ["encounter.primary_hostile", "party.player"],
    "state_tags": ["state.stunned", "state.phase_two"]
  }
}
```

成功响应见 §6/§11。不识别文本时仍返回 HTTP `200`，但明确不执行：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": false,
  "message": "当前无法确认该技能或目标。",
  "order": null
}
```

> `POST /parse-command`是保留的调试别名，只传`text`并回填`DEFAULT_CONTEXT`。语音命令不传`context_json`也会使用该目录。正式接入应显式提交当前角色、能力及目标，不用默认Alice目录证明当前游戏/角色授权。

错误语义：

| 情况 | HTTP 状态 | UE 行为 |
| --- | --- | --- |
| 请求字段不合法 | 422 | 显示“命令格式错误”，不创建任务 |
| 文本不可识别 | 200 + `recognized: false` | 显示原因，维持原 AI |
| LLM / ASR 不可用 | 解析LLM可回退规则；ASR失败可502 | 根据实际状态显示原因，维持本地AI；不把降级当动作完成 |
| 超时（UE 建议 3 秒） | UE 本地取消 | 不阻塞主线程，维持原 AI |
| UE 本地校验失败 | UE 记录原因 | 不执行，显示“技能不可用”等原因 |

### 5.3 语音转写

```text
POST /v1/speech/transcribe
Content-Type: multipart/form-data
```

字段：`audio`（WAV/PCM 文件）、`request_id`、`locale`。首版统一上传 **16 kHz、单声道、16-bit PCM WAV**。

响应：

```json
{
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "text": "艾莉，等 Boss 眩晕时使用爆裂魔法。",
  "language": "zh"
}
```

UE 收到转写后再调用 `/v1/commands/parse`。两步请求便于单独调试 ASR 和 LLM；后续可保留组合端点但不得删除这两个基础端点。

> **现状：** 组合端点 `POST /v1/voice/command`（multipart `file` + 可选 `request_id`/`context_json`）已实现，内部先 ASR 再送同一解析层，一次返回 `ParseCommandResponse`。`AESIR_ASR_BACKEND=faster_whisper` 走真实本机 Whisper（默认`small`模型，具体本机识别效果需按配置验证），`mock` 返回固定文本。专用 `POST /v1/speech/transcribe` 已实现，与组合端点并存，长期保留。

---

## 6. 顶层响应（`ParseCommandResponse`）

```json
{
  "protocol_version": "0.1",
  "request_id": "<uuid4 回显，来自请求>",
  "recognized": true,
  "message": "<给 UE HUD 的中文说明，仅展示用途，不作为逻辑字段>",
  "source": "rule | llm | rule_fallback",
  "order": { "order_id": "<uuid4>", "...see §7" },
  "companion_reply": { "reply_text": "...", "emotion_id": "..." }
}
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `protocol_version` | string | 固定 `"0.1"`，**只在响应外层校验**（见 §10.1） |
| `request_id` | string(uuid4) | 必须原样回显请求的 `request_id`；格式校验失败按 422 |
| `recognized` | boolean | `false` 时 `order` 必须为 `null`，且仍 HTTP 200 |
| `message` | string | 仅 UI 用，不含可被 UE/LLM 逻辑依赖的内容 |
| `source` | string | `rule` / `llm` / `rule_fallback`（LLM 失败回退规则的标记），供 UE 日志与降级观测 |
| `order` | order 判别联合 \| null | `recognized=false` 时必为 `null` |
| `companion_reply` | object \| null | 队友人设确认回复 `{reply_text, emotion_id}`（见 `data/personas/` 人格包）；`recognized=false` 时为 `null`。UE 可仅取 `reply_text`/`emotion_id` 做字幕与表情 |

---

## 7. `order` 判别联合（按 `order.intent`）

### 7.1 共享字段（所有意图）

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `order_id` | string(uuid4) | 服务端生成，跨端日志关联 |
| `agent_id` | string(ID) | 必须在请求 `context.agents[].id` 内 |
| `intent` | string(枚举) | 判别的判断字段 |
| `when` | when 判别联合 \| null | 见 §8；`null` = 立即生效 / 持续性指令 |
| `then` | then 判别联合 | 见 §8 |
| `priority` | int | `[0,100]`，默认 `50`，**数值高者优先覆盖**（见 §9） |
| `expires` | expires 判别联合 | 见 §8.4，默认 `{type:"encounter_end"}` |

### 7.2 分支总览

| `intent` | `when` | `then` | 语义 |
| --- | --- | --- | --- |
| `conditional_cast` | `state_entered`(subject+tag) | `cast_ability`(ability_id+target) | 条件满足时施法一次 |
| `hold_ability` | `null` | `hold_ability`(ability_id, active) | 这一整段不释放某技能 |
| `prioritize_attack` | `null` | `set_priority`(mode) | 持续性：调整输出优先级 |
| `follow_keep_distance` | `null` | `follow`(target, keep_distance) | 持续性：跟随并维持距离 |
| `retreat` | `null` | `retreat` | 持续性：撤离、降进攻优先级 |

命令只表达高层意图：`when` 描述何时，`then` 描述做什么。`TacticalOrderComponent` 负责命令生命周期；Behavior Tree/StateTree 决定如何走位；GAS 或既有技能系统决定能否施放。

---

## 8. `when` / `then` / `expires` 判别联合（按 `.type`）

`order` 按 `order.intent` 判别；`when` 按 `when.type` 判别；`then` 按 `then.type` 判别；`expires` 按 `expires.type` 判别。未知 `type` / 未知 `intent` / 未知 `then.type` → **目的地拒绝**（两端都必须校验，§4.1 原则 1）。

### 8.1 `when`（`v0.1` 交付一种）

| `type` | 字段 | 类型 | 约束 |
| --- | --- | --- | --- |
| `state_entered` | `subject` | string(目标选择器ID) | 必须在请求 `context.target_selectors` 内 |
| | `tag` | string(状态Tag) | 必须在请求 `context.state_tags` 内 |

> 持久/Tick 级调度不在本层表达：`when` 只描述“何时条件达成”，达成判断交给 `TacticalOrderComponent` + Boss 状态事件，不放进 `order`。

### 8.2 `then`

各 `then.type` 与现有动作词表**一比一映射**，UE `USTRUCT` 可平滑对应：

| `then.type` | 字段 | 类型 | 对应理论意图 |
| --- | --- | --- | --- |
| `cast_ability` | `ability_id` | string(ID) | `conditional_cast` |
| | `target` | 引用对象 或 目标选择器ID | 见 §10.2 |
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

### 8.4 `expires`（`v0.1` 交付一种）

| `type` | 字段 | 说明 |
| --- | --- | --- |
| `encounter_end` | — | 本场遭遇结束前保持有效（默认） |

---

## 9. `priority` 语义

- 范围 `[0,100]`，默认 `50`。
- **数值高者覆盖低者**（`TacticalOrderComponent` 只在接到更高 `priority` 或 `expires` 到期时才替换当前命令）。
- 同源意图（如两次 `retreat`）不互相覆盖，用 `order_id` 区分。
- 越界（`<0` 或 `>100`）→ 422。

---

## 10. 格式约束收口

### 10.1 `protocol_version` 归属

只在**响应外层**校验（`"0.1"`）。`order` 对象内**不**携带 `protocol_version`，避免两端在两处各校验一份、版本漂移。UE 校验清单第 1 步的“版本不支持”只针对响应最外层字段。

### 10.2 `then.target` 的两种合法形态

1. **目标选择器 ID 字符串**：引用请求 `context.target_selectors`（如 `"party.player"`）。
2. **引用对象**：`{ "ref": "when.subject" }`——引用 `when.subject` 已在条件里解析过的对象，避免重复解析。

> 不允许多义字符串自引用（如裸写 `"when.subject"`）。UE 端对 `{ref:...}` 只有「解析成功 / 报错」两种结果，无字符串前缀猜测逻辑。

### 10.3 能力目录白名单（硬约束）

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

## 11. Golden JSON（5 份完整示例）

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

### 11.1 `conditional_cast`（唯一带 `when` 的意图）

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

### 11.2 `hold_ability`

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

### 11.3 `prioritize_attack`

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

### 11.4 `follow_keep_distance`

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

### 11.5 `retreat`

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

### 11.6 不可识别（golden 负例）

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

## 12. 两张必须同步的映射表

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

## 13. 执行边界与维护

UE接收后核对支持版本、当前可控角色、已实现订单类型、获准能力、可解析目标、有效期/优先级；真正触发时再验目标存活、资源、冷却、距离和忙碌。具体接入顺序与失败场景统一见[联调指南](integration-alignment-v0.3.md#接入顺序与通过条件)，本页不把建议组件表当UE实现清单。

LLM只形成受约束建议，服务与UE都需校验；其配置可来自本机.env或进程环境，密钥不传给UE或提交Git，具体数据流见[LLM指南](../guides/llm-integration.md)。不要由旧订单解析路径推断所有LLM只在commands/voice调用，也不要将NPC rl占位或旧队友走位实验当当前Boss部署。

字段删除或语义变化须升级并协调双方schema、接口测试、示例和UE反序列化；可选扩展也需明确兼容行为。改规则时同步当前需求与验收；新增公开端口、训练或模型格式不是仅改本文能完成的功能。

---

## 附录 A. 陪伴对话 SSE 流式端点（v0.1 附加扩展，2026-09-15）

`POST /v1/companion/chat/stream` 是 `/v1/companion/chat` 的**流式变体**：请求体
复用 `CompanionDialogueRequest`（原样），响应改为 `text/event-stream`（SSE）。
现有 JSON schema 零改动、非流式端点行为零改动，故为 v0.1 附加式扩展、不升版本。

### 帧语法

每帧两行 + 空行，`data` 为单行 JSON：

```
event: delta
data: {"protocol_version":"0.1","text":"好的"}

event: meta
data: {"protocol_version":"0.1","companion_id":"companion.alice","session_id":"...","reply_text":"...完整文本...","emotion_id":"emotion.bright","gesture_id":"gesture.cheerful_idle","facial_expression_id":"face.bright_smile","interruptible":true,"source":"llm","relationship_stage":""}

event: error
data: {"detail":"LLM stream interrupted; this turn is incomplete."}
```

- **delta**（0..N 帧）：`reply_text` 的文本增量，只用于即时展示。
- **meta**（终结帧，1 帧）：完整的 `CompanionDialogueResponse`，**权威数据**——
  最终文案、表现 ID、来源（mock/llm/fallback）以此帧为准，UE 应在收到后
  用它覆盖已展示的增量拼接结果。
- **error**（可选终结帧）：流中途故障（见下），该轮对话不完整。

### 语义规则

- **meta 为权威，delta 尽力而为**：delta 可能缺失（LLM 未按 JSON 顺序输出
  `reply_text` 时服务端不猜测），不能只靠 delta 渲染最终状态。
- **回退语义**：LLM 在发出任何 delta 之前失败 → 服务端静默回退 mock 回复，
  `source:"fallback"`，与非流式路径一致；mock 后端输出单 delta（全文）+ meta。
- **中断行为（与非流式的唯一差异）**：已发出 delta 后流中断 → `error` 帧，
  该轮**不写**会话/长期记忆；非流式路径回退回复会照常写入。已展示一半的
  文本由 UE 自行处理（建议淡出或保留）。
- HTTP 状态恒为 200；流开始前的错误照常返回 404（未登记角色）/ 422（参数
  校验）。
- 建议代理层禁用缓冲（服务端已带 `Cache-Control: no-cache`、`X-Accel-Buffering: no`）。

### 附加扩展（2026-09-17，SDD US6）：可选 `world_context` 请求字段

`CompanionDialogueRequest` 新增**可选**字段 `world_context`（`WorldContext` 结构，
与 `/v1/agent/step`、`/v1/world/events` 使用的世界快照同构）。缺省不传时行为与
v0.1 完全一致，属附加式扩展、不升版本。

- 用途：艾莉回答「现在战况如何 / 周围有什么 / 你状态怎样」这类问题时，先经
  只读查证工具**查证本轮快照**再作答，不用过期状态（US6 验收场景 3）。
- 建议传法：UE 发起对话时附带当前快照（与心跳同一份即可）；不传时上述三类
  问题她将明确表示「说不清」，而不是凭印象编。

### 附加扩展（2026-09-17）：语音陪伴对话 `POST /v1/companion/chat/voice`

`/v1/companion/chat` 的**语音入口**：multipart 音频 → ASR 转写 → 既有对话
链路（记忆 / 关系 / 信号埋点全部生效）。与 `POST /v1/voice/command` 同款
模式，尾部接陪伴对话而非战术指令解析。

- **请求**（multipart/form-data）：`audio`（WAV 16kHz / 单声道 / 16bit，同
  `/v1/speech/transcribe` 约定）+ `companion_id`（默认 `companion.alice`）+
  `game_state`（`exploration|conversation`，默认前者）+ 可选 `session_id` +
  可选 `world_context_json`（`WorldContext` 的 JSON 字符串，同上）。
- **响应**：`CompanionDialogueResponse` 全部字段 + `transcribed_text`（ASR
  转写文本，供 UE 展示「你说了什么」与调试转写质量）。
- **错误语义**：转写后端故障 → 502；未识别出语音内容 → 422（对话里「听错
  还硬答」比「明确听不清」更糟，**不**回退 mock 文本）；参数非法 → 422；
  未登记角色 → 404。
- `AESIR_ASR_BACKEND` 与转写端点共用：`mock` 返回 `AESIR_ASR_MOCK_TEXT`，
  `faster_whisper` 走真实本机 Whisper。


## 附录 B. 对话JSON、状态和数据副作用

`POST /v1/companion/chat`请求由`CompanionDialogueRequest`定义：`text`必填（1～500字符）；`companion_id`默认`companion.alice`；`game_state`为`exploration|conversation`；可选`session_id`（1～64字符）、`world_context`。请求和响应均配置`extra="forbid"`。对话主路径先查已注册角色，未知角色404，非法场景422；配置错误可503。

响应为`protocol_version="0.1"`、角色/会话标识、`reply_text`、表现ID、`interruptible`、`source=mock|llm|fallback`，以及`relationship_stage`、`relationship_stage_display`、`relationship_delta`、`persona_revision`、`memory_layers`。关系阶段是本轮生成前状态，实际关系变化另由delta表达。

- `session_id`只控制短期会话窗口。缺省时不保存该窗口，仍会检索/写入长期事实和印象、读取关系并尝试记录完整对话信号，不是“完全无状态”。
- 正常完成轮次默认尝试将完整`player_text/reply_text`追加到`data/runtime/dialogue_signals/<game>/<companion>.jsonl`；显著声明还可能逐字入长期档案。写失败按实际降级，不保证每轮均落盘成功。
- LLM模式会把人格、当前文本、检索记忆/印象、近期会话及适用查证结果送到配置后端；回环HTTP监听不等于全部本地。发送范围、存储和清理边界见[LLM与数据流](../guides/llm-integration.md)。
- 记忆reset只处理指定角色会话和长期记忆，保留人格、关系和信号日志；可能部分完成，见[v0.3调试接口](npc-contract-v0.3.md#5-调试与记忆重置)。

订单类型中的技能字段沿用v0.1定义；整个NPC领域不要求日常/社交建议均有技能。需要技能的动作必须引用本角色获准能力，单条指令可引用几项尚未冻结；不能把类型字段直接推广成每条领域指令必有一个技能。

## 当前实现与规范的边界

- `ParseCommandRequest`校验版本0.1、UUID请求ID和文本长度，但顶层没有`extra=forbid`；嵌套`ParseCommandContext`及订单判别联合配置了forbid。不能笼统声称所有端点都拒绝多余字段。
- 目录白名单是解析/接收的约束，UE仍须核验当前角色、技能、目标、冷却、距离、忙碌、有效期及游玩/遭遇身份。未知身份、L0能力门控在不同旧入口的检查并不完整，见[v0.3差距表](npc-contract-v0.3.md#7-当前实现差距)。
- 音频格式是传输约定。当前上传路径把文件读为内存字节交给ASR，没有统一的大小/时长/WAV头门禁；不能把文档写了格式等同每项已由服务器强校验。
- v0.3玩家指令、世界事件、有限幂等与观测字段集中到[NPC契约](npc-contract-v0.3.md)；UE接入步骤集中到[联调指南](integration-alignment-v0.3.md)，不在兼容契约重复维护任务状态。
