# YE26-04 · v0.5 异步契约样例文档

> 父 issue: #116 / #120
> 基线 tag: `yearend-2026-11-baseline`（commit `e50fbc1`）
> 验证脚本: `scripts/v05_async_e2e.py`

本文档记录 v0.5 异步契约的核心语义样例，供 UE 联调参考。

---

## 1. 基础流程：202 提交 → 轮询 completed

### 请求
```http
POST /v1/scoped/companion/chat HTTP/1.1
Content-Type: application/json

{
  "protocol_version": "0.5",
  "request_id": "req-001",
  "save_id": "22222222-...",
  "service_instance_id": "...",
  "companion_id": "companion.alice",
  "run_id": "...",
  "run_binding_id": "...",
  "memory_epoch": "...",
  "timing": {
    "capture_age_ms": 20,
    "request_age_ms": 0,
    "max_snapshot_age_ms": 30000,
    "max_request_age_ms": 120000
  },
  "text": "你好"
}
```

### 响应（立即 202）
```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "protocol_version": "0.5",
  "request_id": "req-001",
  "state": "queued",
  "run_id": "...",
  "run_binding_id": "..."
}
```

**实测延迟**：47ms（vs 同步 140ms）。

### 轮询
```http
GET /v1/scoped/requests/req-001?operation=chat&save_id=...&run_id=... HTTP/1.1
```

**响应（completed）**：
```json
{
  "state": "completed",
  "result": {
    "reply_text": "嗨！来得正好…",
    "emotion_id": "emotion.neutral",
    "gesture_id": "gesture.small_wave",
    "facial_expression_id": "face.smile",
    "relationship_delta": 0,
    "source": "mock",
    "...": "其余 22 字段与 v0.4 同步完全一致"
  }
}
```

**实测轮询耗时**：328ms 总到 completed（mock 后端）。

---

## 2. 幂等：重复 POST 同一 request_id

### 场景
网络重试导致客户端重复发送同一 `request_id`。

### 行为
- 第一次 POST：202 Accepted（queued）
- 第二次 POST（相同 request_id）：
  - 若请求仍在执行 → 返回 202（当前 state）
  - 若已完成 → 返回 200（回放原结果，不重新执行）

**保证**：同一 request_id 不会重复投递后台池、不会重复写记忆、不会重复扣关系分。

---

## 3. 乱序：先 GET status 再 POST

### 场景
客户端先查询某个 request_id 的状态，但该请求尚未提交。

### 行为
- GET /requests/{id} 返回 404 INVALID_SCOPE_OR_TIMING
- 客户端应等待 POST 响应后再开始轮询

---

## 4. 超时：LLM 响应超过 max_request_age_ms

### 场景
LLM 后端慢（实测 20-40s），UE 默认预算 30s 不够。

### 行为
- POST 时 `max_request_age_ms=30000`（30s）
- LLM 35s 才返回 → 409 REQUEST_EXPIRED
- **注意**：LLM 已跑完但结果过期，UE 不会收到

### 建议
- UE 在 v0.5 模式下设 `max_request_age_ms=120000`（120s）
- 或服务端默认值调大（待 UE 拍板）

---

## 5. 并发：两个 v0.5 请求不串台

### 场景
同时提交两个聊天请求（不同 request_id）。

### 行为
- 两个都立即 202
- 各自后台执行，contextvars.copy_context() 隔离
- 各自 completed，reply 各自连贯

**实测**：两个并发 v0.5 均 completed，未串台、未死锁。

---

## 6. 重启回放：服务重启后 GET /requests/{id}

### 场景
请求已 completed 并落 journal，服务重启后客户端查询。

### 行为
- GET /requests/{id} 从 journal 回放 completed 结果
- 不需要重新执行
- **阶段 1 已实现**（commit `830915d`）

### 限制
- 内存模式（非 SQL）：重启后内存状态丢失，journal 回放依赖 SQL
- SQL 模式：跨 worker/重启可完整回放

---

## 7. completed_at 可配置字段

### 场景
UE 需要知道 completed 的确切时间（SC-011 时延统计）。

### 行为
- 默认：`completed_at=null`（不打戳，向后兼容）
- 开启 `AESIR_SCOPE_ASYNC_COMPLETED_AT=true`：completed 时填 UTC ISO 墙钟

**实测**：commit `c8357fb` 已落地，UE 拍板后开配置即可。

---

## 验证脚本

`scripts/v05_async_e2e.py` 自动验证以上 1-5、7 项：

```bash
# 起 server（mock 后端 + development identity）
AESIR_SCOPE_IDENTITY_BACKEND=development \
AESIR_SCOPE_DEV_PLAYER_ID=11111111-1111-1111-1111-111111111111 \
AESIR_SCOPE_DEV_SAVE_IDS=["22222222-2222-2222-2222-222222222222"] \
AESIR_COMPANION_BACKEND=mock \
AESIR_COORDINATION_BACKEND=memory \
AESIR_SCOPE_LEGACY_ENABLED=true \
.venv/Scripts/python.exe scripts/run_server.py

# 另开终端跑验证
.venv/Scripts/python.exe scripts/v05_async_e2e.py
```

**实测结果**（2026-11-05）：
- v0.5 提交：202（47ms）✅
- 轮询 completed：328ms ✅
- result 字段：22 个与 v0.4 逐字节一致 ✅
- 并发两个 v0.5：各自 completed ✅
- 幂等重发：200 回放原结果 ✅

---

## 待 UE 拍板的开放问题

1. **max_request_age_ms 默认值**：当前 30s，真实 LLM 需 120s
2. **终态保留期 300s**：是否够最坏轮询（建议观测长尾）
3. **completed_at**：是否开启（服务端已可配置）
