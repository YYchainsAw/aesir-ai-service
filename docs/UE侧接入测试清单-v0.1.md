# UE 侧接入测试清单（契约 v0.1）

> 依据：`UE5_模型服务联调技术规范_v0.1.md` §8（UE 实施规格）、§10（P2–P4）、
> `UE联调快速验证-v0.1.md`（操作步骤）。本清单是 UE 侧接入 Python 服务时
> **需要逐项测试的验收条目**，按联调阶段分组，建议按编号顺序推进。
> 更新日期：2026-09-07

| 阶段 | 前置条件 | Python 配置 |
| --- | --- | --- |
| P2 文本联调 | 无战斗资产 | 默认（`AESIR_PARSER_BACKEND=rule`） |
| P3 战斗闭环 | 一名队友、一个 Boss、`state.stunned`、一个可触发技能 | 可切 `llm` 验证回退 |
| P4 语音 | Audio Capture 可用 | 先 `mock` 后 `faster_whisper` |

---

## 一、P2 文本联调（先于语音）

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

---

## 二、P3 首个战斗闭环

| # | 测试项 | 验证内容 | 结果 |
|---|---|---|---|
| 10 | 命令生命周期 | `TacticalOrderComponent` 登记 → 执行 → 完成/取消，`order_id` 全程关联 | ☐ |
| 11 | `state.stunned` 事件触发 | Boss 眩晕（Gameplay Tag / Delegate / Blackboard 驱动，**禁止用动画播放状态**）时 conditional_cast **恰好执行一次** | ☐ |
| 12 | 过期与优先级 | `expires: encounter_end` 战斗结束即失效；priority 高的命令覆盖低的（retreat 90 > conditional_cast 80） | ☐ |
| 13 | 触发时二次校验 | 触发时刻目标已死/蓝不够/CD 中/距离不足 → 不执行并给出失败原因 | ☐ |
| 14 | LLM 回退验证 | `AESIR_PARSER_BACKEND=llm` 时同一条指令可执行；LLM 不可用时 `source: rule_fallback` 仍可执行（规则命令不依赖 LLM） | ☐ |

**P3 验收**：文本「艾莉，等 Boss 眩晕时使用爆裂魔法」能被模型正确转换、UE
验证、队友执行；模型不可用时规则命令仍可执行。

---

## 三、P4 Push-to-Talk 与 ASR

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

## 联调注意

- 所有 ID 以 Python 契约为准（当前：`companion.alice` / `ability.alice.*`，
  显示名「艾莉」；旧名「艾琳/eirin」仅作为 wake 词兼容，UE 端不要使用）。
- `then.target` 的合法形态：目标选择器 ID 字符串，或 `{"ref":"when.subject"}`
  对象（见协议契约 §7.2，**不允许**裸字符串 `"when.subject"`）。
- UE 启动时记录支持的 `protocol_version` 与 `catalog_revision`，便于版本对账。
