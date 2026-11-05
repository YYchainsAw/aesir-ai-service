# YE26 · 年底 NPC 服务交接文档

> 父 issue: #116 / #118
> 基线 tag: `yearend-2026-11-baseline`（commit `e50fbc1`）
> 交接日: 2026-11-25
> 本文档面向 UE 对接方（YYchainsAw）

---

## 1. 冻结基线

| 项目 | 值 |
|---|---|
| Git tag | `yearend-2026-11-baseline` |
| Commit SHA | `e50fbc1f81299cd86d3e121ca5392acedbee4ffd` |
| 分支 | `develop-dyh` |
| 测试结果 | 1574 passed / 11 skipped（whisper 单独跑） |
| 生成日期 | 2026-11-05 |

**包含能力**：
- v0.5 异步契约（202 提交 / 轮询 / result 回放 / completed_at 可配置）
- #101 记忆纠错 corrected_fact_ids（待真实 LLM 回归验证）
- #113 情感桶回归三阶段全闭环
- 阶段 0/1 完成（Redis 调度 + status journal fallback）
- Alice 人格包 S2~S5 全阶段

---

## 2. 启动命令

### 2.1 开发模式（mock 后端 + development identity）

```powershell
# 环境变量
$env:AESIR_SCOPE_IDENTITY_BACKEND = "development"
$env:AESIR_SCOPE_DEV_PLAYER_ID = "11111111-1111-1111-1111-111111111111"
$env:AESIR_SCOPE_DEV_SAVE_IDS = '["22222222-2222-2222-2222-222222222222"]'
$env:AESIR_COMPANION_BACKEND = "mock"
$env:AESIR_COORDINATION_BACKEND = "memory"
$env:AESIR_SCOPE_LEGACY_ENABLED = "true"

# 启动
.\.venv\Scripts\python.exe scripts\run_server.py
```

**默认监听**：`127.0.0.1:8011`

### 2.2 真实 LLM 模式

```powershell
# 覆盖 companion 后端
$env:AESIR_COMPANION_BACKEND = "llm"

# 火山 Coding Plan（备用端点）
$env:AESIR_LLM_BASE_URL = "https://open-api.volcengineapi.com/api/coding/v3"
$env:AESIR_LLM_MODEL = "ark-code-latest"
$env:AESIR_LLM_API_KEY = "<你的 API KEY>"

# 启动
.\.venv\Scripts\python.exe scripts\run_server.py
```

**注意**：真实 LLM 单次响应 20-40s，UE 旧 0.3 端点 5s 超时必挂。必须用 v0.5 异步模式。

### 2.3 旧 0.3 端点兼容

`AESIR_SCOPE_LEGACY_ENABLED=true` 时，UE 现有 Subsystem（发 protocol_version="0.3" 到 `/v1/agent/step`）可正常工作。

---

## 3. 健康检查

### 3.1 基础健康

```powershell
curl.exe http://127.0.0.1:8011/health
```

**响应**：
```json
{
  "status": "ok",
  "service": "aesir-ai-service",
  "protocol_version": "0.1",
  "service_commit": "e50fbc1"
}
```

**关键字段**：
- `status`: "ok" = 服务运行中
- `service_commit`: 当前运行的 commit SHA（与基线核对）

### 3.2 scoped 上下文检查

```powershell
curl.exe "http://127.0.0.1:8011/v1/scoped/context?save_id=22222222-...&companion_id=companion.alice"
```

**响应关键字段**：
- `service_instance_id`: 服务实例 ID
- `run_id`: 当前 run（null = 未绑定）
- `memory_epoch`: 记忆 epoch（reset 后变化）

---

## 4. 重启步骤

### 4.1 正常重启

1. **停止服务**：`Ctrl+C` 或关闭终端
2. **数据保留检查**：
   - 长期记忆：`data/memory/<npc_id>/memory.json`
   - 关系：`data/relationship/<npc_id>/relationship.json`
   - 对话信号：`data/runtime/dialogue_signals/`
3. **重新启动**：按 §2 命令

### 4.2 scoped 会话恢复

服务重启后，UE 需要：
1. `GET /v1/scoped/context` 获取新的 `service_instance_id`
2. `POST /v1/scoped/runs/bind` 重新绑定 run
3. **不需要重放旧业务请求**——服务重启后旧 run 失效

### 4.3 journal 回放（SQL 模式）

若使用 SQL 存储（`AESIR_SCOPE_STORAGE_BACKEND=sql`）：
- 重启后 `GET /v1/scoped/requests/{id}` 可从 journal 回放已完成结果
- 内存模式（默认）不支持跨重启回放

---

## 5. 回退步骤

### 5.1 回退到上一个稳定版本

```powershell
# 查看历史 tag
git tag -l "yearend*"

# 回退到指定版本
git checkout yearend-2026-11-baseline

# 或回退到任意 commit
git checkout <commit-sha>

# 重新安装依赖（若代码变化）
.\.venv\Scripts\python.exe -m pip install -e .
```

### 5.2 数据回退

**长期记忆/关系**：
- 自动备份：`data/memory/<npc_id>/memory.json.bak`（原子替换前备份）
- 手动回退：停止服务 → 复制 `.bak` 覆盖原文件 → 重启

**对话信号/日志**：
- 不回退（追加式，无副作用）

---

## 6. 环境变量清单

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AESIR_SERVICE_HOST` | `127.0.0.1` | 监听地址 |
| `AESIR_SERVICE_PORT` | `8011` | 监听端口 |
| `AESIR_COMPANION_BACKEND` | `mock` | `mock` / `llm` |
| `AESIR_COORDINATION_BACKEND` | `memory` | `memory` / `redis` |
| `AESIR_SCOPE_IDENTITY_BACKEND` | `disabled` | `disabled` / `development` |
| `AESIR_SCOPE_DEV_PLAYER_ID` | - | development 模式玩家 UUID |
| `AESIR_SCOPE_DEV_SAVE_IDS` | - | development 模式存档 UUID JSON 数组 |
| `AESIR_SCOPE_LEGACY_ENABLED` | `false` | 是否启用旧 0.3 端点 |
| `AESIR_LLM_BASE_URL` | - | LLM API 端点 |
| `AESIR_LLM_MODEL` | - | LLM 模型名 |
| `AESIR_LLM_API_KEY` | - | LLM API 密钥 |
| `AESIR_SCOPE_ASYNC_COMPLETED_AT` | `false` | v0.5 completed 时是否打墙钟时间 |

---

## 7. 验证脚本

### 7.1 v0.5 异步契约自证

```powershell
# 起 server（mock 后端 + development identity）
.\.venv\Scripts\python.exe scripts\run_server.py

# 另开终端
.\.venv\Scripts\python.exe scripts\v05_async_e2e.py
```

**预期输出**：
- v0.5 提交：202（~50ms）
- 轮询 completed：~300ms
- result 字段与同步逐字节一致
- 并发不串台
- 幂等重放正确

### 7.2 全量回归

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q --ignore=tests/services/test_faster_whisper.py
```

**预期**：1574 passed / 11 skipped

---

## 8. 已知限制

| 限制 | 说明 |
|---|---|
| 旧 0.3 端点 5s 超时 | 真实 LLM 必挂，必须用 v0.5 |
| 内存模式不支持跨重启回放 | SQL 模式才支持 journal 回放 |
| 本机无 Redis/docker | SQL+Bearer 真实恢复演示需隔离环境 |
| #101 corrected_fact_ids | 代码已修，待真实 LLM 回归验证 |

---

## 9. 相关文档

- [v0.5 异步契约样例](yearend-v05-contract-examples.md)
- [v0.4 作用域服务开发](scoped-development.md)
- [部署指南](deployment.md)
- [复现手册](repro.md)
- [UE 端联调环境](../../memory/ue-local-env.md)（内部记录）
