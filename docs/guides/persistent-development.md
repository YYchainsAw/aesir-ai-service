# SQL持久化、访问控制与恢复开发指南

2026-10-22，适用于第四步PR #88合入后的main及 `fix/npc-schema-validation` 后续修正。字段和错误以[持久化增量契约](../protocols/npc-persistence-contract-v0.4.md)、`app/schemas/recovery.py`、`app/schemas/sync.py`与golden为准；本页只维护操作与交接。原v0.4绑定/预算使用[基础指南](scoped-development.md)，范围和真实结果见[第四步计划](../planning/step-04-persistence-access-plan.md)及[验证记录](../logs/verification-records.md#persist-20261022)。

## 1. 环境与配置

项目venv新增SQLAlchemy Core 2.1.6、PyMySQL 1.2.3及其RSA认证依赖，无Redis/MQ/向量数据库。原未提交Linux锁文件保持历史快照；本次SQL增量约束见 `requirements-sql-linux-py312.lock`，可用 `pip install -r requirements-dev.txt -c requirements-sql-linux-py312.lock` 复现新增依赖。MySQL为正式存储目标，SQLite仅在显式测试模式中使用。继续单worker；默认JSON后端和现有开发`.env`保持，不在不知情时切换真实数据。

本轮独立验证实例为 `aesir-ai-dev-mysql84`，MySQL 8.4.13，只监听 `127.0.0.1:13306`；容器限制640MiB、0.75CPU，数据在 `/var/lib/aesir-ai-dev/mysql84`，不会改现有5.7或其他业务。专用dev/test/restore应用库与迁移/运行凭据在 `/etc/aesir-ai/dev`，目录0700、连接文件0600。正式发布应为目标库单独配最小权限账号；本轮验证账号只涉及上述专用项目库，无DDL的运行账号不能读MySQL系统授权表。

| 配置 | 默认及作用 |
| --- | --- |
| `AESIR_SCOPE_STORAGE_BACKEND` | `json`；显式设 `sql` 才使用SQL权威状态 |
| `AESIR_SCOPE_DATABASE_URL_FILE` | 优先读取的私有0600文件；内容为MySQL/PyMySQL连接串，不在终端输出或Git记录 |
| `AESIR_SCOPE_DATABASE_URL` | SecretStr备选；不把含密码URL写入shell参数/PR/日志 |
| `AESIR_SCOPE_DATABASE_POOL_SIZE` | 5，连接池上限；LLM期间不持连接/事务 |
| `AESIR_SCOPE_SQLITE_TEST_MODE` | false；只在隔离测试显式true，拒绝把SQLite当数据库故障回退 |
| `AESIR_SCOPE_IDENTITY_BACKEND` | 默认disabled；正式模式bearer；development保留固定服务器身份开发用途 |
| `AESIR_SCOPE_REQUEST_QUOTA_PER_MINUTE` | 120，已接入的业务准入/控制/同步请求额度，非全部HTTP频率限制 |
| `AESIR_SCOPE_UPSTREAM_QUOTA_PER_DAY` | 200，game/player每日实际上游调用预留，不是货币硬预算 |
| `AESIR_SCOPE_SYNC_BATCH_LIMIT` | 50，可配置1～100；schema硬上限100，每条event最多16KiB |

开发可手动 `docker start aesir-ai-dev-mysql84`；容器本轮未设开机自动发布。停用验证环境可 `docker stop aesir-ai-dev-mysql84`，不删卷或备份。正式守护、OS受限用户、HTTPS、传输限制、备份调度和容量验证留第六步。

## 2. 显式初始化与授权

建表前先审查[数据库设计](../design/database/README.md)与[SQL执行规范](../design/database/sql/README.md)：空库可选择保留的初始DDL或下述CLI，两者不重复执行。已有库先用 `scripts.check_database_design --database-url-file <私有文件>` 只读审计；开发库expires_at可空漂移已在备份后受控修复，三个项目库审计均通过，见[本轮证据](../logs/verification-records.md#schema-gate-20261022)。运行时 `check_schema()` 现与该审计共享metadata结构检查；样本collation未写进metadata，不硬编码为0900，部署仍须核对大小写语义。

以下命令在服务器项目根运行，仅通过文件路径选角色，连接串不出现在命令参数。`init`不带apply只显示计划；应用schema用迁移账号，日常进程用仅SELECT/INSERT/UPDATE/DELETE运行账号。SQL进程在启动与首次取数据库连接时校验结构，通过后缓存连接，不逐请求重复反射。schema版本或结构与声明不符会拒绝；初始化只在没有任何表的专用空库执行DDL，既有完整v1幂等只读检查，部分库或漂移不自动补表。不能以自动create_all代替升级迁移或DDL回滚。

```bash
cd /www/wwwroot/aesir-ai-service
export AESIR_SCOPE_STORAGE_BACKEND=sql
AESIR_SCOPE_DATABASE_URL_FILE=/etc/aesir-ai/dev/mysql84-dev-migrator.url \
  .venv/bin/python -m scripts.persistence_data init --apply
export AESIR_SCOPE_DATABASE_URL_FILE=/etc/aesir-ai/dev/mysql84-dev-runtime.url
.venv/bin/python -m scripts.manage_access player-create
.venv/bin/python -m scripts.manage_access save-grant --player-id <玩家UUID> --save-id <存档UUID>
.venv/bin/python -m scripts.manage_access token-issue --player-id <玩家UUID> \
  --permission npc:use --ttl-seconds 3600 --output /etc/aesir-ai/dev/client-credentials/new-token.txt
```

签发前在站点根外准备私有0700父目录；output必须是新的绝对路径，不在整个 `/www/wwwroot` 内，文件0600且拒绝覆盖。CLI只显示credential_id，明文从受限文件由授权开发者交给客户端；不要把token贴到聊天、issue或日志。需要console/清理/文档时分别签发对应权限，普通业务凭据不自动得到它们。撤销用 `token-revoke --credential-id <UUID>`，存档撤回用 `save-revoke`，玩家停用用 `player-state --active false`；更改在后续鉴权及提交边界复核。

独立SQL验证进程示例（与现有18011开发实例分开）：

```bash
AESIR_SCOPE_IDENTITY_BACKEND=bearer AESIR_SCOPE_LEGACY_ENABLED=false \
AESIR_COMPANION_BACKEND=mock AESIR_INTENT_BACKEND=rule AESIR_PARSER_BACKEND=rule \
  .venv/bin/python -m scripts.run_server --host 127.0.0.1 --port 18012
```

不启用reload或额外worker；本例无真实LLM调用。PyCharm可在独立Run Configuration中设置同样环境值与工作目录，不编辑现有`.env`。Bearer模式即使legacy开关为true也拒绝旧入口；文档/OpenAPI需管理读取权限。18012仅用于本轮受控检查，演练结束会停止临时进程。

## 3. 请求、恢复与同步

1. 携带Bearer发现context并显式bind；战斗显式begin/end。普通业务继续原scope/binding/epoch/单调预算，不把UTC墙钟差当有效期。
2. 网络重试保留原request_id和语义载荷；同会话FIFO提交后再放行。实际供应商调用前独立预留额度，缓存重试不再调用；已预留不会因取消或SQLrollback退款。控制/同步重试仍可能计入请求额度，HTTP传输频率另由发布层限制。
3. 服务重启后重新发现/绑定；不要重播旧聊天/音频/心跳/建议。用 `/recovery/state` 获取自有权威快照，用 `/recovery/operations/{id}` 或 `/recovery/directives/{id}`核对原run确认。这些响应不能直接驱动Action/GAS。
4. 离线真实事件走 `/sync/facts`，保留原fact UUID、run/encounter、来源、原epoch和存档generation；每批用新request_id绑定完整载荷。STATE_VERSION_CONFLICT先拉 `/sync/state`，再以新批次ID重试仍合法的原事实ID，不上传本地总分。实时与离线共享确认，不重复加分。
5. 清记忆后旧epoch的memory分项skipped_reset，relationship独立确认。无活动上下文时memory明确not_applied_missing_context，不能把它写成已恢复记忆。客户端只移除已确认分项，保留未同步状态并按约定处理；本轮未制作UE本地队列。
6. 旧绑定/过期关联窗口的回执走 `/recovery/receipts`，引用原已发布指令、请求、能力、遭遇和原epoch；只归档，不补执行。`stored`表示实际新增记录；`duplicate`表示全部身份原本已知，因此stored=0不必duplicate=true（如终态后新身份accepted被忽略）。同终态的新sequence仍是新身份。此归档确认可跨重启按原批次取回，响应里的原service_instance不能当成新绑定。
7. 遇UNKNOWN保留原关联人工核对，不换ID重做。SQL身份记录不自动TTL遗忘，数据保留/压缩策略与容量需发布前核定；没有启用多worker一致性。

## 4. JSON导入与切换

先停止目标数据写入并备份，确认源属于具体game/player/save/npc。默认dry-run只预检完整scoped目录与schema；legacy归属不明文件排除，不自动认领。导入记录源SHA且不修改原JSON；对目标同内容可重复导入，对不同内容拒绝整批覆盖。

```bash
.venv/bin/python -m scripts.persistence_data import-json \
  --memory-root <明确的memory-root> --relationship-root <明确的relationship-root>
.venv/bin/python -m scripts.persistence_data import-json \
  --memory-root <明确的memory-root> --relationship-root <明确的relationship-root> --apply
```

导入使用当前显式选择的目标库；不扫描后把任意legacy默认角色分配给固定开发玩家。切换前核对源哈希、目标计数、epoch、关系及新配置。开始SQL写入后不能直接切回旧JSON并丢掉新增记录；本轮没有自动SQL→旧JSON反迁工具，回滚使用已核对SQL恢复点或先单独设计导出/收敛流程。

## 5. 备份与恢复

备份包含schema版本、业务文档、epoch、确认版本、逻辑身份、事件/回执、授权/撤销和额度。输出为站点根外私有目录内新的0600文件，带完整内容校验；拒绝覆盖。备份不是只复制memory.json，不能丢掉去重/重置屏障后继续写。

```bash
.venv/bin/python -m scripts.persistence_data backup --output /etc/aesir-ai/dev/backups/new-backup.json
AESIR_SCOPE_DATABASE_URL_FILE=/etc/aesir-ai/dev/mysql84-restore-migrator.url \
  .venv/bin/python -m scripts.persistence_data init --apply
AESIR_SCOPE_DATABASE_URL_FILE=/etc/aesir-ai/dev/mysql84-restore-migrator.url \
  .venv/bin/python -m scripts.persistence_data restore --input /etc/aesir-ai/dev/backups/new-backup.json
AESIR_SCOPE_DATABASE_URL_FILE=/etc/aesir-ai/dev/mysql84-restore-migrator.url \
  .venv/bin/python -m scripts.persistence_data restore --input /etc/aesir-ai/dev/backups/new-backup.json --apply
```

恢复只允许已初始化的空隔离目标；先检查格式、schema、哈希、表集和身份，再同事务写入，失败不改源备份或留下部分目标。恢复报告有table_counts和credential_policy。所有恢复credentials均强制revoked，防较旧备份使后续已撤销token复活；核对授权/存档后显式签发新凭据，原备份仍保真。

数据回到备份恢复点，不能推测备份之后的写入、授权撤回或reset。正式灾备切换必须先核对恢复点/RPO、补齐之后的清理/撤销事实，再启用新service_instance并使旧UE缓存失效；本轮不自动切换生产库，也不承诺较旧备份保留未来的reset。恢复后的旧逻辑请求仍只读确认，不重播动作。备份保留/加密/异地副本、调度和恢复时限需正式发布另验。

## 6. 验证及UE待办

SQLite隔离回归与实际MySQL分开运行；实际库测试需显式指定受限验证URL文件：

```bash
AESIR_TEST_MYSQL_URL_FILE=/etc/aesir-ai/dev/mysql84-test-runtime.url \
  .venv/bin/python -m pytest tests/persistence/test_mysql_integration.py -q --tb=short
```

完整适用命令、真实进程重启/备份恢复结果及源码哈希见[验证记录](../logs/verification-records.md#persist-20261022)。未提供真实库路径时5个MySQL专项明确skip，不能把它们算成MySQL通过。UE仍需实现可信凭据接入、按档缓存、稳定事实/回执队列与分项移除、版本冲突拉取、容量/保留/退避/失败状态、断网本地兜底及SC-011采样。本轮未连接或修改UE，第四步服务端通过不等于全部DEP/EVO或正式多人发布完成。
