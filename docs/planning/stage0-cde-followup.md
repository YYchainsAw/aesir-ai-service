# 阶段 0c/0d/0e：Redis 调度器的影子验证与下线内存后端

> 关联提交：`0ad7ada`（develop-dyh）。0a/0b 已落地，单机单 worker 语义已用 fakeredis 验证（1503 passed / 0 failed）。跨 worker 行为尚未验证。

## 背景

50k 人规模架构改造的阶段 0 目标：把请求协调器的易失调度态（全局生成槽/会话串行/排队深度/唤醒）从进程内存外置到 Redis，使多 worker 可水平扩展。用户拍板的三项硬约束：

1. 阶段 0 保持同步——UE 契约零改动（异步化推到阶段 2）
2. 单实例 Redis（带持久化 + 哨兵）足够，不上 Cluster
3. `coordination_backend=redis` 但 `scope_storage_backend=json` 启动即拒（已落地）

0a/0b 已完成：`SchedulerBackend` Protocol + `InMemoryScheduler`（默认，逐字节保留原语义）+ `RedisScheduler`（NX 信号量 + 租约 TTL，无 Lua）。

## 0c：影子模式双写比对

**目标**：在真实 Redis 实例上并行运行 `InMemoryScheduler` 与 `RedisScheduler`，比对调度决策（谁先占槽、谁被串行、排队深度）是否逐字节一致。

- 新增 `ShadowScheduler`：实现 `SchedulerBackend`，内部委托两个后端，每次操作后比对状态
- 测试：用 fakeredis 模拟真实 Redis 行为，跑现有 `tests/scoped/test_requests.py` 全部用例，比对两个后端的 `running`/`waiting`/`sessions` 快照
- 通过标准：1430 个原有测试在 shadow 模式下全绿，且两个后端的调度决策无偏差

## 0d：双 worker + 混沌测试

**目标**：验证跨 worker 的 NX 抢占、租约过期接管、会话串行跨进程语义。

- 测试夹具：两个 `RequestCoordinator` 实例共享同一个 fakeredis（或真实 Redis），模拟双 worker
- 场景：
  - 两个 worker 同时请求同一会话：只有一个能占槽
  - worker A 占槽后崩溃（锁靠租约过期）：worker B 能接管
  - 全局槽上限在跨 worker 维度生效（max_concurrency=2 时，两个 worker 各占一个，第三个请求必排队）
  - 排队深度在跨 worker 维度生效
- 混沌注入：随机延迟、随机释放、随机崩溃（不删锁，靠租约过期）
- 通过标准：所有场景无死锁、无双执行、无槽泄漏（租约过期后自动清理）

## 0e：下掉内存 coordinator

**目标**：把默认后端从 `InMemoryScheduler` 切到 `RedisScheduler`，内存后端降级为测试替身。

- `config.py`：`coordination_backend` 默认值从 `memory` 改为 `redis`
- `InMemoryScheduler` 标记为 `@pytest.fixture` 专用（或移到 tests/）
- 文档：更新部署手册，要求 Redis 实例 + 哨兵配置
- 通过标准：生产模式启动即连 Redis，连不上快速失败；测试模式仍用 fakeredis

## 阶段 1：状态层 MySQL journal 权威化

**目标**：请求注册表（`_entries`）、结果/错误、取消 tombstone 跨进程共享。

- 现状：这些状态留在 `RequestCoordinator` 内存里，多 worker 各自维护一份
- 改造：SQL 模式下，`_entries` 的权威版本由 `app.persistence.journal` 承担（已有第四步持久化基础）
- 每个 worker 启动时从 journal 重建 `_entries`；完成态结果写 journal，重放者从 journal 读
- 通过标准：双 worker 下，同一逻辑请求的结果在两个 worker 间一致

## 阶段 2：异步化（UE 契约变更）

**目标**：接收请求的 worker 不再阻塞跑生成，而是推队列立即返回 `request_id`，UE 轮询 `/status`。

- 用户拍板：阶段 0 不做这个，等状态层（Redis+MySQL）稳定后再改
- 改造点：
  - 接收端点立即返回 `{"request_id": "...", "status": "queued"}`
  - 后台 worker 池消费队列
  - UE 轮询 `/v1/scoped/requests/{id}` 拿最终结果
- 这是唯一改变 UE 契约的阶段，需要与 UE 侧协调

## 非目标（本期不做）

- Redis Cluster（用户明确拍板不上）
- HTTPS / 认证增强（独立任务）
- 多租户隔离（50k 之外的事）
- 跨设备合并（独立任务）

## 验证命令

```powershell
# 本地跑全部适用核心
.\.venv\Scripts\python.exe -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q

# RedisScheduler 单测（fakeredis）
.\.venv\Scripts\python.exe -m pytest tests/scoped/test_redis_scheduling.py -q
```
