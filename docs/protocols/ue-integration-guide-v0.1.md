# UE 侧接入指南 v0.1

> 本指南让 UE 侧用**最短路径**把契约 v0.1 文本/语音链路跑通，并对照逐项验收。
> 完整协议见 [ue-protocol-contract-v0.1.md](ue-protocol-contract-v0.1.md)；本文只做
> 分步操作清单 + 验收测试清单。
> 更新日期：2026-09-07

| 阶段 | 前置条件 | Python 配置 |
| --- | --- | --- |
| P2 文本联调 | 无战斗资产 | 默认（`AESIR_PARSER_BACKEND=rule`） |
| P3 战斗闭环 | 一名队友、一个 Boss、`state.stunned`、一个可触发技能 | 可切 `llm` 验证回退 |
| P4 语音 | Audio Capture 可用 | 先 `mock` 后 `faster_whisper` |

---

## 0. 前置

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

- mock 阶段**不需要**装 faster-whisper，不需要 .env。
- 全程只依赖本机，无外网调用。

---

## 1. 第一步：纯文本（先不碰音频）

`POST /v1/commands/parse`，验证 JSON 契约、`request_id` 回显、5 条指令的
`TacticalOrder` 结构。请求体模板直接抄 [getting-started.md](../guides/getting-started.md) §5.2。

验收：5 条指令各返回正确 `intent`；未识别文本返回 `recognized:false` +
`order:null`（UE 安全忽略路径）。

---

## 2. 第二步：mock 语音（打通上传链路）

`.env` 或环境变量（也可不设，mock 为默认）：

```powershell
$env:AESIR_ASR_MOCK_TEXT = "艾莉，撤退并优先保命"
```

UE 上传任意 WAV（16kHz/单声道/16bit，内容不重要）到：

- 组合端点：`POST /v1/voice/command`（multipart `file` + 可选 `request_id`）
  → 一次返回 `ParseCommandResponse`。
- 两步式：`POST /v1/speech/transcribe`（multipart `audio` + 可选 `request_id`）
  → `{request_id, text, language}`，再拿 `text` 调 `/v1/commands/parse`。

验收：multipart 编码正确、`request_id` 回显、错误分支（422/502）有 HUD 提示。
建议 UE 侧 Audio Capture + WAV 编码在本步一并调通（内容随意，格式必须对）。

---

## 3. 第三步：切换真实 ASR

```powershell
.\.venv\Scripts\python -m pip install -r requirements-ml.txt
$env:HF_ENDPOINT = "https://hf-mirror.com"      # 首次下载模型
$env:AESIR_ASR_BACKEND = "faster_whisper"
```

用真人录音（「艾莉，撤退并优先保命」等）替换 mock 文本验证。真人声调优已取消，
`scripts/command_service/asr_eval.py` 评测脚手架保留备用。

验收：一句指令端到端 < 3s（`small` 模型本机约 0.5s）；识别错句时确认走
`recognized:false` 而非报错。

---

## 4. 第四步（可选）：v0.2 战术决策端点

`POST /v1/tactical/resolve` 已实现（规则策略 v1）：UE 传语义意图 + 战斗快照，
返回带 `reason_codes` 的上下文决策。可先用手写快照 JSON 验证（示例见
[getting-started.md](../guides/getting-started.md) §5.4），UE 侧真实快照采集到位后再联调。

### 4.1 执行回执（v0.2 §7，服务端已实现）

UE 对每个 `order_id` 回传执行结果，服务端落 `data/rl/executions/` 按天 JSONL：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/tactical/executions `
  -ContentType "application/json" `
  -Body '{"receipt":{"order_id":"527b4c0d-0fe1-4e4c-9057-3c991ba1616c","result":"executed","encounter_id":"encounter.20260907.001"}}'
# result ∈ accepted/executed/rejected/expired/cancelled；预期 202 {"stored":true,...}
```

回执仅用于观察与后续评测数据集（**不自动用于训练**，v0.2 §7）；批量上传留待 v0.3。

---

## 5. 逐项验收测试清单

按阶段（P2 文本 → P3 战斗闭环 → P4 语音）推进，共 21 条。

### 5.1 P2 文本联调（先于语音）

| # | 测试项 | 验证内容 | 结果 |
|---|---|---|---|
| 1 | 服务可达性 | `GET /health` 返回 `ok` + `protocol_version:"0.1"`；服务关闭时 UE 有降级提示、不崩溃 | ☐ |
| 2 | `FTacticalOrder` 反序列化 | 契约 v0.1 golden 示例的 5 种 intent JSON 逐个解析成功，字段与 `USTRUCT` 1:1 映射（`when`/`then`/`expires` 判别联合） | ☐ |
| 3 | `request_id` 生成与回显 | UE 发 UUID v4，响应原样返回；跨端日志可关联 | ☐ |
| 4 | 非法 JSON 安全拒绝 | 截断 JSON、错误类型字段、多余字段不崩溃，记录原因（HTTP 422 也走此路径） | ☐ |
| 5 | `recognized:false` 路径 | 未识别文本返回 `order:null`，UE 安全忽略并显示 `message` | ☐ |
| 6 | UE 最终校验七步（按序） | ①`protocol_version` 支持 → ②`agent_id` 存在/可控/未死亡 → ③`intent`/`when.type`/`then.type` 已实现 → ④`ability_id` 在能力目录 → ⑤`subject`/`target` 可解析 → ⑥未过期/未被高优先级覆盖 → ⑦触发时再验目标存活、蓝量、CD、距离 | ☐ |
| 7 | 非法 ID 本地拦截 | Python 认可但 UE 本地不认识的 ID（两端目录不同步场景）被拒绝执行 | ☐ |
| 8 | 超时与取消 | 3s 超时本地取消，不阻塞游戏主线程，队友维持原 AI | ☐ |
| 9 | HUD 任务显示 | `conditional_cast` JSON 在日志/HUD 显示为可读任务（P2 验收标准） | ☐ |

**P2 验收**：Python 返回的 `conditional_cast` JSON 能在 UE 日志/HUD 中显示为
可读任务；非法 JSON 被安全拒绝。

### 5.2 P3 首个战斗闭环

| # | 测试项 | 验证内容 | 结果 |
|---|---|---|---|
| 10 | 命令生命周期 | `TacticalOrderComponent` 登记 → 执行 → 完成/取消，`order_id` 全程关联 | ☐ |
| 11 | `state.stunned` 事件触发 | Boss 眩晕（Gameplay Tag / Delegate / Blackboard 驱动，**禁止用动画播放状态**）时 conditional_cast **恰好执行一次** | ☐ |
| 12 | 过期与优先级 | `expires: encounter_end` 战斗结束即失效；priority 高的命令覆盖低的（retreat 90 > conditional_cast 80） | ☐ |
| 13 | 触发时二次校验 | 触发时刻目标已死/蓝不够/CD 中/距离不足 → 不执行并给出失败原因 | ☐ |
| 14 | LLM 回退验证 | `AESIR_PARSER_BACKEND=llm` 时同一条指令可执行；LLM 不可用时 `source: rule_fallback` 仍可执行（规则命令不依赖 LLM） | ☐ |

**P3 验收**：文本「艾莉，等 Boss 眩晕时使用爆裂魔法」能被模型正确转换、UE
验证、队友执行；模型不可用时规则命令仍可执行。

### 5.3 P4 Push-to-Talk 与 ASR

| # | 测试项 | 验证内容 | 结果 |
|---|---|---|---|
| 15 | Audio Capture → WAV 编码 | 采集输出为 **16kHz / 单声道 / 16bit PCM WAV**（格式错则 ASR 全链路失效；建议先拿任意内容 WAV 对 mock 后端打格式） | ☐ |
| 16 | multipart 上传编码 | 组合端点 `file` 字段 / transcribe 端点 `audio` 字段编码正确，服务端能收到并解析 | ☐ |
| 17 | 独立转写两步式 | `POST /v1/speech/transcribe` → 拿 `text` → `POST /v1/commands/parse`；`{request_id, text, language}` 响应解析正确 | ☐ |
| 18 | HUD 链路四态 | 录音中 → 转写文本 → 解析中 → 命令接受/拒绝（P4 验收标准） | ☐ |
| 19 | 全链路不阻塞主线程 | 按住说话到命令入队全程异步；HTTP/ASR 在 3s 预算内 | ☐ |
| 20 | ASR 错误分支 | 空转写（`text:""`）→ 显示未识别；转写 502 → 「语音服务不可用」本地降级 | ☐ |
| 21 | mock → 真实 ASR 切换 | 同一 UE 代码不动，仅切 `AESIR_ASR_BACKEND`（`mock`/`faster_whisper`）行为一致 | ☐ |

**P4 验收**：按住说话到命令入队全链路不阻塞游戏主线程；失败能给出可理解反馈。

---

## 6. 错误处理对照（UE 必须实现）

| 情况 | 服务返回 | UE 行为 |
| --- | --- | --- |
| 未识别（空转写/未知文本） | 200, `recognized:false` | 显示 message，不执行 |
| request_id 非法 | 422 | 客户端 bug，修 UE |
| ASR/LLM 故障 | 502/503 | 本地降级提示 |
| 超时（建议 3s） | — | UE 本地取消，维持原 AI |

---

## 联调注意

- 所有 ID 以 Python 契约为准（当前：`companion.alice` / `ability.alice.*`，
  显示名「艾莉」；旧名「艾琳/eirin」仅作为 wake 词兼容，UE 端不要使用）。
- `then.target` 的合法形态：目标选择器 ID 字符串，或 `{"ref":"when.subject"}`
  对象（见契约 §10.2，**不允许**裸字符串 `"when.subject"`）。
- UE 启动时记录支持的 `protocol_version` 与 `catalog_revision`，便于版本对账。

---

## 附：v0.2 端点测试清单（待补）

`/v1/tactical/resolve`（规则策略 v1）已实现：CombatContext 上传、意图传递、
决策四态（actionable / advisory / not_actionable / clarification_needed）、
reason_codes 解析、companion_reply 展示等测试项将在 UE 快照采集就绪后补充。

`/v1/tactical/executions`（执行回执）服务端已实现（信封 `{receipt:{...}}`，
单条，202 受理后按天落 JSONL；`result` 枚举与 v0.2 §7 一致）：UE 侧测试项——
resolve 返回的 `order_id` 回传后收到 202、非法 `result` 返回 422、
批量上传留待 v0.3 后补充。

`/v1/combat/events`（战斗事件）服务端已实现（六类 `event_type`：玩家血线危急、
Boss 快眩晕、Boss 眩晕、Boss 狂暴、艾莉蓝量低、Boss 被击败）：UE 侧测试项——
上传事件 → 拿 `companion_action`/`companion_reply` 展示，CD 中/蓝量不足时
`companion_action` 为 `null` 而非虚构动作；同一 `encounter_id + event_id` 重试
会收到 `duplicate: true` 的幂等回放（同一 `order_id`，UE 去重显示即可）。

## 附：联调资产（不写 C++ 也能先跑通）

- **golden 快照**：`data/golden/` 下 A（濒危贴脸）/B（稳态消耗）/C（眩晕窗口）/D（资源枯竭）四份
  `CombatContext` JSON，与回归评测集同源，可直接作为请求体 fixture。
- **假 UE 全链路脚本**：`.\.venv\Scripts\python -m scripts.command_service.mock_ue_flow`——按总策划书 §9
  伪流程跑 chat → parse → resolve（同一句治疗指令 × 四类战况）→ combat/events（含幂等
  重试）→ executions，打印每步响应 JSON；写 C++ 前先跑一遍即可看到完整闭环的期望输出。
