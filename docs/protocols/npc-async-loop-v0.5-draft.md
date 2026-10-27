# NPC 异步请求契约 v0.5（设计草案 · 待 UE 对齐）

> 2026-10-27 起草。本页是 [50k 人架构改造阶段 2](../planning/stage0-cde-followup.md#阶段-2异步化ue-契约变更) 的 UE 契约设计稿。
> 基线：develop-dyh@`9c25895`，阶段 0（Redis 外置调度）+ 阶段 1（status journal fallback）已闭环。
> **2026-10-27 进展**：§4 的 result 回放已实现（`ScopedRequestStatusResponse` 加 `result` 字段；内存 `_record()` 与 journal `read_status()` 在 completed 时回放业务结果，其余状态为 None）。同步模式下 UE 也可拿 POST 结果回查。
> **§3 的 202 提交已落地服务端（develop-dyh@`d0b6ffe`，受控 1566 绿，未经 UE 联调）**：`chat`/`agent-step` 发 `protocol_version="0.5"` opt-in——提交线程只做校验/配额/容量准入即返回 §3.2 信封（202，不含业务结果），业务闭包投递进程内守护池（`app/scoped/async_pool.py`，contextvars 捕获 scope/principal/budget）执行；`coordinator.submit()`/`run_submitted()` 把登记入队与执行段拆开；幂等 `begin/settle/settle_failure` 不等待，同 request_id 网络重试在 `running` 时**不重复投递后台**（否则两 worker 把同一 action 跑两遍）。其余入口不放开 0.5（422）；v0.4 同步 200 永久保留。**第 8 节三个开放问题仍待 UE 拍板，服务端默认值尚未冻结。**
> 阅读前提：[闭环增量契约 v0.4](npc-loop-contract-v0.4.md) 的请求生命周期与状态机全部沿用，本页只定义异步化带来的增量变更，未提及字段保持 v0.4 原样。

## 1. 为什么要异步

现状（v0.4 同步）：UE 调 `POST /v1/scoped/companion/chat` 或 `/agent/step`，服务端**在 HTTP 请求线程内**跑完整 LLM 生成再返回结果。多 worker 水平扩展后：

- 每个 worker 的 HTTP 连接被一次 LLM 调用占住数秒，并发上限 = HTTP 连接池大小，与生成并发（全局 2 槽）脱钩；
- 非粘性部署下同一 UE 的两次请求落到不同 worker，会话串行语义只能靠 Redis 调度兜底，但响应仍必须由接收 worker 自己跑完。

目标：接收 worker 登记后**立即返回 202**，业务执行交给后台 worker 池；UE 轮询 `GET /requests/{id}` 拿终态结果。

## 2. 变更范围（先划边界）

| 入口 | 模式 | 理由 |
| --- | --- | --- |
| `POST /v1/scoped/companion/chat` | **同步→异步（v0.5 opt-in）** | LLM 生成 1~3s，唯一占连接的入口 |
| `POST /v1/scoped/agent/step` | **同步→异步（v0.5 opt-in）** | 同上；text 非空时走 LLM，心跳可仍快速返回（见 §5） |
| `POST /v1/scoped/world/events` | 保持同步 | 纯规则 ~27ms，无 LLM，异步化无收益 |
| `POST /v1/scoped/tactical/executions` | 保持同步（已是 202 受理语义） | 回执落盘即返回 |
| runs/bind、runs/end、encounters/control、memory/reset | 保持同步 | 控制路径，毫秒级 |
| `POST /v1/scoped/requests/cancel` | 不变 | 短控制路径，本就在生成队列之外 |
| `GET /v1/scoped/requests/{id}` | **扩展**：completed 时携带业务结果（§4） | 轮询拿结果的唯一出口 |

## 3. 提交入口的 opt-in 语义（v0.5）

**不做全局切换。** UE 在请求体中显式发 `protocol_version: "0.5"` 才进入异步模式；发 `"0.4"` 或不发的现有请求一律保持同步 200 行为不变。双跑期两类客户端并存，UE 改造一个端点切一个。

### 3.1 提交时仍同步完成的校验（失败立即返回，不进队列）

以下检查与当前同步路径完全相同，仍在提交线程内失败：

- 作用域/绑定/epoch 校验（403/409）；
- 请求体 schema 校验（422）；
- 配额（429）；
- **队列准入**：会话深度/全局等待/全局槽上限（503 `REQUEST_QUEUE_FULL`）。容量检查通过即视为已登记（v0.4 契约原文"不确定提交保持占位"）。

### 3.2 异步提交成功的响应

HTTP **202**，响应体是当前 `_base(scope, request_id)` 信封加状态，**不含业务结果**：

```json
{
  "protocol_version": "0.5",
  "scope": { "game_id": "...", "player_id": "...", "save_id": "...", "npc_key": "..." },
  "service_instance_id": "...",
  "run_id": "...", "run_binding_id": "...", "memory_epoch": "...",
  "session_id": "...", "encounter_id": null,
  "request_id": "<原 request_id 回显>",
  "state": "queued",
  "timing": { "valid_for_ms": 6000 }
}
```

- `state` 只能是 `queued` 或 `running`（提交即获槽时）；**UE 不得假设 POST 返回即有结果**。
- `timing.valid_for_ms` 是**从提交时刻起算的总预算**。排队消耗预算；排队超时则该请求不执行，终态 `expired`（reason_code `REQUEST_EXPIRED`），UE 必须以**新 request_id** 重发，不能用旧 ID 续期（v0.4 契约：状态键不加入 epoch/binding 作为绕过去重的新维度）。
- 同 request_id 网络重试：幂等账本返回已登记项的当前状态（queued/running/completed），不会重复执行。

## 4. 轮询出口：`GET /v1/scoped/requests/{target_request_id}` 扩展

现有查询参数（scope/binding/epoch/operation）不变。响应在现有 `_record()` 字段基础上按状态分叉：

| state | 响应 |
| --- | --- |
| `queued` / `running` | 仅现有字段（状态、queue_ms/processing_ms、upstream_attempts、cancel_requested），**不带 result** |
| `completed` | 现有字段 **+ `result` 对象**——即原同步 200 响应体会原样回放（chat：对话回复+表现 ID；agent-step：output+directive 信封） |
| `cancelled` | 现有字段 + `reason_code`；不带 result |
| `expired` / `failed` | 现有字段 + `reason_code`；UE 以新 request_id 发起新意图 |
| `unknown` | 现有字段；**不得自动重发**（v0.4 契约原文），等人工核对或复用本 ID 后续查询 |

设计要点：

1. **result 回放是本阶段唯一新增读路径。** 现状 `ScopedRequestStatusResponse` 注释为"the read does not replay its business result"（同步模式下 UE 已从 POST 拿到结果）——v0.5 起 completed 请求必须回放。result 的 schema 与对应端点同步响应**逐字段相同**，不另造DTO（UE 同一套解析代码可复用）。
2. **跨 worker 结果已通。** 阶段 1 的 `journal.read_status()` 已能把 journal 行折成同形状 record；`stage_active_result(result)` 本就把业务结果落 journal。worker B 轮询 worker A 完成的请求，completed+result 从 journal 读出——无需新存储。
3. 回放不改变、不刷新任何指令有效期；directive 有效期仍以指令注册时刻起算（现状语义不变）。
4. 终态保留期维持 v0.4 口径（正常终态 300 秒可配置）；UE 超过保留期再查 → 404 `REQUEST_UNKNOWN`，只能重发新请求。UE 侧轮询设计须在保留期内拿到终态。

## 5. 服务端实现要点（给后续工程，不在本契约稿范围）

- 提交线程：现有 `_execute()` 拆两段——校验/配额/容量（同步）+ 登记入队后立即返回 202；业务闭包投递到**进程内后台 worker 池**。
- 后台池线程执行与现有 `coordinator.execute(action)` 完全同一条代码路径（Redis 全局槽/会话串行/取消检查/预算裁剪全部复用），只是调用方从 HTTP 线程换成池线程。**不做跨进程 work-stealing**：闭包只活在接收进程内，跨进程只做槽位仲裁，不做任务搬运（本阶段非目标）。
- 心跳型 agent-step（text 为空、无 LLM）：池内执行也是毫秒级，可不入队直接同步完成返回 200——由服务端按 operation 是否触 LLM 决定，UE 无需区分。
- 池大小与全局生成槽（默认 2）解耦：池 >= 全局槽 × 预期 worker 数即可，真正的并发上限仍由 Redis 槽位裁决。

## 6. UE 侧适配清单（双跑期对齐用）

1. 收到 202 后**立即丢弃等待 body 的逻辑**，转入轮询：建议起始 100~200ms 间隔、指数退避到上限 1s；拿到终态即停。
2. 轮询请求必须带与提交时相同的完整 scope/binding/epoch 查询参数（现状要求不变）。
3. `completed` → 用 result 字段驱动表现；`expired/failed/cancelled/unknown` → 走对应本地兜底（文案/重试入口），**unknown 绝不静默重发**。
4. 超时预算：UE 展示层的"思考中"计时不得超过提交时收到的 `valid_for_ms`，避免用户等一个已 expired 的请求。
5. 取消：用户中途打断时调 `/requests/cancel`；queued 中取消立即生效，running 中取消以终态轮询为准（v0.4 语义：已最终提交的事实不撤销）。

## 7. 非目标（本阶段明确不做）

- 不引入服务端推送（SSE/WebSocket）——轮询是唯一出口；
- 不做跨进程任务搬运/工作窃取；
- 不改 LLM 供应商、熔断、超时口径；
- world/events / executions / 控制入口不同步化；
- v0.4 同步模式不下线（UE 全量切完前永久保留）。

## 8. 待 UE 侧拍板的开放问题

1. 轮询节奏与保留期匹配：默认终态保留 300s 是否够 UE 最坏轮询路径，还是延长到 600s？
2. result 回放字段冻结点：建议直接复用同步响应 schema；UE 是否需要在 result 内额外附带 `completed_at` 服务端打戳（用于 SC-011 类采样）？
3. 单请求预算上限默认值：异步后排队时间计入预算，默认值是否从现口径上调（例如 6s→10s）？

---

> 落地顺序建议：本稿与 UE 侧对齐开放问题后，先实现 §4 的 result 回放（同步模式下也能用：UE 同步拿到结果后仍可回查），再切 §3 的 202 提交。两步可独立上线，互不阻塞。
