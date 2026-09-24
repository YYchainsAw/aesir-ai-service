# Aesir Combat Prototype｜UE5 × 模型服务 协议契约 v0.1

> 状态：**格式化金标准（golden）**，作为 UE / Python / LLM 三者共同的反序列化契约。
> 适用范围：单机 ARPG 的语音战术指挥、队友任务执行与后续 RL 走位策略。
> 更新日期：2026-09-14（补注演进方向；类型定义本身未改动）

本文由原《协议格式契约》与《UE5 × 模型服务联调技术规范》合并而成，只保留**类型穷尽定义**与**两端共同契约**，删除会随进度过期的「进度/目标」章节。

> **实现状态说明：** 本文是当前代码已经实现的 v0.1 格式基线。战斗状态快照、自动事件、上下文技能选择、执行回执不属于本版本；请参见《[战斗事件与上下文感知战术协议 v0.2(combat-tactical-protocol-v0.2.md)》。v0.2 中 `/v1/tactical/resolve`（规则策略 v1）、`/v1/combat/events`、`/v1/tactical/executions` 均已在 Python 侧实现。
>
> **演进方向（2026-09-13 起）：** 项目定位升级为「NPC 人格与行为代理」（需求规格见 [SDD v1.0](../planning/aesir-agent-sdd-v1.0.md)）。v0.1 的 `TacticalOrder` 将并入**单一指令体系**的统一信封（按行为类型判别的联合类型，见 SDD 章程原则 VI 与 FR-045），不另起平行协议族；本文格式在迁移前保持不变。

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
| RL 策略 | 站位、躲避、接近/撤离建议 | 伤害结算和技能规则 |

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

## 3. 锁定技术栈

| 范围 | 选型 | 状态 / 说明 |
| --- | --- | --- |
| 游戏端 | UE 5.8、C++、Blueprint、Enhanced Input | 已有项目基础 |
| UE AI | `TacticalOrderComponent` + Blackboard + Behavior Tree 或 StateTree | 首版优先选一种，不能混用同一决策职责 |
| UE 战斗事件 | Gameplay Tags 或显式 C++ Delegate | Boss 眩晕等状态必须由事件/Tag 提供 |
| UE 通信 | `FHttpModule`、`Json`、`JsonUtilities` | 本机 HTTP + JSON；首版不使用 WebSocket/gRPC |
| UE 语音 | Audio Capture 插件、`AudioCaptureCore` | C++ 采集原始 PCM；Blueprint 可用于原型验证 |
| API 服务 | Python 3.12、FastAPI、Uvicorn、Pydantic 2、HTTPX | 已建立 |
| 配置 | `python-dotenv`、`.env` | 已安装使用 |
| ASR | 首版 ASR Adapter；本地方案使用 `faster-whisper` | 已接线：`AESIR_ASR_BACKEND=faster_whisper`（`small` 模型，`mock` 可回退） |
| LLM | 支持结构化 JSON 输出的云端或本地 Provider | 已接入：OpenAI 兼容共享 Client（默认 DeepSeek，已实测） |
| RL 训练 | PyTorch、Gymnasium、Stable-Baselines3 | 在 UE 训练场稳定后才加入 |
| RL 部署 | ONNX + UE 端本地推理 | 先验证 Python 推理，再导出 ONNX |

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
  "protocol_version": "0.1"
}
```

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

> `POST /parse-command` 是早期原型别名，迁移期保留为调试入口，只传 `text`、服务端回填默认能力目录。

错误语义：

| 情况 | HTTP 状态 | UE 行为 |
| --- | --- | --- |
| 请求字段不合法 | 422 | 显示“命令格式错误”，不创建任务 |
| 文本不可识别 | 200 + `recognized: false` | 显示原因，维持原 AI |
| LLM / ASR 不可用 | 502/503 | 显示“语音服务不可用”，维持原 AI |
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

> **现状：** 组合端点 `POST /v1/voice/command`（multipart `file` + 可选 `request_id`/`context_json`）已实现，内部先 ASR 再送同一解析层，一次返回 `ParseCommandResponse`。`AESIR_ASR_BACKEND=faster_whisper` 走真实本机 Whisper（默认 `small` 模型，已端到端验证），`mock` 返回固定文本。专用 `POST /v1/speech/transcribe` 已实现，与组合端点并存，长期保留。

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
| `companion_reply` | object \| null | 队友人设确认回复 `{reply_text, emotion_id}`（见 `data/companions/` YAML）；`recognized=false` 时为 `null`。UE 可仅取 `reply_text`/`emotion_id` 做字幕与表情 |

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

## 13. UE5 侧实施规格

### 13.1 必备模块与组件

在 UE 项目的 `.Build.cs` 中加入：

```text
HTTP
Json
JsonUtilities
AudioCapture
AudioCaptureCore
```

需要的 UE 组件：

| 组件 | 推荐位置 | 职责 |
| --- | --- | --- |
| `UCommandServiceSubsystem` | `GameInstanceSubsystem` | 异步 HTTP、超时、JSON 序列化和回调分发 |
| `UVoiceCommandComponent` | PlayerController / Local Player | Push-to-Talk、音频缓存、WAV 编码 |
| `UTacticalOrderComponent` | 队友角色或其 AI Controller | 保存/取消/完成命令，暴露失败原因 |
| Boss 状态组件 | Boss Character | 广播 `state.stunned`、阶段切换、死亡等事件 |

### 13.2 UE 最终校验清单

接收 JSON 后，UE 必须按顺序验证：

1. `protocol_version` 是否支持。
2. `agent_id` 是否存在、可控制且未死亡。
3. `intent`、`when.type`、`then.type` 是否为已实现类型。
4. `ability_id` 是否属于该队友的能力目录。
5. `subject` 与 `target` 是否为当前可解析对象。
6. 命令是否已过期或被更高优先级命令覆盖。
7. 触发时再检查目标存活、蓝量、冷却、距离和角色状态。

### 13.3 事件与 AI

Boss 眩晕应由明确状态或事件驱动，例如：

```text
Gameplay Tag：state.stunned
Delegate：OnBossStunned
Blackboard Key：BossCombatState
```

禁止以“某动画正在播放”作为战术触发条件。

---

## 14. 模型服务实施规格

### 14.1 LLM 接入位置

LLM 只在下列路径接入：

```text
app/api/health.py / app/api/v1/commands.py / app/api/v1/voice.py
  → app/services/parsers/command_parser.py
    → app/services/parsers/llm.py
      → app/services/llm/client.py（共享 OpenAI 兼容 Client，factory 按配置创建）
```

`LLMCommandParser` 的唯一输出是本契约的 JSON。其处理步骤：

1. 接收文本和 UE 能力目录。
2. 将目录中的稳定 ID 加入 Prompt。
3. 请求结构化 JSON 输出。
4. 用 Pydantic 验证响应。
5. 校验 ID 是否存在于请求上下文。
6. 失败时回退 `RuleCommandParser`，或返回 `recognized: false`。

LLM Provider 的 API Key、模型名和 Base URL 只存在 `.env`，绝不传给 UE 或提交 Git。

### 14.2 ASR 接入位置

```text
app/services/transcribers/base.py          # ASRBackend 抽象 + TranscriptionError
app/services/transcribers/mock.py           # 固定文本自测后端
app/services/transcribers/faster_whisper.py # 真实本机 Whisper
app/services/transcribers/factory.py        # 按 AESIR_ASR_BACKEND 选后端
```

`ASRBackend.transcribe(audio_bytes)` 返回文本。它不调用 LLM，也不生成战术命令。

### 14.3 RL 接入位置

RL 在命令得到 UE 接受后才参与。它的输入为已脱敏、固定长度的战斗状态；输出为低频走位建议，例如方向、距离档位或目标站位。

```text
TacticalOrder（等待眩晕施法）
→ RL：安全站位 / 躲避 / 接近施法范围
→ UE：移动、导航、技能合法性检查与执行
```

首版必须先完成规则 AI 基线。RL 只替换“怎么移动”，不替换“执行什么命令”。

---

## 15. 版本与变更规则

- `protocol_version` 为两端共同版本。字段删除、字段含义变化或 ID 语义变化必须升级版本。
- 仅新增可选字段时，保留旧版本兼容并记录迁移期限。
- UE 与 Python 启动时应记录支持的协议版本和 `catalog_revision`。
- 每个请求使用 `request_id`；每个生成命令使用 `order_id`，便于跨端定位日志。
- 修改本契约时，必须同步更新 Pydantic Schema、UE `USTRUCT`、接口测试与示例 JSON。

---

## 16. 当前明确不做的技术决策

- 不使用 WebSocket：语音指令是低频请求，HTTP 更易调试和恢复。
- 不让 UE 直接携带/调用 LLM API Key。
- 不让模型输出 UE 资产路径、动画名、原始坐标或 C++ 函数名。
- 不将模型权重、训练缓存、`.env` 或 API Key 提交 Git。
- 不在队友 AI、Boss 状态和技能系统未完成前开始 RL 在线训练。

---

## 17. 落地清单

- [x] Python：`TacticalOrder` 改为按 `intent` 判别 + `when`/`then`/`expires` 判别联合 + ID 字符串 + `priority:int`
- [x] Python：`ParseCommandResponse` 增加 `request_id`/`order_id`；`order` 内移除硬编码 `protocol_version`
- [x] Python：解析时校验 ID ∈ `context`；目录外 ID → `recognized:false`
- [x] LLM prompt：改喂 `context` 的 ID 目录 + 判别联合结构说明 + 5 份 golden 示例
- [ ] UE：`FTacticalOrder` 实现判别反序列化 + `{ref:...}` 解析 + UUID 校验
- [x] 测试：5 份 golden JSON 各配 1 例合法 + 1 例未知 type/越界 ID 负例

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

### 附加扩展（2026-09-21，SDD US4 加固 T074/T075）：主入口文本指令

`POST /v1/agent/step` 携带可选 `text` 字段时，与 `/v1/tactical/command`
共用同一意图解析与决策层（规则/LLM 门面，按域路由），不再返回
`TEXT_PIPELINE_PENDING` 骨架原因码：

- **战斗意图**（治疗/护盾/爆发/等眩晕集火/撤退，6 类）：复用
  `resolve_intent` 战术决策（含 US2 关系阶段调制），快照 `world_context.combat`
  存在时产出统一信封 `DirectiveEnvelope`（`domain="combat"`，
  `source="player_command"`，action_type 取 combat 白名单
  major_heal/quick_heal/shield/burst/retreat）；未携带战斗快照 →
  `action="none"` + `COMBAT_CONTEXT_MISSING`；决策不可执行 → 原因码 +
  `reply_text` 说明。
- **非战斗意图**（T074 新增白名单）：`follow_player` / `inspect_interactable`
  / `pickup_item` / `rest_here` / `wait_here`，映射到 agency 行为目录
  （follow/inspect/pickup/rest/wait），并按当前 `scene` 做目录域校验
  （不匹配 → `BEHAVIOR_NOT_IN_SCENE`）、目标类型/距离校验（有目标行为取快照内
  最近可交互物，无合适目标 → `NO_VALID_TARGET`，不虚构目标）。
- **不可识别文本**：`action="none"` + `INTENT_UNRECOGNIZED` + 澄清
  `reply_text`，不猜测执行（FR-028）。
- 意图解析来源进 `observability.source`（`rule`/`llm`/`rule_fallback`），
  关系阶段进 `observability.relationship_stage`，原因码完整可解释（US7 前置）。

### 附加扩展（2026-09-21，SDD US7 T076/T077）：链路信息字段与调试台

- **链路字段补全（T076）**：`AgentStepObservability` 新增 `persona_revision`
  （人设 YAML 的 `profile_version`）与 `memory_layers`（本轮注入记忆条数；
  心跳路径为空字典）；`CompanionDialogueResponse` 同样新增 `persona_revision`
  与 `memory_layers`（`{"long_term": n, "impressions": m}`）；tactical
  `Observability` 新增 `persona_revision`。全部为可选字段，缺省空——UE
  不应依赖其做表现逻辑，仅供调试与归因。
- **调试台（T077）**：`GET /v1/console/state` 返回扩展为完整调试视图：
  `relationship_stage` / `relationship_value`（关系）、`last_scene` /
  `last_emotion_id`（运行期最近观测，服务重启后为空）、`recent_memory`
  （按重要性前 5 条）、`persona_revision` / `agency_policy_revision` /
  `tactical_policy_revision`（三个策略版本）。
- **指标采集（T079）**：`.venv/Scripts/python -m scripts.metrics_report`
  汇总执行回执分布、降级次数、复读轮数、负反馈与话题延续率
  （`--json` 输出机器可读格式）。

### 附加扩展（2026-09-21）：记忆写入链路（对话事实 + 世界事件共同经历）

**协议零变更**（请求/响应字段与上面完全一致），仅说明两个端点在处理成功后的
记忆副作用——UE 侧无需任何改动，但调试时可据此预期「她为什么记得这件事」：

- `POST /v1/companion/chat`（含 `/chat/voice` 与流式变体）：LLM 顺带抽出
  玩家陈述过的**事实**（0~3 条第三人称陈述）写入长期档案层，经接地校验
  （实词须大部分出自玩家真说过的话）后才落档——**编造的事实会被丢弃**。
  下一轮起这些事实作为「她确定知道的事」注入，她可以直说，但不得加细节。
- `POST /v1/world/events`（含 v0.2 `POST /v1/combat/events`）：有共同经历
  语义的事件（`region_first_entered` / `gift_given` /
  `player_protected_companion` / `promise_kept` / `companion_recovered` /
  `boss_defeated`）写入经历摘要层；瞬时战斗状态（`player_hp_critical` /
  `companion_mp_low` / `boss_stunned` 等）**不**入记忆。文案里的细节只取
  请求 `details`（`item_id` / `promise_id` / `boss_id` / `region_id`）或快照
  地区，取不到就写泛一点，服务端不推断任何未上报的名字。
- **幂等**：同一 `event_id` 重放（`duplicate: true`）不重复记共同经历；
  记忆文件损坏/不可写时静默降级，事件响应照常返回（FR-011）。

### 附加扩展（2026-09-22）：对话推动关系

**响应新增一个可选字段**（附加式扩展，不升版本）：

- `CompanionDialogueResponse.relationship_delta`（int，默认 0）：本轮玩家发言的
  情感质量实际造成的关系增减（+1/+2/-1/-2；冷却窗口或每日上限吃掉则为 0）。
  UE 可用作好感度反馈动效（心形粒子/震动），不应依赖其做逻辑。
- 信号由 LLM 顺带判定（none/warm/deep/cold/hurtful，绝大多数轮次为 none），
  写入复用关系规则层全套（同类事件冷却 300 秒、每日正向净上限 15 与事实
  事件共享、负向不限、持久化与损坏降级）。事件类型与数值见
  `data/policy/relationship_policy.yaml` 的 `dialogue_*` 条目。
- `relationship_stage` 读的是本轮生成**前**的值——对话造成升档时，阶段变化自
  下一轮生效（下一轮的称呼/语气/硬边界自动跟随，无需 UE 处理）。
- mock/回退路径不推动关系（规则判不了情感质量，宁缺毋滥）；关系层故障静默
  降级为 delta=0，对话照常（FR-011）。
