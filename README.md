# Aesir AI Service

为 **Aesir Combat Prototype** 提供本地 AI 服务：把玩家的**文本或语音**战术指令转换为 UE 可校验的 `TacticalOrder` JSON（契约 v0.1），并提供 v0.2 上下文感知战术决策 `/v1/tactical/resolve`。解析后端（规则 / LLM）与语音转写后端（mock / faster-whisper）均可插拔，输出协议保持不变。

详细设计见 `docs/项目介绍.md`；UE 侧通信契约见 `docs/UE5-协议格式契约-v0.1.md`。

## 启动

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

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
| `POST` | `/v1/companion/chat` | 陪伴对话 |
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

~~真人声调优~~（已取消：无真人录音样本；`scripts/asr_eval.py` 评测脚手架保留备用）。

## 测试

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

覆盖契约 v0.1、语音链路、LLM 回退、v0.2 tactical resolve 与回归评测等（169 通过 + 2 条冒烟默认跳过）。真机 ASR 冒烟需 `AESIR_ASR_SMOKE=1`。

## 调试

PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，**请改用 `Invoke-RestMethod` 或 `curl.exe`**。浏览器打开 `http://127.0.0.1:8000/docs` 可交互式调用接口。
