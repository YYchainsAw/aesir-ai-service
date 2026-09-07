# Aesir Combat Prototype｜UE5 × 模型服务联调技术规范 v0.1

> 状态：**拟定，作为 UE 与 Python 两端的共同契约**  
> 更新日期：2026-09-03  
> 适用范围：单机 ARPG 的语音战术指挥、队友任务执行与后续 RL 走位策略。

## 1. 目标与边界

本项目让玩家以文本或语音下达战术命令；Python 服务将自然语言转换为受限的 `TacticalOrder`，UE5 验证并执行该命令。

典型体验：

> “艾莉，等 Boss 眩晕时使用爆裂魔法。”

```text
语音（可选） → ASR 转写 → LLM/规则解析 → TacticalOrder JSON
→ UE 再校验 → 队友任务队列 → Boss 状态触发 → 走位与施法
```

### 本规范不做的事

- 不让 LLM 逐帧操控角色、移动、碰撞或技能伤害。
- 不让 Python 作为战斗规则的唯一裁决者。
- 不在首版引入向量数据库、长期记忆、多智能体编排或开放世界任务规划。
- 不让强化学习直接决定伤害、CD、资源消耗或技能是否合法。

## 2. 当前模型服务进度

项目目录：`F:\python\aesir-ai-service`（开发分支 `develop-dyh`）

### 已完成

- Python 3.12 虚拟环境、GitHub 仓库与 FastAPI 服务骨架。
- `GET /health` 健康检查（返回 `protocol_version: "0.1"`）。
- 契约 v0.1：`POST /v1/commands/parse`（能力目录 `context` + `request_id`），`POST /parse-command` 保留为遗留别名。
- `RuleCommandParser`：支持条件施法、保留技能、优先普攻、跟随保持距离、撤退五种规则指令（判别联合 + ID 白名单校验）。
- `LLMCommandParser`：共享 OpenAI 兼容 `LLMClient`（默认 DeepSeek），输出严格 Pydantic 校验 + 目录越界拦截；失败/不确定时回退规则解析器（`source: rule_fallback`）。
- `POST /v1/voice/command` 组合端点：音频 → ASR → 同一解析层；`AESIR_ASR_BACKEND=faster_whisper` 走真实本机 Whisper（`small` 模型，已端到端验证），`mock` 返回固定文本。
- `POST /v1/companion/chat` 非战斗陪伴对话（mock / llm 后端，YAML 人设）。
- v0.2 第一阶段（2026-09-07）：`CombatContext`/`TacticalIntent`/`TacticalDecision` schema + `POST /v1/tactical/resolve` 规则策略 v1 + 85 例（20 意图 × 4 战况）回归评测集；详见 v0.2 草案文档。
- pytest 全绿：169 通过 + 2 条冒烟跳过（`AESIR_ASR_SMOKE=1` 门控，默认跳过）。
- `.env.example`、运行时/ML/开发测试依赖拆分、接口测试与中文文档。

### 当前阻塞

无。测试与本地启动均可直接复现（见 `docs/启动说明.md`）。

### 尚未开始

- UE 侧 HTTP 客户端、`FTacticalOrder`、队友任务组件与 Boss 状态事件。
- ~~真实中文人声的 ASR 命中率与延迟调优~~（已取消，见开发记录 2026-09-07）。
- 模型评测集（≥30 条中文有效/无效战术命令）。
- RL 训练环境、奖励函数、ONNX 导出与 UE 推理。

## 3. 架构决策

### 3.1 职责划分

| 层 | 唯一职责 | 不得负责 |
| --- | --- | --- |
| UE5 / C++ | 战斗状态、命中、CD、蓝量、导航、动画、技能执行、最终校验 | 调用大模型进行逐帧决策 |
| Python API | 请求编排、Schema 校验、日志、规则/LLM/ASR 适配 | 修改游戏世界或绕过 UE 规则 |
| ASR | 音频转文字 | 解释战术语义 |
| LLM | 文本转受限战术命令 | 直接发出移动、伤害或 Tick 级操作 |
| RL 策略 | 站位、躲避、接近/撤离建议 | 伤害结算和技能规则 |

### 3.2 运行时拓扑

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

## 4. 锁定技术栈

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

## 5. 协议总则

### 5.1 核心原则

1. **LLM 输出不可信。** Python 和 UE 都必须校验。
2. **显示名不进入协议。** 协议只使用稳定 ID；“艾莉”“爆裂魔法”只用于 UI 与 Prompt 映射。
3. **能力目录与命令结构分离。** Schema 定义字段；UE 能力目录决定哪些 ID 当前可用。
4. **低频命令、事件驱动执行。** 仅在按住说话结束或文本提交时请求服务，禁止 Tick 请求。
5. **UE 最终裁决。** 即使命令合法，也必须检查目标存活、距离、资源、冷却和角色状态。

### 5.2 ID 命名

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

## 6. 目标 API 契约

当前 `/parse-command` 是原型接口。UE 正式接入前，升级为本节规定的版本化接口；原接口可在迁移期保留为调试别名。

### 6.1 健康检查

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

### 6.2 文本命令解析

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

成功响应：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": true,
  "message": "艾莉将在主要敌人眩晕时施放爆裂魔法。",
  "order": {
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
    "expires": {
      "type": "encounter_end"
    }
  }
}
```

不识别文本时，接口仍返回 HTTP `200`，但必须明确不执行：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": false,
  "message": "当前无法确认该技能或目标。",
  "order": null
}
```

错误语义：

| 情况 | HTTP 状态 | UE 行为 |
| --- | --- | --- |
| 请求字段不合法 | 422 | 显示“命令格式错误”，不创建任务 |
| 文本不可识别 | 200 + `recognized: false` | 显示原因，维持原 AI |
| LLM / ASR 不可用 | 503 | 显示“语音服务不可用”，维持原 AI |
| 超时（UE 建议 3 秒） | UE 本地取消 | 不阻塞主线程，维持原 AI |
| UE 本地校验失败 | UE 记录原因 | 不执行，显示“技能不可用”等原因 |

### 6.3 语音转写

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

UE 收到转写后再调用 `/v1/commands/parse`。两步请求便于单独调试 ASR 和 LLM；后期若需要压缩调用，可由 Python 添加组合端点，但不得删除这两个基础端点。

> **现状**：已实现组合端点 `POST /v1/voice/command`（multipart `file` + 可选 `request_id`/`context_json`），内部先 ASR 再送同一解析层，一次返回 `ParseCommandResponse`。`AESIR_ASR_BACKEND=faster_whisper` 时走真实本机 Whisper 转写（默认 `small` 模型，已端到端验证），`mock` 返回固定文本用于自测。专用 `POST /v1/speech/transcribe` 已实现（multipart 字段 `audio` + 可选 `request_id`/`locale`，返回 `{request_id, text, language}`），与组合端点并存，长期保留。

## 7. TacticalOrder 语义

第一阶段正式支持下列意图；字段相同但 `when`/`then` 按意图增减。

| `intent` | 用途 | 示例动作 |
| --- | --- | --- |
| `conditional_cast` | 条件满足时施法 | Boss 眩晕时施放技能 |
| `hold_ability` | 保留某项技能 | 不在普通循环中释放大招 |
| `prioritize_attack` | 调整输出优先级 | 优先普通攻击 |
| `follow_keep_distance` | 调整跟随策略 | 跟随玩家并维持距离 |
| `retreat` | 调整生存策略 | 撤离、降低进攻优先级 |

命令只表达高层意图：`when` 描述何时，`then` 描述做什么。`TacticalOrderComponent` 负责命令生命周期；Behavior Tree/StateTree 决定如何走位；GAS 或既有技能系统决定能否施放。

## 8. UE5 侧实施规格

### 必备模块与组件

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

### UE 最终校验清单

接收 JSON 后，UE 必须按顺序验证：

1. `protocol_version` 是否支持。
2. `agent_id` 是否存在、可控制且未死亡。
3. `intent`、`when.type`、`then.type` 是否为已实现类型。
4. `ability_id` 是否属于该队友的能力目录。
5. `subject` 与 `target` 是否为当前可解析对象。
6. 命令是否已过期或被更高优先级命令覆盖。
7. 触发时再检查目标存活、蓝量、冷却、距离和角色状态。

### 事件与 AI

Boss 眩晕应由明确状态或事件驱动，例如：

```text
Gameplay Tag：state.stunned
Delegate：OnBossStunned
Blackboard Key：BossCombatState
```

禁止以“某动画正在播放”作为战术触发条件。

## 9. 模型服务实施规格

### 9.1 LLM 接入位置

LLM 只在下列路径接入：

```text
app/api/routes.py / app/api/v1/voice.py
  → app/services/command_parser.py
    → app/services/parsers/llm.py
      → app/services/llm/client.py（共享 OpenAI 兼容 Client，factory 按配置创建）
```

`LLMCommandParser` 的唯一输出是本规范的 JSON。其处理步骤：

1. 接收文本和 UE 能力目录。
2. 将目录中的稳定 ID 加入 Prompt。
3. 请求结构化 JSON 输出。
4. 用 Pydantic 验证响应。
5. 校验 ID 是否存在于请求上下文。
6. 失败时回退 `RuleCommandParser`，或返回 `recognized: false`。

LLM Provider 的 API Key、模型名和 Base URL 只存在 `.env`，绝不传给 UE 或提交 Git。

### 9.2 ASR 接入位置

```text
app/services/transcribers/base.py          # ASRBackend 抽象 + TranscriptionError
app/services/transcribers/mock.py           # 固定文本自测后端
app/services/transcribers/faster_whisper.py # 真实本机 Whisper
app/services/transcribers/factory.py        # 按 AESIR_ASR_BACKEND 选后端
```

`ASRBackend.transcribe(audio_bytes)` 返回文本。它不调用 LLM，也不生成战术命令。

### 9.3 RL 接入位置

RL 在命令得到 UE 接受后才参与。它的输入为已脱敏、固定长度的战斗状态；输出为低频走位建议，例如方向、距离档位或目标站位。

```text
TacticalOrder（等待眩晕施法）
→ RL：安全站位 / 躲避 / 接近施法范围
→ UE：移动、导航、技能合法性检查与执行
```

首版必须先完成规则 AI 基线。RL 只替换“怎么移动”，不替换“执行什么命令”。

## 10. 近期开发目标

### P0：恢复可验证状态（已完成 ✅）

- 安装 `requirements-dev.txt` 并让全部测试通过。
- 为现有 `/health` 和 `/parse-command` 保留回归测试。
- 在 README 记录本地启动、测试和 `.env` 使用方式。

**验收（已达成）：** `pytest -q` 169 通过 + 2 条冒烟跳过；`GET /health` 返回 `ok`；五类规则命令及未知命令均有测试。

### P1：冻结联调协议（已完成 ✅）

- 按第 6 节将现有硬编码占位符的 `Literal` Schema 改为 ID 字符串。
- 增加 `request_id`、`catalog_revision`、`context` 与 `order_id`。
- 新增 `/v1/commands/parse`，原 `/parse-command` 暂作兼容入口。
- 为协议示例、非法 ID、未知 ID、版本不支持增加测试。

**验收（已达成）：** Python 能根据请求内能力目录拒绝未知角色、技能和状态；UE 未接入时可用 API 文档手动验证。

### P2：UE 文本联调（先于语音，待 UE 侧启动）

- UE 实现 `FTacticalOrder`、`UCommandServiceSubsystem` 与 JSON 映射。
- UE 使用调试按钮或文本输入请求 Python，而不是在 UE 内解析自然语言。
- UE 先接收 JSON 并记录/显示任务；尚无队友 AI 时允许只验证反序列化与本地校验。

**验收：** Python 返回的 `conditional_cast` JSON 能在 UE 日志/HUD 中显示为可读任务，非法 JSON 被安全拒绝。

### P3：首个战斗闭环与 LLM（Python 侧已完成，UE 侧待做）

- 实现一名队友、一个 Boss、`state.stunned` 与一个可触发技能。（UE 侧待做）
- 接入真实 `LLMCommandParser`，但保留规则解析器回退。（已接入并实测，见 `docs/LLM-联调指南.md`）
- 建立至少 30 条中文有效/无效战术命令测试集。（待建；现有 pytest 已覆盖 golden 正/负例）

**验收：** 文本“艾莉，等 Boss 眩晕时使用爆裂魔法”能被模型正确转换、UE 验证、队友执行；模型不可用时规则命令仍可执行。

### P4：Push-to-Talk 与 ASR（Python 侧已打通组合端点，UE 侧待做）

- UE Audio Capture 采集与 WAV 编码。（待 UE 侧）
- `/v1/speech/transcribe` 和 ASR Adapter。（ASR 已接线 faster-whisper；专用 `/v1/speech/transcribe` 端点已实现，组合端点 `/v1/voice/command` 已可用）
- HUD 显示录音中、转写文本、解析中、命令已接受/拒绝。（待 UE 侧）

**验收：** 按住说话到命令入队全链路不阻塞游戏主线程；失败能给出可理解反馈。

## 11. 版本与变更规则

- `protocol_version` 为两端共同版本。字段删除、字段含义变化或 ID 语义变化必须升级版本。
- 仅新增可选字段时，保留旧版本兼容并记录迁移期限。
- UE 与 Python 启动时应记录支持的协议版本和 `catalog_revision`。
- 每个请求使用 `request_id`；每个生成命令使用 `order_id`，便于跨端定位日志。
- 修改本规范时，必须同步更新 Pydantic Schema、UE `USTRUCT`、接口测试与示例 JSON。

## 12. 当前明确不做的技术决策

- 不使用 WebSocket：语音指令是低频请求，HTTP 更易调试和恢复。
- 不让 UE 直接携带/调用 LLM API Key。
- 不让模型输出 UE 资产路径、动画名、原始坐标或 C++ 函数名。
- 不将模型权重、训练缓存、`.env` 或 API Key 提交 Git。
- 不在队友 AI、Boss 状态和技能系统未完成前开始 RL 在线训练。
