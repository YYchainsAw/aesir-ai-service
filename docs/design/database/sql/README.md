# NPC持久化SQL与迁移规范

> 2026-10-22，`database-design-v1`，当前 `schema_version=1`。本目录保留可审查、可复核的MySQL初始DDL和有实际依据的修复SQL。物理规范见[物理模型](../02-physical-model.md)，字段与JSON命名空间见[数据字典](../03-data-dictionary.md)。现有初始化、JSON导入和逻辑备份恢复工具见[持久化开发指南](../../../guides/persistent-development.md)。

## 1. 文件与版本

| 文件 | 目的与适用对象 |
| --- | --- |
| `001-initial-schema.sql` | 从当前SQLAlchemy metadata编译并核对的MySQL v1初始DDL；8次CREATE TABLE，最后登记 `(id=1, version=1)`；只用于已选定的空应用库 |
| `repairs/001-v1-credential-expiry-not-null.sql` | 已存在v1库的特定漂移修复候选；仅修复credentials.expires_at的可空性，带检查步骤；不等于v2迁移，不自动执行 |

目前没有已实现的v2结构，也没有Alembic或其他版本迁移执行器。本目录不制作“成功但不改结构”的占位v2脚本。未来版本确有结构/语义变化时，再新增有前置条件、数据处理与验证证据的增量SQL。

`schema_versions` 是应用读取的兼容版本标记，不是迁移历史表、锁或自动执行器。当前只有应用约定的一行 `id=1`，没有执行人、时间、checksum及逐条迁移记录；仅把version改大，不能证明DDL和数据回填已完成。

## 2. 初始DDL的执行边界

初始脚本不创建数据库、账号或授权，不含USE、DROP或对既有表的ALTER。执行者必须提前选择专用空库，用单独迁移账号连接；运行服务账号仅有DML权限。目标MySQL应符合当前服务支持的8.4及以上非MariaDB检查，并采用本项目经验证的8.4 LTS环境；SQLite不执行本文件。

执行前逐项确认：目标不是现有开发/测试/恢复库；应用连接停写且没有并行初始化；应用表为空且不存在；数据库charset/collation已核对为本次预期；连接凭据在站点根外的私有文件，不把密码或含密DSN粘贴进命令、聊天、Git或日志。

空库初始化有两条等价的结构入口，选择其一：

1. 现有受控CLI：先用 `scripts.persistence_data init` 预览，再显式 `--apply`；内部 `metadata.create_all()` 建表并登记v1。
2. 需要人工审查DDL的交付环境：由迁移账号在已选空库执行 `001-initial-schema.sql`，随后运行只读结构审计和应用 `check_schema()`。

两条路径不能在同一目标上顺次重复执行。SQL有意不使用 `IF NOT EXISTS` 掩盖既有定义，任何重名表应中止；`create_all()` 的存在性判断也不代表既有表结构匹配。脚本与源码规范一致，不承诺MySQL自动生成的外键/索引名称在所有环境相同。

默认值须按字典提供：active、revoked的默认值来自SQLAlchemy客户端，初始SQL不虚构数据库DEFAULT；时间列必须是DOUBLE，不将其改成FLOAT。源码未固定表collation，当前样本继承 `utf8mb4_0900_ai_ci`；部署前明确数据库默认值和标识大小写策略，不能把另一环境的默认值视为已验证。

MySQL DDL不是一个可以整体回滚的普通业务事务。若脚本中途失败，可能已经留下部分表；不要仅靠ROLLBACK或直接重跑声称恢复成功。先保留错误与实际结构，核对目标确为新建隔离库，再按受控处置重建空目标或制定修复；不能针对已有业务库运行破坏性清理。

## 3. 已有v1库与漂移修复

`metadata.create_all()` 只创建缺失表，不修改已存在列、默认值、主外键或索引。当前应用检查覆盖版本、可选取列和DOUBLE列型，不能完全发现结构漂移。已有库必须先只读比较实际元数据与v1规范，再决定是否需要修复；禁止把初始DDL当升级脚本。

本轮发现dev验证库 `access_credentials.expires_at` 为 `DOUBLE NULL`，而当前源码及初始SQL为 `DOUBLE NOT NULL`。`repairs/001-v1-credential-expiry-not-null.sql` 保留这一真实差异的修复步骤：先确认版本和实际列型、统计NULL到期值并核对凭据处置，再安排停止凭据写入的维护窗口，最后才执行受限ALTER与复核。本次文档交付没有对现有dev/test/restore库应用修复。

修复脚本使用带明确名称的临时辅助存储过程，以 `SQL SECURITY INVOKER` 按执行者权限运行；版本、DOUBLE列型或NULL计数不符合前置条件时由SIGNAL阻止ALTER，成功后删除辅助过程。执行账号除目标ALTER外还需本脚本相应的例程权限；业务运行账号不执行。用支持DELIMITER的MySQL客户端执行整份脚本，不使用 `--force` 忽略错误；失败后核对辅助过程是否残留并按脚本说明处置，不能误把客户端继续执行当成功。

若存在NULL凭据，不得猜一个未来到期时间继续放行；先明确撤销/隔离及审计策略，消除无定义到期值后再独立复核。若目标本已NOT NULL，则记录一致性，不重复DDL。修复保持schema版本1，因为它恢复v1已有约束；不能通过标记v2掩盖漂移，也不能未经数据检查直接执行全库重建。

## 4. 后续增量迁移必须包含什么

真正的下一版使用有序编号与内容明确的文件名，例如 `NNN-<change-name>.sql`；编号、变更前后schema版本和适用代码版本在说明中对应。每次变更必须提供以下材料：

| 阶段 | 要求 |
| --- | --- |
| 需求与影响 | 说明触发需求、涉及逻辑实体、原子性/唯一身份/授权边界及新旧版本读写兼容性；同步ER、PDM和数据字典 |
| 前置检查 | 确认MySQL版本、当前schema版本、实际列/索引/FK/collation、数据量、NULL/重复/非法scope等阻断项；不依赖版本号猜结构 |
| 备份与演练 | 对完整8表及新增结构做受控备份，在独立目标演练恢复，记录恢复点、保留与耗时；备份应包含去重及reset/撤销屏障 |
| DDL与回填 | 明确执行顺序、锁表/资源影响、维护窗口；JSON拆表时保留原完整稳定key、原scope、版本与确认身份，回填全量校验，不把同一事实变成新事实 |
| 应用切换 | 默认停写后迁移并升级代码；若未来需要在线expand/contract，必须先实现并测试新旧读写策略，不能只在文档声称支持 |
| 版本更新 | DDL、回填与验证全部成功后，才条件更新 `schema_versions` 到目标版本；代码同步调整SCHEMA_VERSION及检查逻辑 |
| 结果验证 | 比较表/列/类型/nullability/PK/FK/索引/默认/collation；核对行数、哈希、scope、epoch、CAS/确认版本、凭据撤销与quota，不只检查SQL退出码 |
| 回退 | 写清哪些DDL可反向执行、哪些必须从恢复点重建；回退代码与结构成对，保留稳定身份，禁止丢弃迁移后新事实再启用旧库 |

迁移前若已允许新数据写入，单纯切回旧JSON或旧快照会丢失新事实及去重屏障。此时应先停止写入，设计导出/收敛和恢复点策略；恢复默认撤销旧credentials的安全规则继续有效。SQL数据备份不是物理快照/PITR能力的替代说明，正式恢复目标与时限留发布演练。

## 5. 审计与交付验证

从服务器项目根运行离线检查，确认保留DDL与当前metadata一致：

```bash
cd /www/wwwroot/aesir-ai-service
.venv/bin/python -m scripts.check_database_design
```

已有目标只读审计使用私有连接文件；检查命令不建表、不ALTER、不改数据：

```bash
.venv/bin/python -m scripts.check_database_design \
  --database-url-file /etc/aesir-ai/dev/mysql84-dev-runtime.url
```

凭据文件必须受限，报告只保留结构差异，不输出连接串或token。发现差异应使审计失败，并分别记录目标与差异；不能因另一个空库初始化成功而覆盖既有库失败结果。执行初始DDL的验证只在新建隔离空库进行，需另记目标库名、脚本SHA-256、8表/外键/列定义核对及实际结果；本页命令本身不表示验证已通过，真实证据见[验证记录](../../../logs/verification-records.md)。
