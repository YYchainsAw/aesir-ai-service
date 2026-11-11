# UE 服务适配说明：文本 NPC、语音与 Boss RL

本文把游戏端工作限定为 HTTP 适配。UE 不需要把 NPC 记忆、关系、LLM、ASR 或 Boss 策略逻辑搬进游戏本体；UE 只负责采集状态、发送请求、校验响应、执行合法动作并回传事实。

可复制的请求模板见[ue-scoped.http](../examples/ue-scoped.http)。这些 UUID 和快照仅为占位，必须由当前 context/bind 和 UE 实际快照替换。实际 Bearer token 放在 HTTP 客户端的私有环境，不填写回仓库示例。

离线生成交接包（不访问模型、数据库或运行中的服务）：

```powershell
.\.venv\Scripts\python.exe -m scripts.export_ue_handoff
```

产物为 `data/runtime/ue-handoff/ue-service-handoff.zip`，包含本说明、请求样例、OpenAPI、相关契约、发布模板与文件哈希清单；不包含 `.env`、模型、音频、真实记忆或运行日志。它是源码交接材料，不是运行验收证据。

## 1. 服务职责边界

| 能力 | 服务端负责 | UE 负责 |
| --- | --- | --- |
| 文本 NPC | LLM/规则回复、记忆、关系、表现 ID、作用域隔离 | 输入框、字幕、表情/动作播放 |
| 语音 NPC | 音频接收、ASR、转写、同一角色对话链路 | 录音、上传、转写展示、失败后切文本 |
| NPC 指令 | 高层 directive、有效期、原因码、回执账本 | 能力/目标/距离/资源校验和实际执行 |
| Boss RL | 本地策略服务或随包模型的决策协议 | 观测、请求、动作合法性、BT fallback、结算 |

服务端返回 `200`、`202` 或 `accepted` 都不表示 UE 已执行技能。只有 UE 完成实际启动、命中或结算后提交回执，才能记为执行事实。

## 2. 服务端启动

### 开发联调

```powershell
$env:AESIR_SCOPE_IDENTITY_BACKEND = "development"
$env:AESIR_SCOPE_STORAGE_BACKEND = "json"
$env:AESIR_COORDINATION_BACKEND = "memory"
$env:AESIR_SCOPE_DEV_PLAYER_ID = "<player-uuid>"
$env:AESIR_SCOPE_DEV_SAVE_IDS = '["<save-uuid>"]'
$env:AESIR_SCOPE_LEGACY_ENABLED = "false"
.venv\Scripts\python.exe scripts\run_server.py
```

### staging/生产配置门禁

```powershell
.venv\Scripts\python.exe scripts\release_preflight.py --mode staging --json
.venv\Scripts\python.exe scripts\release_preflight.py --mode production --json
```

生产必须使用 Bearer、SQL、Redis、可用数据库连接和非 mock ASR。HTTPS 反向代理、证书、systemd、备份恢复和容量仍需部署环境验收。

## 3. 每次启动和换局的调用顺序

1. `GET /v1/scoped/context?save_id=<uuid>&companion_id=<id>`。
2. 如果返回 `run_id=null`，调用 `POST /v1/scoped/runs/bind` 创建本次游玩 run。
3. 进入战斗时调用 `POST /v1/scoped/encounters/control`，`op=begin`；结束时调用 `op=end`。
4. 保存 `service_instance_id`、`run_id`、`run_binding_id`、`memory_epoch`、`control_revision` 和 `encounter_revision`。
5. 服务重启、读档或收到 `SERVER_INSTANCE_CHANGED` 后重新获取 context，并显式 bind；不要重放旧请求或旧 directive。

普通业务请求必须带：

```text
protocol_version
request_id
save_id
service_instance_id
companion_id
run_id
run_binding_id
memory_epoch
timing
```

正式环境所有请求都带 `Authorization: Bearer <player-token>`。`player_id` 由服务端从凭据解析，UE 不应把它作为可伪造请求字段发送。

`request_id` 是逻辑请求 ID。网络重试必须复用原 ID 和原请求语义；修改文本、快照或作用域时必须生成新 ID。

## 4. 文本 NPC

调用 `POST /v1/scoped/companion/chat`，请求体使用 v0.4 schema。响应包含 `reply_text`、`emotion_id`、`gesture_id`、`facial_expression_id`、`source`、关系字段和作用域回显。

UE 必须：

- 校验响应 `request_id`、`scope`、`run_binding_id`、`memory_epoch`；
- 只使用当前仍有效的响应；
- `fallback` 只作为降级回复展示，不能当成技能执行成功；
- 换局时作废旧回调。

### v0.5 异步文本

请求体将 `protocol_version` 改为 `0.5`，POST 返回 `202` 和 `state=queued/running`，不包含业务回复。随后轮询：

同 ID 重试时，已完成请求可能直接返回 `200` 的业务结果；UE 必须处理 `200` 和 `202` 两种成功分支。v0.5 只是提交方式，轮询信封与业务 result 当前仍使用 v0.4 形状，不能把所有响应都强制要求为 `protocol_version=0.5`。

```text
GET /v1/scoped/requests/{request_id}
  ?save_id=...
  &companion_id=...
  &run_id=...
  &run_binding_id=...
  &service_instance_id=...
  &memory_epoch=...
  &operation=chat
```

- `completed`：从 `result` 读取与 v0.4 同形状的回复；
- `expired/failed/cancelled`：显示失败或文本重试入口；
- `unknown`：只提示状态未知，不能自动换 ID 重做；
- 轮询应在服务端终态保留期内完成，建议 100~200ms 起步并退避到 1s。

## 5. 语音 NPC

服务端入口：`POST /v1/scoped/companion/chat/voice`。

使用 `multipart/form-data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `audio` | file | 16 kHz、单声道、16-bit PCM WAV；默认最多 2 MiB、30 秒 |
| `protocol_version` | string | 当前为 `0.4` |
| `request_id` | UUID | 可省略；省略由服务端生成 |
| `save_id`、`service_instance_id`、`companion_id` | string | 当前作用域 |
| `run_id`、`run_binding_id`、`memory_epoch` | string | 当前 run 绑定 |
| `session_id`、`encounter_id` | string | 可选 |
| `game_state` | string | `exploration` 或 `conversation` |
| `timing` | JSON string | 与文本请求相同的 TimingInput |
| `world_context_json` | JSON string | 可选世界快照 |

成功响应是 v0.4 scoped chat 响应，并增加 `transcribed_text`。错误处理：

| HTTP | `detail.code` | UE 处理 |
| --- | --- | --- |
| 422 | `ASR_EMPTY` | 提示“未听清”，允许改用文本输入；不猜测指令 |
| 502 | `ASR_UNAVAILABLE` | 保留本地游戏流程，允许改用文本 |
| 409 | 作用域/时效/绑定错误 | 重新获取 context；不要重放旧音频 |
| 413/422 | 音频格式或大小问题 | 本地提示并重新录音 |

2026-11-11 本轮答辩确认允许自部署开源 ASR：优先采用 faster-whisper，通过服务端 HTTP 向 UE 提供真实转写，无需第三方语音 API Key。配置和验证见[自部署语音识别](asr-self-hosted.md)。服务端另保留 mock 与豆包商业接口适配；模型部署、音频范围和保留期需记录，mock 不能代替真实模型验收。

## 6. Directive 与执行回执

收到 `action=directive` 时，UE 在执行前检查：

1. `directive_id`、`agent_id`、`domain` 是否匹配当前角色和场景；
2. `expires` 是否仍有效；
3. `ability_id`、目标、距离、资源、冷却、动作锁和当前状态是否合法；
4. 当前 UE 能力目录是否声明该动作。

执行后向 `POST /v1/scoped/tactical/executions` 回报原 directive：

- `accepted`：UE 已接收；
- `executed`：UE 已实际执行完成；
- `rejected`：本地能力或状态拒绝；
- `expired`：到达 UE 时已过期；
- `cancelled`：被新请求或换局取消。

回执必须使用原 `directive_id` 和原 `request_id`。服务端回执已记录不代表 UE 世界状态已经改变。

线上字段分为两层，不能把它们写成同一个 ID：

| 字段 | 值与生命周期 |
| --- | --- |
| 外层 `request_id` | 本次回执提交的新逻辑 ID；网络重试复用它，accepted 与 executed 两次提交使用不同 ID |
| `receipt.request_id` | 产生原 directive 的 agent-step/world-event 请求 ID |
| `receipt.order_id` | 原 `directive.directive_id` |
| `receipt.agent_id` | 当前 companion_id |
| `receipt.sequence` | 同一指令的递增反馈序号，例如 accepted=0、executed=1；同一条回执重试不递增 |

原提交 ID 重放会回放原响应，因此响应中 `stored=1` 不代表又写了一条；使用新外层 ID 重报同一回执时，去重响应可为 `stored=0`。只读 directive 状态查询可核对账本，但不能拿查询结果重新执行动作。

最小 UE 动作先使用已有控制器处理的 exploration / player_command / wait，再接 follow。wait 无需 ability_id，不能虚构技能来满足字段；有能力动作时才核对 payload.ability_id 与 UE 实际能力目录。

## 7. 错误、断网和重启

- 401：暂停云端写入，重新获取凭据；不要退回匿名作用域。
- 403：停止当前存档请求，提示没有权限。
- 409：刷新 context/binding/epoch 后由玩家或游戏逻辑决定是否重新发起。
- 429：按 `Retry-After` 或本地退避处理，不重复创建逻辑请求。
- 503：若为 `REQUEST_OUTCOME_UNKNOWN`，等待人工或状态查询，不自动重做副作用。
- 服务不可达：本地基础 AI、战斗结算、菜单和退出必须继续；云端对话和新 directive 显示为不可用。

## 8. 验收边界

服务端可单独验收：schema、认证、作用域隔离、记忆/关系、LLM/ASR错误、v0.5轮询、回执去重、SQL/Redis、备份恢复和配置门禁。

UE 仍需适配并提供证据：实际录音上传、文本/语音 UI、directive 执行、技能命中/完成、Boss 观测与 fallback、断网恢复和真实 Windows 包运行。服务端测试不能替代这些游戏内证据。

## 9. UE 代码实施顺序

当前 `CompanionChatSubsystem.cpp` 仍发送 legacy v0.3；以下是待实施的接口分工，不表示 UE 已完成修改。

1. **会话上下文**：保存服务实例、save、run、binding、epoch、revision。进入新局或重连时由 context/bind 更新；不要用响应中旧值反向覆盖当前上下文。
2. **请求记录**：每个逻辑请求保存 ID、operation、原始语义、快照和首次发送单调时间。重试只增加 age，不增加原预算、不刷新原快照。
3. **异步分发**：POST 200 直接进入结果校验；202 创建轮询。chat 与 agent-step 的查询 operation 不同，session/encounter 要保持原值。HTTP 线程只交回结果，游戏线程更新 UI/角色。
4. **旧代失效**：换局、读档、切角色和服务重启使本地回调代次失效并停止轮询。取消请求使用新控制 ID；即便服务端取消返回 false，也不能让旧回调作用于新局。
5. **动作与回执**：只执行当前仍有效且本地可执行的 directive；本地已处理 directive_id 不能再次触发动作。按实际结果报告，不因模型回复或服务 HTTP 成功报告 executed。
6. **录音界面**：按键录音导出完整 PCM WAV，上传时保存本地输入状态；等待期间游戏继续。失败显示未听清、重录或文本入口，不能自动上传上一局的录音。

UE 待填的运行证据分开记录：文本首次回复、wait 实际生效、follow 恢复、重复响应不重复动作、换局旧响应丢弃、录音上传、ASR 故障切文本、断网仍能结算。最终代码提交、地图/资产快照、录屏及日志与这些项目一一关联。
