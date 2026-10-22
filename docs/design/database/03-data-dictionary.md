# NPC持久化数据库数据字典v1

> 2026-10-22，`database-design-v1`。对应[数据库设计索引](README.md)、[逻辑模型](01-requirements-and-logical-model.md)、[物理模型](02-physical-model.md)与[第四步持久化契约](../../protocols/npc-persistence-contract-v0.4.md)。本字典描述当前源码的schema v1；服务器已有库的差异单列记录，不把设计目标当作已整改事实。

## 1. 字段约定

- 物理依据为 `app/persistence/schema.py`、`auth.py`、`journal.py`，共8表44列。`PK1/PK2`表示复合主键中的顺序，`FK`表示数据库实际外键；JSON内的逻辑关联不是物理外键。
- 全部表为InnoDB、utf8mb4。MySQL 8.4.13参考库实际排序规则为 `utf8mb4_0900_ai_ci`；当前metadata只显式指定字符集，没有锁定排序规则。此规则对VARCHAR比较不区分大小写/重音，不能把它解释成二进制ID比较。UUID由应用规范化，哈希使用小写十六进制；游戏标识的大小写规范与未来排序规则调整见物理模型。
- `INTEGER`即MySQL `INT`，SQLAlchemy `BOOL`在MySQL实际为 `TINYINT(1)`，不自带只能取0/1的CHECK。时间列使用UTC Unix秒的 `DOUBLE`，额度窗口起点用整数 `BIGINT`；不要改成精度不足的 `FLOAT`。
- “数据库默认”描述DDL行为；“应用默认/写入”描述Python侧行为。`default=True/False`是SQLAlchemy客户端默认，当前DDL没有相应的 `DEFAULT 1/0`。`NULL（隐式）`仅表示可空列在省略时得到SQL NULL，没有显式server_default；JSON字面量 `null`与SQL NULL不同。
- 除 `schema_versions.id`的隐式整数主键自增外，没有AUTO_INCREMENT、触发器、生成列、额外UNIQUE或CHECK。状态枚举、UUID、哈希长度/格式、JSON结构、非负版本等由应用校验，不能宣称已经由数据库约束保证。
- 存档作用域S为 `(game_id, player_id, save_id)`；NPC作用域N为 `S + (companion_id,)`。控制历史可使用S作为scope，不能假定每个 `scope_parts`都是四段。原逻辑键和scope必须与哈希命中行核对。

## 2. access_players

玩家在游戏下的可信登记。主键 `(game_id, player_id)`；被存档授权及凭据两表引用。停用由应用鉴权检查，不自动删除业务历史。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `game_id` | VARCHAR(100) | 否 | PK1 | 无 | 显式写入 | 游戏命名空间；受安全路径片段与服务游戏配置校验 |
| `player_id` | VARCHAR(36) | 否 | PK2 | 无 | 规范化UUID | 游戏下玩家身份；不由客户端自报即可获信任 |
| `active` | TINYINT(1) / BOOL | 否 | — | 无 | 客户端默认true；登记显式true | 玩家是否启用；false使现有凭据无法继续通过鉴权 |

## 3. access_save_grants

可信玩家对存档的授权，不是完整存档内容表。同一save UUID在不同玩家/游戏下仍属不同S，不声明跨玩家共享存档。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `game_id` | VARCHAR(100) | 否 | PK1；FK1 | 无 | 显式写入 | 与玩家复合外键第一列 |
| `player_id` | VARCHAR(36) | 否 | PK2；FK2 | 无 | 规范化UUID | 与玩家复合外键第二列 |
| `save_id` | VARCHAR(36) | 否 | PK3 | 无 | 规范化UUID | 当前玩家被授权的存档身份 |
| `active` | TINYINT(1) / BOOL | 否 | — | 无 | 客户端默认true；授权操作显式传入 | 授权是否启用；撤销不删除历史状态 |

外键 `(game_id, player_id) → access_players(game_id, player_id)`。MySQL参考名称 `access_save_grants_ibfk_1`，名称由数据库生成；无级联规则，实际默认RESTRICT/NO ACTION语义。复合主键左前缀已覆盖外键查找，无额外二级索引。

## 4. access_credentials

受限运维CLI签发的opaque Bearer凭据。数据库只保存完整token的SHA-256，不保存明文；原始供应商API key不属于本表。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `credential_id` | VARCHAR(36) | 否 | PK | 无 | 新UUID | 凭据公开定位标识；不是秘密 |
| `game_id` | VARCHAR(100) | 否 | FK1；IDX1 | 无 | 显式写入 | 凭据所属游戏 |
| `player_id` | VARCHAR(36) | 否 | FK2；IDX2 | 无 | 规范化UUID | 凭据所属玩家 |
| `secret_hash` | VARCHAR(64) | 否 | — | 无 | SHA-256十六进制 | 完整高熵token的哈希，鉴权恒定时间比对；无UNIQUE约束 |
| `permissions` | VARCHAR(250) | 否 | — | 无 | 去重排序后逗号分隔 | 非空权限集合：npc:use、console:read、memory:reset、docs:read；数据库不校验集合 |
| `created_at` | DOUBLE | 否 | — | 无 | 签发时服务端UTC秒 | 凭据签发时间；没有数据库CURRENT_TIMESTAMP默认 |
| `expires_at` | DOUBLE | 否 | — | 无 | created_at + 有限正TTL | 到期UTC秒；要求NOT NULL，首次dev漂移及后续整改见第11节 |
| `revoked` | TINYINT(1) / BOOL | 否 | — | 无 | 客户端默认false；签发显式false | 是否已撤销；备份恢复操作会保守撤销全部恢复凭据 |

外键 `(game_id, player_id) → access_players(game_id, player_id)`，参考名 `access_credentials_ibfk_1`，无级联。InnoDB自动建立非唯一二级索引 `game_id(game_id, player_id)`支持该FK；它不是源码另写的业务索引。默认TTL为3600秒是CLI/API函数参数行为，不是数据库DEFAULT。

## 5. access_quotas

按游戏/玩家/种类/时间窗口持久计数。额度预留使用独立短事务；取消或业务回滚不返还已预留额度。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `game_id` | VARCHAR(100) | 否 | PK1 | 无 | 显式写入 | 额度所属游戏 |
| `player_id` | VARCHAR(36) | 否 | PK2 | 无 | 规范化UUID | 同玩家跨NPC/session共同计数 |
| `kind` | VARCHAR(20) | 否 | PK3 | 无 | request / upstream | 已准入业务请求窗口或真实上游尝试窗口；应用约束字符串 |
| `window_start` | BIGINT | 否 | PK4 | 无 | 向下取整的UTC窗口起点 | 请求分钟窗口或上游日窗口的Unix整数秒 |
| `used` | INTEGER | 否 | — | 无 | 新窗口1；占位成功后加1 | 已预留次数；额度上限来自配置，不存于本表 |

当前没有到 `access_players`的物理FK，没有二级索引或自动清理机制。不能因两列同名就画成已实施外键，也不能把调用次数额度解释为货币费用预算。

## 6. documents

多个逻辑实体的持久JSON容器。主键 `(namespace, key_hash)`保证同namespace的完整逻辑身份不重复，不保证JSON中任意业务字段唯一。namespace全集、逐类key与payload映射见[逻辑模型](01-requirements-and-logical-model.md)。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `namespace` | VARCHAR(32) | 否 | PK1 | 无 | 小写[a-z][a-z0-9_-]{0,31} | 逻辑文档种类，如memory、relationship、directive；应用正则校验 |
| `key_hash` | VARCHAR(64) | 否 | PK2 | 无 | canonical_parts的SHA-256 | 完整逻辑键的定长索引；并非玩家认证或加密 |
| `key_parts` | JSON | 否 | — | 无 | 字符串数组 | 原完整逻辑键；采用UTF-8、ensure_ascii=false、无多余分隔空格计算哈希，读取须核对 |
| `scope_parts` | JSON | 否 | — | 无 | S或N等作用域字符串数组 | 查询过滤与隔离依据；不是关联到玩家/存档的SQL外键 |
| `payload` | JSON | 否 | — | 无 | JSON对象 | 经对应服务/schema校验的记忆、关系、控制历史、指令关联或确认数据 |
| `version` | BIGINT | 否 | — | 无 | 新建1；更新CAS递增 | 单文档并发版本；删除操作按原版本CAS，不等同于NPC确认版本 |

没有JSON路径索引或物理FK。按namespace列举后在应用中按scope前缀过滤，当前不应宣称已有高效按玩家/存档分页检索。需要审计、归档、容量治理时应按物理模型中的条件评估拆表/投影，不把所有未来数据都继续塞入payload。

## 7. state_versions

一个作用域的已确认状态版本，和 `documents.version`分工不同。主键 `scope_hash`，不存在物理FK。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `scope_hash` | VARCHAR(64) | 否 | PK | 无 | scope字符串元组的SHA-256 | 完整作用域的定长身份 |
| `scope_parts` | JSON | 否 | — | 无 | 原作用域字符串数组 | NPC提交一般为N；控制历史可为S，读取核对原scope |
| `version` | BIGINT | 否 | — | 无 | 首次确认1；提交递增 | UoW最终事务内递增；缺行读取为0是应用行为，不是数据库DEFAULT 0 |

与该UoW的文档及journal完成记录在同事务提交。不是全库流水号，也不能凭较大版本推断UE已经执行动作。

## 8. operation_journal

请求/事件的持久幂等身份及提交结果。主键 `identity_hash`；历史身份不会被TTL自动删除。作用域/版本/原指令均为逻辑关联，没有SQL外键。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `identity_hash` | VARCHAR(64) | 否 | PK | 无 | kind + 完整key的SHA-256 | 包含种类的稳定逻辑身份哈希 |
| `kind` | VARCHAR(16) | 否 | — | 无 | request / event | 幂等账本种类；字符串由应用约束 |
| `key_parts` | JSON | 否 | — | 无 | 完整原逻辑键字符串数组 | 请求含N/run/operation/request_id，事件含N/run/encounter/event_id；具体入口见持久化契约 |
| `scope_parts` | JSON | 否 | — | 无 | 原N | 权威恢复按当前可信存档授权查询，仍核对完整key |
| `request_id` | VARCHAR(100) | 否 | — | 无 | 请求ID或事件ID的字符串 | 原始关联标识；它本身无全局UNIQUE索引 |
| `fingerprint` | VARCHAR(64) | 否 | — | 无 | 规范化载荷指纹 | 相同逻辑ID换内容/binding/epoch冲突；不是原始请求全文 |
| `owner_instance` | VARCHAR(36) | 否 | — | 无 | claim时service_instance UUID | 原负责进程；重启后不得接管未明提交并重做 |
| `state` | VARCHAR(16) | 否 | — | 无 | running / complete / failed / unknown | 应用状态机；cancelled由持久取消墓碑/查询结果表达，不是本表声明的枚举列 |
| `result` | JSON | 是 | — | NULL（隐式） | 完成结果JSON或空 | 可含原回复/协议响应，属于受保护业务数据；恢复查询不返回旧可执行payload |
| `error` | JSON | 是 | — | NULL（隐式） | 已知错误JSON或空 | 已知失败的结构化确认；与无法确认COMMIT的unknown区分 |
| `confirmed_version` | BIGINT | 是 | — | NULL（隐式） | 完成时UoW确认版本 | 未完成claim可为空；不以此推断动作命中/动画完成 |
| `created_at` | DOUBLE | 否 | — | 无 | claim时服务端UTC秒 | 独立短事务建立占位的时间 |
| `finished_at` | DOUBLE | 是 | — | NULL（隐式） | 进入终态时UTC秒 | 尚未结束为空；时间是审计信息，不改变稳定身份 |

LLM等待期间不持有业务长事务。最终结果与业务状态原子提交；原实例遗留running按unknown处理。只有明确安全的历史回执归档确认支持跨实例取回原确认，普通请求不重放旧动作。

## 9. schema_versions

当前schema门禁的单行版本标记，不是已经实施的迁移流水表。

| 列 | MySQL类型 | 可空 | 键/索引 | 数据库默认 | 应用默认/写入 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | INTEGER | 否 | PK；AUTO_INCREMENT | 无固定DEFAULT | 初始化显式1 | SQLAlchemy整数单列PK在MySQL隐式自增；门禁要求唯一id=1，不能依赖自动生成另一个标记 |
| `version` | INTEGER | 否 | — | 无 | SCHEMA_VERSION=1 | 当前版本号；初始SQL最后插入(1,1)，不以存在该行代替完整结构审计 |

当前无“只能一行”“id只能为1”的数据库CHECK；应用共享结构门禁要求版本表恰好只有 `(1, SCHEMA_VERSION)` 一行。`check_schema()`现与离线MySQL审计共享metadata结构检查，不能只凭版本行或启动成功推断业务语义、权限和容量全部通过。

## 10. 全部索引与物理外键

| 表 | 主键顺序 | 二级索引 | 物理外键 |
| --- | --- | --- | --- |
| access_players | game_id, player_id | 无 | 无 |
| access_save_grants | game_id, player_id, save_id | 无，FK复用PK左前缀 | (game_id, player_id) → access_players，同列 |
| access_credentials | credential_id | game_id(game_id, player_id)，非唯一，InnoDB自动建立 | (game_id, player_id) → access_players，同列 |
| access_quotas | game_id, player_id, kind, window_start | 无 | 无 |
| documents | namespace, key_hash | 无 | 无 |
| state_versions | scope_hash | 无 | 无 |
| operation_journal | identity_hash | 无 | 无 |
| schema_versions | id | 无 | 无 |

共8个主键索引、1个二级索引、2条复合外键。FK默认限制删除/更新父键，不级联删除凭据或授权。索引名不是SQLAlchemy显式稳定命名契约，后续迁移不要盲目写死自动生成名。

## 11. 实际库核对与保密边界

2026-10-22首次只读检查发现dev到期列可空性漂移；后续先备份dev，再通过修复SQL前置检查并执行ALTER。下表为本轮修复后的只读核对，未读取或展示凭据值：

| 环境 | access_credentials.expires_at类型 | 可空 | NULL行数 | 版本标记 |
| --- | --- | --- | --- | --- |
| dev84 | DOUBLE | 否，已修复 | 0 | 1 |
| test84 | DOUBLE | 否 | 0 | 1 |
| restore84 | DOUBLE | 否 | 0 | 1 |

dev/test/restore三个库现均通过共享结构审计。整改使用 [v1到期列修复SQL](sql/repairs/001-v1-credential-expiry-not-null.sql)，恢复v1已有NOT NULL约束，未标记为schema v2；test/restore已符合规范，没有重复ALTER。原始差异、私有备份和整改后核对分别保留在[验证记录](../../logs/verification-records.md#schema-gate-20261022)。后续其他实例仍须独立核对前置条件并按[SQL使用说明](sql/README.md)执行，不能借用本表结果。

使用 `python -m scripts.check_database_design`检查保留DDL、数据字典列覆盖和PDM源列/类型/键标记；追加 `--database-url-file <站点根外0600连接文件>`只读核对真实MySQL完整结构。脚本不打印DSN、凭据、payload或请求正文；检测漂移返回非0。具体运行证据见[验证记录](../../logs/verification-records.md)。

记忆、关系、事实确认及journal结果可能含玩家业务信息，不能因“JSON”就当作无敏感性。Bearer明文只允许写新建私有文件，供应商key保持服务端；日志/备份/恢复沿用[运维指南](../../guides/persistent-development.md)权限与撤销规则。配置型persona、游戏能力声明、运行中的session对话历史和实时活动绑定没有在这8表中另建实体表；不得把未落库能力写成已持久化。
