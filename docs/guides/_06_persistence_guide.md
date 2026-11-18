# SQL持久化、访问控制与恢复开发指南

第四步 PR #88 后的 SQL/Bearer 开发与恢复说明；2026-11-16 补齐 JSON/development 对照。字段和错误以[持久化增量契约](../protocols/_01_npc_contract.md#persistence)、`app/schemas/recovery.py`、`app/schemas/sync.py`与golden为准；本页只维护操作与交接。原v0.4绑定/预算使用[基础指南](_04_scoped_development_guide.md)，范围和真实结果见[第四步计划](../planning/_05_persistence_plan.md)及[验证记录](../records/_01_verification_records.md#persist-20261022)。

## 模式速查：JSON/development 与 SQL/Bearer

存储、身份和协调是三个独立配置轴，下表比较两种常用组合。`development` 从服务器配置取得固定玩家与可用存档，不验证传入的 Bearer；拿它的成功请求不能证明正式认证已通过。`sql` 也不会自动启用 Bearer 或 Redis。

| 项目 | JSON + development（本机开发） | SQL + Bearer（正式身份与持久确认） |
| --- | --- | --- |
| 身份 | `AESIR_SCOPE_IDENTITY_BACKEND=development`，固定 `AESIR_SCOPE_DEV_PLAYER_ID` 与 `AESIR_SCOPE_DEV_SAVE_IDS` | `AESIR_SCOPE_IDENTITY_BACKEND=bearer`，数据库中的凭据、玩家状态、存档授权与权限 |
| 权威状态 | `AESIR_SCOPE_STORAGE_BACKEND=json`；记忆、关系为分区文件 | `AESIR_SCOPE_STORAGE_BACKEND=sql`；业务文档、版本、请求/事件/回执确认在数据库 |
| 物理位置 | `<AESIR_MEMORY_ROOT>/<game>/<player>/<save>/<npc>/memory.json`；关系在 `<AESIR_RELATIONSHIP_ROOT>` 下同样分区；默认根分别为 `data/memory`、`data/relationship` | `AESIR_SCOPE_DATABASE_URL_FILE` 指向私有连接文件；不要从旧 JSON 文件判断 SQL 当前值 |
| 协调 | 隔离单进程可显式 `AESIR_COORDINATION_BACKEND=memory` | 发布要求 Redis；本机 SQL + memory 只用于隔离验证。Redis + JSON 会被门禁拒绝 |
| 服务重启 | 记忆/关系文件保留；进程内 binding、请求缓存、FIFO 不保留，不能保证跨重启原 ID 去重 | SQL 保留权威状态和持久确认；仍须获取新 context 并重新 bind，旧实例关联不能执行新动作 |
| 恢复与同步 | 不提供持久 recovery/sync；不能用重发旧聊天重建丢失确认 | 使用下面的只读恢复与稳定事实/回执归档路径；不重放历史动作 |
| 日志 | 信号仍是文件；清记忆不等于删除信号或关系 | 信号也仍是文件，不能将其当作 SQL 事务确认或完整恢复备份 |
| 验收含义 | 可验证开发业务和真实 LLM/ASR，但不证明 Bearer、真实 MySQL、UE/GAS 执行或生产恢复 | SQLite/TestClient 只覆盖隔离逻辑；真实 MySQL、HTTP 进程重启、目标部署和 UE 执行仍分别验收 |

### 本机 JSON 开发启动

在项目根设置当前终端环境，不覆盖私有 `.env`。以下固定身份只用于本机合成数据；mock 是无上游费用的接口检查，不能作为真实模型验收。

```powershell
$env:AESIR_SCOPE_STORAGE_BACKEND='json'
$env:AESIR_SCOPE_IDENTITY_BACKEND='development'
$env:AESIR_SCOPE_DEV_PLAYER_ID='11111111-1111-4111-8111-111111111111'
$env:AESIR_SCOPE_DEV_SAVE_IDS='["22222222-2222-4222-8222-222222222222"]'
$env:AESIR_COORDINATION_BACKEND='memory'
$env:AESIR_SCOPE_LEGACY_ENABLED='false'
$env:AESIR_COMPANION_BACKEND='mock'
$env:AESIR_PARSER_BACKEND='rule'
$env:AESIR_INTENT_BACKEND='rule'
$env:AESIR_ASR_BACKEND='mock'
.\.venv\Scripts\python.exe -m scripts.run_server --host 127.0.0.1 --port 18011
```

需要独立数据时，另将 `AESIR_MEMORY_ROOT`、`AESIR_RELATIONSHIP_ROOT` 和信号目录指向隔离目录。真实模型验证按 [LLM 与数据流](_03_llm_integration_guide.md) 配置，将 companion/ASR 后端显式改为所验实现，并检查返回的 `source`；不要在终端或 Issue 中打印 Key。

### SQL/Bearer 启动与恢复

下文第 2 节给出专用空库初始化、最小权限运行账号、玩家/存档授权与私有 token 文件命令。SQL 服务在启动时校验 schema；不匹配可能在开始监听前直接退出，不能把它描述成已提供 HTTP 503 的服务。生产副本还需 Redis、legacy 关闭及独立进程/HTTPS；旧开发数据库路径仅是历史样本，不是当前目标环境配置。

| 路径（均以 `/v1/scoped` 开头） | 使用条件和结果 |
| --- | --- |
| `GET /recovery/state?save_id=…&companion_id=…` | SQL、有效自有 Bearer；返回记忆、关系、epoch、generation 和版本。未初始化返回 `404 STATE_UNKNOWN` |
| `GET /recovery/operations/{request_id}` | 带原 `run_id`、`operation`、存档和 NPC；只返回持久状态/确认版本/原实例等关联，不返回 reply、directive 或可执行 payload |
| `GET /recovery/directives/{directive_id}` | 带原 `run_id`、存档和 NPC；返回历史回执账本与终态，不重新发布 directive |
| `POST /recovery/receipts` | 用稳定回执身份归档原已发布动作；遵守 generation、epoch、版本及原始关联，只归档、不补执行 |
| `GET /sync/state`、`POST /sync/facts` | SQL 的权威同步；沿用稳定事实 ID，按 memory/relationship 分项确认。清记忆后的旧 epoch 首次确认可能为 `skipped_reset`，已确认 duplicate 返回原 ack |
| `GET /requests/{request_id}` | 当前活跃 binding 的状态轮询；SQL 缓存未命中时可查询持久状态/已有结果，但历史 scope 字段不会授权重新执行 |

恢复读取依赖当前 Bearer 的归属/权限，不要求复活旧 run binding。重启后先读恢复确认、获取新 context/bind，再发送新的业务请求；不改旧 ID、不重发旧 POST 来尝试“恢复执行”。JSON 模式对已鉴权的 recovery 请求返回 `404 RECOVERY_UNAVAILABLE`，不能将其误读为凭据无效或存档越权。完整参数看契约和 golden；恢复不是 seq/cursor 增量补拉 API。

### 失败响应对照

相同 HTTP 状态不保证两种模式触发条件相同，应同时判断 `detail.code`。以下以通过 schema 校验的 scoped 请求为前提；字段缺失/格式错误通常为 422，超额可能为 429。

| HTTP | JSON/development | SQL/Bearer |
| --- | --- | --- |
| 401 `IDENTITY_REQUIRED` | 未启用可信身份，或固定玩家/存档配置不完整；传入无效 Bearer 本身不会触发此开发身份检查 | 缺失、无效、过期、撤销凭据或玩家已停用；客户端不能用请求体冒充玩家 |
| 403 `SCOPE_FORBIDDEN` / `PERMISSION_DENIED` | 请求存档不在固定允许集合；开发 principal 有默认权限，不能据此证明数据库分权 | 存档未授权/已撤回，或缺少相应业务/管理权限；提交边界会复核撤回 |
| 409 | 两者均检查 service_instance、run/binding/encounter/epoch、重复 ID 与载荷冲突等生命周期条件 | 除共同条件外，SQL 事务/同步还检查 `STATE_VERSION_CONFLICT`、`SAVE_GENERATION_STALE` 等持久版本屏障 |
| 503 | 状态文件、人格资源、运行服务不可用等；`/sync/*` 因未启用 SQL 返回 `PERSISTENCE_REQUIRED`；上游失败若允许 mock/fallback，可能返回降级成功，必须看 `source` | 也有公共不可用条件；凭据或准入数据库故障为 `AUTH_UNAVAILABLE`，不能将数据库故障当作无效 token。SQL schema 启动失败另看进程日志 |

发布前可执行 `python -m scripts.release_preflight --mode production --json`，有 BLOCK 时退出码为 1。它只检查配置门禁，不联网验证数据库、提供方、证书、备份、容量或 UE。本机 development/json/memory 被阻止用于生产是预期结果；当前可复现证据见 [P1 服务端验证](../records/_05_p1_server_verification.md)。

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

建表前先审查[数据库设计](../design/database/README.md)与[SQL执行规范](../design/database/sql/README.md)：空库可选择保留的初始DDL或下述CLI，两者不重复执行。已有库先用 `scripts.check_database_design --database-url-file <私有文件>` 只读审计；开发库expires_at可空漂移已在备份后受控修复，三个项目库审计均通过，见[本轮证据](../records/_01_verification_records.md#schema-gate-20261022)。运行时 `check_schema()` 现与该审计共享metadata结构检查；样本collation未写进metadata，不硬编码为0900，部署仍须核对大小写语义。

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

完整适用命令、真实进程重启/备份恢复结果及源码哈希见[验证记录](../records/_01_verification_records.md#persist-20261022)。未提供真实库路径时5个MySQL专项明确skip，不能把它们算成MySQL通过。UE仍需实现可信凭据接入、按档缓存、稳定事实/回执队列与分项移除、版本冲突拉取、容量/保留/退避/失败状态、断网本地兜底及SC-011采样。本轮未连接或修改UE，第四步服务端通过不等于全部DEP/EVO或正式多人发布完成。
