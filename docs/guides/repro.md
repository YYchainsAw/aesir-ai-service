# NPC 联调复现手册（T21 / #34）

> 目标：UE 侧不读 Python 代码即可确认「当前跑的是哪个 commit、走的是哪条后端链路、响应长什么样」。

## 1. 版本锚点

启动服务后，UE 侧第一步打 `/health`：

```bash
curl http://127.0.0.1:8000/health
```

返回：
```json
{
  "status": "ok",
  "service": "aesir-ai-service",
  "protocol_version": "0.1",
  "service_commit": "335acb6"
}
```

- `protocol_version`：协议大版本（与 `npc-contract-v0.3.md` 对齐）
- `service_commit`：**运行时 git short SHA**（T21 新增），与 CHANGELOG 测试锚点对齐
- 非 git 环境（打包分发）返回 `"unknown"`，不阻塞

## 2. 后端三态对照（Mock / LLM / Fallback）

同一句玩家输入「你好」在三种后端下的响应差异：

| 维度 | Mock（默认） | LLM | Fallback（LLM 故障回退） |
|---|---|---|---|
| 环境变量 | `AESIR_COMPANION_BACKEND=mock` | `AESIR_COMPANION_BACKEND=llm` | LLM 路径自动触发，无需手动切 |
| 触发条件 | 默认启动 | 显式切 llm | LLMClientError（超时/风格重试两次失败） |
| 响应来源 | YAML fallback 候选池 | 真实 LLM 生成 | YAML 候选池（同 mock） |
| `source` 字段 | `"mock"` | `"llm"` | `"fallback"` |
| `style_violations` | `null`（未校验） | `[]` 或非空数组 | `null`（未校验） |
| 耗时基线 | < 5ms（本地 YAML） | ≈2.3s（实测 2026-10-08） | < 5ms |
| 落盘路径 | `data/runtime/dialogue_signals/<game>/<companion>.jsonl` | 同左 | 同左 |

### 实测样本（从落盘 JSONL 摘录）

**LLM 路径**（`data/runtime/dialogue_signals/aesir/companion.alice.jsonl`，2026-10-08）：
```json
{
  "source": "llm",
  "player_text": "你好，艾莉",
  "reply_text": "你好，旅行者。今天天气不错，要出发的话我随时可以走。",
  "emotion_id": "emotion.bright",
  "style_violations": []
}
```

**Fallback 路径**（`data/runtime/dialogue_signals/demo-vn/companion.narrator.jsonl`，2026-10-08）：
```json
{
  "source": "fallback",
  "player_text": "你好",
  "reply_text": "你好。",
  "emotion_id": "emotion.neutral",
  "style_violations": []
}
```

## 3. 一键复现脚本

| 脚本 | 用途 | 启动命令 |
|---|---|---|
| `start.bat` | 一键起服务 / 进 REPL | `start.bat` / `start.bat chat` |
| `scripts/chat_console.py` | 终端对话 REPL（流式） | `.venv/Scripts/python -m scripts.chat_console` |
| `scripts/command_service/mock_ue_flow.py` | 「假 UE」全链路演示（chat → parse → resolve → combat → executions → 心跳 → world） | `.venv/Scripts/python -m scripts.command_service.mock_ue_flow` |
| `scripts/metrics_report.py` | 事后统计落盘 JSONL → SC 判定 | `.venv/Scripts/python -m scripts.metrics_report` |

## 4. 预发状态索引（按 ID 查落盘）

| 维度 | 落盘位置 | 查询方式 |
|---|---|---|
| `game_id` | `data/runtime/dialogue_signals/<game_id>/` | 一级子目录 |
| `companion_id` | `.../<game_id>/<companion_id>.jsonl` | 文件名 |
| `order_id` | `data/runtime/command_service/executions/<game_id>/<YYYYMMDD>.jsonl` | 逐行 `order_id` 字段 |
| `event_id` | 世界事件无独立落盘，仅 HTTP 响应 | 见 `npc-contract-v0.3.md` §6 |
| `request_id` | 关联日志与响应 | HTTP 响应头 / body `request_id` |

## 5. 版本字段矩阵（各端点对照）

| 端点 | `protocol_version` | `policy_revision` | `persona_revision` | `service_commit` |
|---|---|---|---|---|
| `/health` | ✅ | — | — | ✅（T21 新增） |
| `/v1/agent/step` | ✅ | ✅ | ✅ | 走 `/health` 查 |
| `/v1/tactical/resolve` `/command` | ✅ | ✅ | ✅ | 走 `/health` 查 |
| `/v1/companion/chat` | ✅ | — | ✅ | 走 `/health` 查 |
| `/v1/commands/parse` | ✅ | — | — | 走 `/health` 查 |

> `service_commit` 只在 `/health` 暴露一次，UE 侧启动时打一次即可，无需每个请求都查。
