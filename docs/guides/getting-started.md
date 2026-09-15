# Aesir AI Service — 启动说明

本文档说明如何在本地启动、运行与测试 Aesir AI Service。

> 本文描述的是**当前已实现**的 v0.1/v0.2 能力（语音/文本战术指挥、事件反应、陪伴对话）。项目定位已于 2026-09-13 升级为「NPC 人格与行为代理」（持久化记忆、关系状态、非战斗自主行为等），规划与任务分解见 [SDD v1.0](../planning/aesir-agent-sdd-v1.0.md)；新端点落地后将补充到本文。

## 1. 环境要求

- **Python 3.12**（本项目使用 3.12.7 开发）
- **Windows**（当前开发环境；Linux/macOS 仅需替换虚拟环境路径）
- 可选：`pip` 可访问 PyPI 以安装依赖

## 2. 安装依赖

### 2.1 创建虚拟环境（首次）

在项目根目录执行：

```powershell
python -m venv .venv
```

### 2.2 激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
```

> 若 PowerShell 提示执行策略限制，可先执行：
> ```powershell
> Set-ExecutionPolicy -Scope Process RemoteSigned
> ```

### 2.3 安装依赖

按用途分三类安装（也可用 `-r` 一条命令带上主依赖）：

```powershell
# 先做一次可编辑安装（让 app/rl/scripts 成为可导入包，脚本即可用 python -m 运行）
.\.venv\Scripts\python -m pip install -e .
# 仅运行服务
.\.venv\Scripts\python -m pip install -r requirements.txt
# 或开发/测试（含运行依赖 + pytest + httpx）
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
# 真实语音识别（faster-whisper，按需）：在服务之外单独安装；mock 后端不需要
.\.venv\Scripts\python -m pip install -r requirements-ml.txt
```

运行时依赖清单（`requirements.txt`）：

```
fastapi==0.141.1
uvicorn[standard]==0.52.4
pydantic==2.13.5
httpx[socks]==0.28.1
python-dotenv==1.2.3
PyYAML==6.0.3
python-multipart==0.0.32      # /v1/voice/command 的 File/Form 上传必需
pydantic-settings==2.15.0     # 运行时配置（AESIR_* 环境变量 → Settings）
```

## 3. 启动服务

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

或直接双击项目根目录的 `start.bat`（可带参数指定端口，如 `start.bat 8001`）。

**终端对话模式（人设质量检查）**：`start.bat chat [端口]` —— 服务已在运行则直接复用，否则后台最小化启动；随后进入终端 REPL 直接与艾莉对话（详见 5.7 节）。等价命令：`.venv\Scripts\python -m scripts.chat_console`。

- `--reload`：代码改动后自动重启，仅开发环境使用。
- 默认监听 `127.0.0.1:8000`。

启动成功后访问：

| 地址 | 说明 |
| --- | --- |
| `http://127.0.0.1:8000/health` | 健康检查 |
| `http://127.0.0.1:8000/docs` | 交互式接口文档（Swagger UI） |

## 4. 运行测试

测试需要开发依赖，先装再跑：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

测试覆盖：健康检查、5 条已支持指令的解析、未知指令的安全拒绝、LLM 解析回退、语音端点（mock / 桩 / 错误链路）、v0.2 tactical resolve 与回归评测（20 意图 × 4 战况）、combat/events 幂等、策略 YAML 加载、US1 分级记忆（持久化/淘汰/降级）、v0.3 骨架端点、语料红线。测试数以 `pytest` 输出为准（2026-09-14：**286 通过 + 3 条冒烟默认跳过**，锚点见根目录 [CHANGELOG](../CHANGELOG.md)）；真机 ASR 冒烟需 `$env:AESIR_ASR_SMOKE = "1"`（并装好 `requirements-ml.txt`）。

另备 UE 联调前预演（无需写 C++ 即可看到全链路响应）：起服务后运行 `.\.venv\Scripts\python -m scripts.command_service.mock_ue_flow`，脚本按策划书 §9 伪流程跑 chat → parse → resolve（四类战况 golden 快照见 `data/golden/`）→ combat/events（含幂等重试）→ executions。

## 5. 接口验证示例

### 5.1 健康检查

```powershell
curl http://127.0.0.1:8000/health
```

返回：

```json
{"status": "ok", "service": "aesir-ai-service", "protocol_version": "0.1"}
```

### 5.2 解析战术指令（契约 v0.1）

推荐使用正式接口 `/v1/commands/parse`（携带能力目录与 request_id）：

```powershell
curl -X POST http://127.0.0.1:8000/v1/commands/parse `
  -H "Content-Type: application/json" `
  -d '{\"protocol_version\": \"0.1\", \"request_id\": \"1fad2e69-4a2d-4308-ad4f-2f8abb338b89\", \"text\": \"艾莉，等 Boss 眩晕时使用爆裂魔法\", \"context\": {\"catalog_revision\": \"dev-001\", \"locale\": \"zh-CN\", \"agents\": [{\"id\": \"companion.alice\", \"ability_ids\": [\"ability.alice.explosion\", \"ability.alice.basic_attack\"]}], \"target_selectors\": [\"encounter.primary_hostile\", \"party.player\"], \"state_tags\": [\"state.stunned\", \"state.phase_two\"]}}'
```

返回（节选）：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": true,
  "message": "好，等 Boss 眩晕时释放爆裂魔法。",
  "source": "rule",
  "order": {
    "intent": "conditional_cast",
    "order_id": "<uuid 生成>",
    "agent_id": "companion.alice",
    "priority": 80,
    "expires": { "type": "encounter_end" },
    "when": { "type": "state_entered", "subject": "encounter.primary_hostile", "tag": "state.stunned" },
    "then": { "type": "cast_ability", "ability_id": "ability.alice.explosion", "target": { "ref": "when.subject" } }
  }
}
```

遗留入口 `POST /parse-command` 只传 `text`，服务端自动回填默认能力目录与 request_id，用于旧客户端调试。

未知指令返回：

```json
{
  "protocol_version": "0.1",
  "recognized": false,
  "order": null,
  "message": "当前无法确认该技能或目标。"
}
```

### 5.3 语音指令（ASR 链路）

`/v1/voice/command` 接收 WAV / 16kHz / 单声道 / 16bit 的 multipart 上传，先经 ASR 转成文本再送入同一解析层。

**方式一：mock 后端（默认，无需模型）**——返回固定文本：

```powershell
$env:AESIR_ASR_BACKEND = "mock"
$env:AESIR_ASR_MOCK_TEXT = "艾莉，撤退并优先保命"

curl -X POST http://127.0.0.1:8000/v1/voice/command `
  -F "file=@cmd.wav" `
  -F "request_id=1fad2e69-4a2d-4308-ad4f-2f8abb338b89"
```

**方式二：真实 faster-whisper**——需先装 `requirements-ml.txt`；首次下载模型要配国内镜像：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"   # 首次下载模型需要；已缓存则可省
$env:AESIR_ASR_BACKEND = "faster_whisper"    # 模型/设备/量化/语言见 .env.example

curl -X POST http://127.0.0.1:8000/v1/voice/command -F "file=@cmd.wav"
```

返回同契约 v0.1：mock 方式下 `order.intent == "retreat"`；转写出空串则 `recognized: false`，转写抛错则 `502`。

### 5.3.1 独立转写（调试 ASR 单环节）

`POST /v1/speech/transcribe` 只做「音频 → 文本」，不接解析层，便于 UE 单独调试 ASR（两步式：先 transcribe 再 `parse`）：

```powershell
curl -X POST http://127.0.0.1:8000/v1/speech/transcribe -F "audio=@cmd.wav" -F "request_id=1fad2e69-4a2d-4308-ad4f-2f8abb338b89"
```

返回：

```json
{"request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89", "text": "艾莉，撤退并优先保命", "language": "zh"}
```

未识别出语音内容时 `text` 为空串（仍 HTTP 200）；转写抛错返回 `502`。

### 5.3.2 真人声调优评测（已取消，脚手架保留）

真人录音按「文件名即期望文本」放入 `data/asr_samples/`（如 `艾莉撤退并优先保命.wav`，16kHz/单声道/16bit），然后跑：

```powershell
.\.venv\Scripts\python -m scripts.command_service.asr_eval
.\.venv\Scripts\python -m scripts.command_service.asr_eval --model small --beam 5 --no-vad
```

脚本输出每条样本的转写结果、字错误率（CER）与耗时，以及整体平均；用于对比模型 / beam_size / VAD 组合选出最优配置。

### 5.4 v0.2 战术决策 `/v1/tactical/resolve`

语义意图 + 战斗快照 → 上下文战术决策（规则策略 v1；协议详见 `../protocols/combat-tactical-protocol-v0.2.md` §5）：

```powershell
curl -X POST http://127.0.0.1:8000/v1/tactical/resolve `
  -H "Content-Type: application/json" `
  -d '{\"protocol_version\": \"0.2\", \"request_id\": \"88d7e6b4-f4f2-4d39-8c96-a23d293882f6\", \"intent\": {\"intent_id\": \"support_heal_player\", \"target_id\": \"party.player\", \"timing\": \"immediate\"}, \"combat_context\": {\"encounter_id\": \"encounter.001\", \"snapshot_id\": \"11111111-1111-1111-1111-111111111111\", \"captured_at\": \"2026-09-07T12:00:00Z\", \"mode\": \"combat\", \"player\": {\"id\": \"party.player\", \"hp_percent\": 18, \"is_downed\": false, \"distance_to_boss_m\": 4.5}, \"companion\": {\"id\": \"companion.alice\", \"hp_percent\": 83, \"mp_percent\": 72, \"current_behavior\": \"ranged_attack\", \"ability_states\": {\"ability.alice.basic_attack\": \"ready\"}}, \"boss\": {\"id\": \"encounter.primary_hostile\", \"hp_percent\": 42, \"stun_percent\": 0, \"state_tags\": [], \"phase\": 1}}}'
```

返回（节选）：`decision.status`（actionable / not_actionable）、`decision.action`（候选动作 + priority + expires）、`reason_codes`（可解释决策依据）。同一意图在不同快照（玩家濒危 / 健康 / Boss 眩晕 / 艾莉缺蓝）下产出不同决策；能力不可用时返回 `not_actionable`，绝不虚构动作。目前为纯规则策略（`source` 固定 `rule`），无 LLM 调用。

组合端点 `POST /v1/tactical/command` 可省一次往返——把 `intent` 换成 `text` 即可（"艾莉，帮我回一下血"这类文本由服务端规则解析出意图再落地；不可识别时返回 `recognized:false` + 澄清台词）：

```powershell
curl -X POST http://127.0.0.1:8000/v1/tactical/command `
  -H "Content-Type: application/json" `
  -d '{\"protocol_version\": \"0.2\", \"request_id\": \"99d7e6b4-f4f2-4d39-8c96-a23d293882f6\", \"text\": \"艾莉，帮我回一下血\", \"combat_context\": {\"encounter_id\": \"encounter.001\", \"snapshot_id\": \"11111111-1111-1111-1111-111111111111\", \"captured_at\": \"2026-09-09T12:00:00Z\", \"mode\": \"combat\", \"player\": {\"id\": \"party.player\", \"hp_percent\": 18, \"is_downed\": false, \"distance_to_boss_m\": 4.5}, \"companion\": {\"id\": \"companion.alice\", \"hp_percent\": 83, \"mp_percent\": 72, \"current_behavior\": \"ranged_attack\", \"ability_states\": {\"ability.alice.basic_attack\": \"ready\"}}, \"boss\": {\"id\": \"encounter.primary_hostile\", \"hp_percent\": 42, \"stun_percent\": 0, \"state_tags\": [], \"phase\": 1}}}'
```

### 5.5 非战斗陪伴对话

`POST /v1/companion/chat`（仅 `exploration` / `conversation` 状态；后端由 `AESIR_COMPANION_BACKEND` 决定，默认 `mock`，LLM 故障时回退 YAML 分类候选回复）：

```powershell
curl -X POST http://127.0.0.1:8000/v1/companion/chat `
  -H "Content-Type: application/json" `
  -d '{\"text\": \"艾莉，今天心情怎么样？\", \"companion_id\": \"companion.alice\", \"game_state\": \"conversation\", \"session_id\": \"ue-session-42\"}'
```

- `session_id`（选填，v0.3 新增）：UE 生成并在同一轮对话中复用；传入时服务端维护最近 N 轮（`AESIR_DIALOGUE_HISTORY_TURNS`，默认 10）滚动记忆并注入 LLM，角色可接续上文；缺省时请求完全无状态。
- **长期记忆已接入（SDD US1）**：每轮对话玩家发言写入分级记忆（`data/memory/<companion_id>/`，重启保留）；LLM 生成时按预算（`AESIR_MEMORY_INJECTION_BUDGET`，默认 12 条）注入档案/摘要/短期记忆，角色可自然引用历史信息。记忆故障自动降级为无记忆继续对话（FR-011）。重置入口：`POST /v1/console/memory/reset`；持久化演示：`python -m scripts.demo_memory_persistence`。
- 未登记的 `companion_id` 返回 `404`。

### 5.6 v0.3 骨架端点（SDD Phase 2，主入口/世界事件/调试台）

三个新端点已通、但为骨架实现（空动作路径；记忆/关系/自主行为在 SDD US1~US3 落地后接入），请求/响应结构以 `data/golden/` 下的样例为准：

| 端点 | 状态 | 说明 |
| --- | --- | --- |
| `POST /v1/agent/step` | 骨架 | 心跳与指令统一处理：无 `text` 即心跳（限流 429，最小间隔 `AESIR_HEARTBEAT_MIN_INTERVAL_SECONDS` 默认 2s）；当前返回空动作 `action:"none"`。未登记角色 404 |
| `POST /v1/world/events` | 骨架 | 世界事件（战斗+生活类型白名单）：`companion_id + event_id` 幂等回放（`duplicate:true`）；反应暂回退角色默认表现 |
| `GET /v1/console/state` / `GET /v1/console/memory` / `POST /v1/console/memory/reset` | 骨架 | 调试台：注册表/状态查询、三级长期记忆视图、会话+长期记忆重置 |

```powershell
curl -X POST http://127.0.0.1:8000/v1/agent/step -H "Content-Type: application/json" -d '{\"protocol_version\": \"0.3\", \"request_id\": \"88888888-8888-4888-8888-888888888888\", \"companion_id\": \"companion.alice\", \"world_context\": {\"snapshot_id\": \"44444444-4444-4444-8444-444444444444\", \"captured_at\": \"2026-09-13T12:00:00Z\", \"scene\": \"exploration\", \"player\": {\"id\": \"party.player\", \"hp_percent\": 80}, \"companion\": {\"id\": \"companion.alice\", \"hp_percent\": 90, \"mp_percent\": 70}}}'
```

完整样例（探索/营地/待机/非战斗危险四类世界快照 + 心跳请求/响应 + 世界事件）见 `data/golden/`；`python -m scripts.mock_ue_flow` 已覆盖 v0.3 骨架链路（心跳限流 → 世界事件幂等 → 调试台）。

### 5.7 终端对话调试（start.bat chat）

无需 UE 即可与 NPC 面对面聊天，用于检查人设与记忆是否合格：

```powershell
start.bat chat          # 或 .\.venv\Scripts\python -m scripts.chat_console --port 8000
```

- 每轮回复附带 `[source | emotion | gesture | face]` 调试行：`source` 为 `mock`（无 LLM 后端）、`llm` 或 `fallback`（LLM 故障回退），表现 ID 可对照 `data/companions/primary_companion.yaml` 白名单核对。
- 同一次 REPL 使用固定 `session_id`，可验证短期会话记忆（接续上文）与长期记忆（重启服务后 `/memory` 仍能看到之前说过的内容）。
- 内置命令：`/help` 帮助、`/memory` 查看三级长期记忆、`/reset` 清空会话+长期记忆、`/scene exploration|conversation` 切换对话场景、`/quit` 退出（服务留在后台）。

人格训练语料（few-shot 优先路线）见 `data/training/README.md`：语料格式、14 个互动分类、人工过滤红线与入库流程。

## 6. 常见问题

- **端口被占用**：`--reload` 启动失败时，可用 `--port 8001` 指定其他端口。
- **PowerShell 激活失败**：按 2.2 节调整执行策略，或改用 `cmd` 执行 `.\\.venv\\Scripts\\activate.bat`。
- **依赖安装缓慢**：可临时使用国内镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
