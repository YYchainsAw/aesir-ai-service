# Aesir AI Service

本仓库包含两个边界明确的子系统：供 Unreal 调用的**指令服务**，以及独立运行的 **Boss 强化学习实验**。指令服务把玩家的文本或语音战术指令转换为 UE 可校验的 JSON；Boss RL 负责训练和评估高层战术策略，不参与指令服务启动。

> **定位升级（2026-09-13 起）**：项目要求已从「语音转 JSON 战术命令」升级为「**NPC 人格与行为代理**」——在保留战斗指挥的前提下新增持久化记忆、关系状态、非战斗自主行为与只读查证工具。需求规格、章程与任务分解见 [`docs/planning/aesir-agent-sdd-v1.0.md`](docs/planning/aesir-agent-sdd-v1.0.md)（当前最高规划基线）；本 README 描述的 v0.1/v0.2 能力均已实现且保持兼容。

解析后端（规则 / LLM）与语音转写后端（mock / faster-whisper）均可插拔，输出协议保持不变。服务在本地运行，无外部依赖，UE 客户端通过 HTTP 直接调用。

## 设计理念

直接让 LLM 生成 UE 命令存在不可控风险（幻觉技能、非法参数、越权指令），因此采用「**受限协议 + 可替换解析器**」：

- **协议层**：`TacticalOrder` 每个字段限定在严格白名单内；UE C++ 侧做 1:1 结构映射并二次校验。
- **解析层**：规则 / LLM 解析器可替换，语音识别结果复用同一解析层。无论输入来源，输出协议不变。

把风险收敛在解析层，UE 通信协议与校验逻辑不因接入 LLM 或语音而改变。

## 技术栈

| 组件 | 选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI 0.141 | 轻量、自带 OpenAPI 文档 |
| 数据校验 | Pydantic 2.13 | `Literal` / 判别联合实现协议白名单 |
| ASGI 服务器 | Uvicorn 0.52 | 本地开发/运行 |
| 测试 | pytest 9.1 + httpx | 基于 `TestClient` 的接口测试 |
| 运行时 | Python 3.12 | — |
| 语音转写 | faster-whisper / mock | 可插拔 ASR 后端 |

## 目录结构

```
aesir-ai-service/
├── app/                           # 指令服务（生产运行时，不依赖 rl）
│   ├── main.py                    # FastAPI 应用入口
│   ├── config.py                  # pydantic-settings 环境变量解析
│   ├── api/
│   │   ├── health.py              # /health
│   │   ├── routes.py              # 路由聚合器（include 全部子 router）
│   │   └── v1/
│   │       ├── commands.py        # /v1/commands/parse（遗留 /parse-command）
│   │       ├── voice.py           # /v1/voice/command（音频→ASR→解析）
│   │       ├── speech.py          # /v1/speech/transcribe（独立转写）
│   │       ├── tactical.py        # /v1/tactical/resolve + executions
│   │       ├── combat.py          # /v1/combat/events
│   │       └── companion.py       # /v1/companion/chat
│   ├── schemas/                   # 协议 schema：ids / tactical_order / combat_context / directives（单一指令体系）…
│   └── services/
│       ├── parsers/               # rule / llm / command_parser（解析门面+回退）
│       ├── transcribers/          # base / mock / faster_whisper / factory
│       ├── tactical/              # resolver / event_policy / receipt_store / acknowledgement
│       ├── companion/             # 对话服务 + 人设仓库
│       ├── llm/                   # client + factory（共享 LLM Client）
│       ├── memory/                # 记忆体系（US1：三级记忆/淘汰/检索/降级）
│       ├── relationship/          # 关系体系（US2：数值/阶段/防刷/阶段化调制）
│       ├── agency/                # 自主行为（US3：场景判定/行为目录/仲裁/节流）
│       └── skills/                # 能力注册与只读查证工具（SDD 骨架，US6）
├── rl/                            # Boss 强化学习研究（可选依赖）
│   └── boss/                      # Boss-as-agent + UE schema v4
├── scripts/
│   ├── command_service/           # ASR 评估与假 UE 联调
│   └── rl/
│       └── boss/                  # Boss 训练/评估入口
├── data/
│   ├── companions/                # 队友 YAML 人设（Alice）
│   ├── policy/                    # 战术/关系/活动域策略阈值（tactical/relationship/agency_policy.yaml）
│   ├── world/                     # 世界观知识库 lore.yaml（只读查证用）
│   ├── golden/                    # UE 联调用 golden 快照（A/B/C/D 四类战况）
│   ├── memory/                    # 运行期 NPC 记忆（gitignore 不入库）
│   └── runtime/                   # 指令回执等运行数据（gitignore 不入库）
├── tests/                         # 指令服务测试 + rl/boss
├── docs/                          # 项目文档（planning/protocols/guides/design/logs）
├── requirements*.txt              # 运行时 / ML / RL / 开发测试 依赖拆分
└── CHANGELOG.md                   # 里程碑记录
```

## 文档导航

| 请求 | 入口 |
| --- | --- |
| 项目总览 / 设计理念 | 本文档 |
| **UE × 模型服务协议契约 v0.1**（API + 类型定义） | [`docs/protocols/ue-protocol-contract-v0.1.md`](docs/protocols/ue-protocol-contract-v0.1.md) |
| **UE 侧接入指南 v0.1**（分步 + 验收清单） | [`docs/protocols/ue-integration-guide-v0.1.md`](docs/protocols/ue-integration-guide-v0.1.md) |
| 战斗事件 / 上下文感知战术协议 v0.2（正式版） | [`docs/protocols/combat-tactical-protocol-v0.2.md`](docs/protocols/combat-tactical-protocol-v0.2.md) |
| 启动 / 安装 / 接口示例 | [`docs/guides/getting-started.md`](docs/guides/getting-started.md) |
| LLM 联调 | [`docs/guides/llm-integration.md`](docs/guides/llm-integration.md) |
| 当前 Boss RL 代码与运行入口 | [`rl/README.md`](rl/README.md) |
| 总策划书 v0.1 | [`docs/planning/game-design-doc-v0.1.md`](docs/planning/game-design-doc-v0.1.md) |
| **需求规格说明书 SDD v1.0**（章程 / 用户故事 / 任务分解） | [`docs/planning/aesir-agent-sdd-v1.0.md`](docs/planning/aesir-agent-sdd-v1.0.md) |
| 全部文档索引 | [`docs/README.md`](docs/README.md) |

## 启动

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

或直接双击根目录的 `start.bat`（可带参数指定端口，如 `start.bat 8001`）；`start.bat chat` 可在终端直接与 NPC 对话（人设质量检查，见 `docs/guides/getting-started.md` §5.7）。

服务启动后访问：

- `http://127.0.0.1:8000/health`：健康检查（返回 `protocol_version: "0.1"`）
- `http://127.0.0.1:8000/docs`：交互式接口文档

## 当前接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/v1/commands/parse` | 契约 v0.1：文本 + 能力目录 `context` + `request_id` |
| `POST` | `/v1/voice/command` | 语音：multipart WAV(16kHz/mono/16bit) → ASR → 同一解析层 |
| `POST` | `/v1/speech/transcribe` | 独立转写：只做音频 → 文本（两步式调试 ASR） |
| `POST` | `/v1/tactical/resolve` | v0.2 预览：意图 + 战斗快照 → 上下文决策（规则策略） |
| `POST` | `/v1/tactical/command` | v0.2 组合端点：文本 + 战斗快照 → 上下文决策，一次调用 |
| `POST` | `/v1/tactical/executions` | v0.2 §7：UE 执行回执（202 受理，落 JSONL） |
| `POST` | `/v1/combat/events` | v0.2 §6：战斗事件 → 艾莉反应/建议/候选动作 |
| `POST` | `/v1/companion/chat` | 陪伴对话 |
| `POST` | `/v1/companion/chat/stream` | 陪伴对话流式变体（SSE：delta 增量 + meta 权威帧，契约附录 A） |
| `POST` | `/v1/agent/step` | v0.3 主入口：心跳/世界快照 → 禁打断判定 → 候选生成 → 仲裁 → 节流 → 自主行为指令（US3） |
| `POST` | `/v1/world/events` | v0.3 世界事件（含幂等回放） |
| `GET` | `/v1/console/state` · `/memory`，`POST /memory/reset` | v0.3 调试台（状态查询/记忆重置） |
| `POST` | `/parse-command` | 遗留别名：只传 `text`，服务端回填默认能力目录 |

支持的 5 条战术指令（`intent`）：

| 指令 | intent | 动作 `then.type` |
| --- | --- | --- |
| 艾莉，等 Boss 眩晕时使用爆裂魔法 | `conditional_cast` | `cast_ability` |
| 艾莉，保留爆裂魔法 | `hold_ability` | `hold_ability` |
| 艾莉，撤退并优先保命 | `retreat` | `retreat` |
| 艾莉，跟随我并保持距离 | `follow_keep_distance` | `follow` |
| 艾莉，优先普通攻击 | `prioritize_attack` | `set_priority` |

不识别的文本会明确返回 `recognized: false` 且 `order: null`，UE 端可安全忽略。

### 文本示例

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/commands/parse `
  -ContentType "application/json" `
  -Body '{"protocol_version":"0.1","request_id":"1fad2e69-4a2d-4308-ad4f-2f8abb338b89","text":"艾莉，撤退并优先保命","context":{"agents":[{"id":"companion.alice","ability_ids":["ability.alice.explosion","ability.alice.basic_attack"]}],"target_selectors":["encounter.primary_hostile","party.player"],"state_tags":["state.stunned","state.phase_two"]}}'
```

### 语音（真实 ASR）

`.env` 设 `AESIR_ASR_BACKEND=faster_whisper`（模型/设备等见 `.env.example`；首次需装 `requirements-ml.txt` 并配 `HF_ENDPOINT=https://hf-mirror.com` 下载模型）：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/voice/command `
  -Form @{ file = Get-Item cmd.wav; request_id = "1fad2e69-4a2d-4308-ad4f-2f8abb338b89" }
```

默认 `AESIR_ASR_BACKEND=mock` 返回 `AESIR_ASR_MOCK_TEXT` 固定文本，用于无模型环境自测。

~~真人声调优~~（已取消：无真人录音样本；`scripts/command_service/asr_eval.py` 评测脚手架保留备用）。

## 核心设计

`TacticalOrder` 由 `intent` 判别的联合类型；`when` / `then` / `expires` 又各自按 `type` 判别。完整类型定义、Golden JSON 与能力目录白名单见[协议契约](docs/protocols/ue-protocol-contract-v0.1.md)。

解析流程：

```
玩家文本 / ASR 文本 → 后端选型（rule / llm）
        → 规则解析器 _normalize（去空格/标点/大小写/全半角）
        → 匹配 agent → 按「更具体优先」匹配 5 个意图
        → 生成 TacticalOrder / recognized=false
        → LLM 失败时回退到规则（rule_fallback → source 标记）
```

解析逻辑隔离在 `app/services/parsers/`，输出 `ParseCommandResponse` 由 schema 固定。`source` 字段标注最终实际来源（`rule` / `llm` / `rule_fallback`），供 UE 端日志与降级观测。

## Boss RL（当前答辩主线）

`rl/boss/` 是当前唯一的强化学习实现，动作和观察契约与 UE 对齐。它不会被 `app.main:app` 导入：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-rl.txt      # gymnasium/sb3/torch(CPU)
.\.venv\Scripts\python scripts\rl\boss\eval.py --episodes 20      # BT/规则基线
.\.venv\Scripts\python scripts\rl\boss\train.py --timesteps 20000 # PPO 冒烟训练
```

正式训练会额外生成 TensorBoard 日志、周期 Checkpoint、周期评估结果和最佳模型；
最终 manifest 同时记录总体指标及每种玩家画像的胜率、伤害与动作分布。

冻结后的 Boss 策略由独立服务提供推理，不与玩家指令服务混合：

```powershell
.\.venv\Scripts\python scripts\rl\boss\serve.py  # http://127.0.0.1:8012
```

目录边界与旧实验说明见 [`rl/README.md`](rl/README.md)。RL 尚未接入 HTTP 推理路径；后续会通过独立 Boss policy adapter 接入，而不是混进玩家指令解析器。

## 测试

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

覆盖契约 v0.1、语音链路、LLM 回退、v0.2 tactical resolve/executions/combat events（含幂等）、策略 YAML、当前 Boss RL 和归档队友实验。测试数量以当前 `pytest` 输出为准；真机 ASR 与完整 PPO 训练需要各自的可选依赖和显式冒烟开关。

### UE 联调前预演（不写一行 C++ 也能看到全链路）

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload          # 终端 1：起服务
.\.venv\Scripts\python -m scripts.command_service.mock_ue_flow    # 终端 2：假 UE 全链路
```

脚本按策划书 §9 的 UE 伪流程依次调用 chat → parse → resolve（同一句治疗指令 × A/B/C/D 四类战况，见 `data/golden/`）→ combat/events（含同一 `event_id` 重试的幂等回放）→ executions 回执，全部打印响应 JSON，可直接作为 UE 侧开发与答辩演示素材。

## 路线图

- [x] 规则解析器：支持首批 5 条战术指令（契约 v0.1 判别联合）
- [x] LLM 指令解析：`llm` 后端接入，失败回退规则（`source: rule_fallback`）
- [x] 语音识别 mock 全链路：`/v1/voice/command` 音频 → ASR(mock) → 同一解析层
- [x] 语音识别接入 faster-whisper：`AESIR_ASR_BACKEND=faster_whisper` 走真实本机 Whisper
- [x] 专用 `/v1/speech/transcribe` 端点，与组合端点并存
- [x] v0.2 第一阶段：CombatContext/TacticalIntent/TacticalDecision schema + `/v1/tactical/resolve` 规则策略 v1 + 85 例回归评测
- [x] `/v1/combat/events` 战斗事件端点 + `/v1/tactical/executions` 执行回执
- [x] v0.2 协议定稿：`event_id` 服务端幂等（重试回放 + `duplicate` 标记）、快照时间 ISO-8601 校验、策略阈值/优先级迁 `data/policy/tactical_policy.yaml`（2026-09-09）
- [x] UE 联调支持资产：`data/golden/` 四类战况 golden 快照 + `scripts/command_service/mock_ue_flow.py` 全链路演示（2026-09-09）
- [x] 组合端点 `/v1/tactical/command`：文本 + 快照 → 上下文决策一次到位（规则意图解析 v1，后续可接 LLM）
- [x] Boss RL schema v4、训练模拟器、奖励和 Behavior Tree 规则基线
- [ ] 训练 Boss PPO，接入 UE 的共享 GAS Boss action executor，并完成 BT 对照实验

## 调试

PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，**请改用 `Invoke-RestMethod` 或 `curl.exe`**。浏览器打开 `http://127.0.0.1:8000/docs` 可交互式调用接口。
