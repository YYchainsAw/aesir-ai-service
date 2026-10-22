# 第四步：持久化、访问控制与恢复实施计划

> 2026-10-22，`persistence-plan-v1`。第三步PR #81已合入 `main@15f1672`；第四步基础实现及数据库设计由PR #88合入 `main@eea7532`。用户授权继续推进，当前后续分支为 `fix/npc-schema-validation`。本页维护范围、依赖与验收定义，运行结果另记[验证记录](../logs/verification-records.md)。

主线以[六步方案](local-boss-cloud-companion-roadmap.md)为准，需求映射为DEP-REQ-02/03/06/07、BR-DEP-01/02/03/04/06及EVO-01生产余项/EVO-03同步子集。工作状态由[DEP4里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/8)维护；基础工作包[#82](https://github.com/YYchainsAw/aesir-ai-service/issues/82)～[#87](https://github.com/YYchainsAw/aesir-ai-service/issues/87)已随PR #88完成，结构门禁与既有库整改后续由[#89](https://github.com/YYchainsAw/aesir-ai-service/issues/89)维护，不复制任务勾选。新字段见[持久化增量契约](../protocols/npc-persistence-contract-v0.4.md)。

数据库设计补充见[ER/PDM与SQL索引](../design/database/README.md)，含需求映射、8表44列字典、初始DDL、v1实例漂移修复及后续迁移规范。本组为实现后补齐审查，不追记为先于编码。首次发现的dev库到期列可空性漂移已在备份后受控修复，dev/test/restore只读结构审计均通过；运行时与离线审计现共用metadata结构门禁，完整运行验收仍不能由schema版本或启动成功替代。证据见[本轮记录](../logs/verification-records.md#schema-gate-20261022)。

## 1. 目标与边界

| 目标 | 本步范围 |
| --- | --- |
| 数据库权威状态 | 完整NPC作用域的记忆/关系/epoch、确认版本、请求/事件身份、指令及回执在MySQL事务中提交；JSON保留为隔离开发后端与迁移输入 |
| 可信主体 | 服务端CLI签发随机Bearer，数据库仅存哈希、权限、到期与撤销；数据库存档授权，管理读取/重置分权；不制作通用注册登录产品 |
| 去重与恢复 | 持久逻辑身份不因重启/新binding/epoch变成新请求；未知提交不自动重做；历史确认查询不返回可执行payload |
| 离线真实事实 | 只归档已有目录中的事实与已发布指令的回执；版本/存档世代/原run/encounter/epoch核对，关系与记忆分项确认；不补执行旧命令 |
| 迁移与运维 | 归属明确的scoped JSON预检、默认dry-run、原文件不改；私有备份/空库恢复；迁移与运行账号分离 |
| 验证 | SQLite隔离回归、真实MySQL事务/权限、子进程重启及备份恢复分别留证；不替代UE/HTTPS/容量验收 |

仍为单worker。UE修改、连接与本地队列制作继续后置；本步交付服务端同步及接入要求，不能写成游戏离线恢复已通过。外部ASR、VAD/TTS/播放打断、Boss发行及第六步正式网络发布不在本次实现。既有原文日志保留边界不因SQL或元数据追踪自动改变。

## 2. 技术与隔离决策

沿用FastAPI/Pydantic，新增SQLAlchemy Core 2.1.6与PyMySQL 1.2.3（RSA认证依赖由 `PyMySQL[rsa]` 安装）。正式目标选择MySQL 8.4 LTS，本轮独立验证为8.4.13；LTS策略参见[MySQL官方发布模型](https://dev.mysql.com/doc/refman/8.4/en/mysql-releases.html)。SQLite仅显式测试开关下用于临时文件测试，不是MySQL故障回退。

服务器现有MySQL 5.7和其他业务不升级、不复用其账号或库。本轮独立容器 `aesir-ai-dev-mysql84` 只绑定 `127.0.0.1:13306`，限制640MiB和0.75CPU，数据在 `/var/lib/aesir-ai-dev/mysql84`，私有连接文件在 `/etc/aesir-ai/dev`；不将数据库数据或凭据放入站点根。工程默认仍为JSON，开发`.env`不自动切换。资源上限不是并发承诺，正式服务用户、自动守护、HTTPS与容量留第六步。

## 3. 工作包

| 工作包 | 交付与验收重点 |
| --- | --- |
| DEP4-01 / #82 | SQL连接/schema检查、文档CAS、短事务UoW；记忆/关系/epoch/业务结果一起提交，回滚不泄漏缓存 |
| DEP4-02 / #83 | 正式Bearer、存档权限、console/reset分权、最终授权复核与持久调用额度 |
| DEP4-03 / #84 | 请求/事件claim、持久结果/UNKNOWN、数据库回执账本与历史确认读取 |
| DEP4-04 / #85 | 真实事实与历史回执同步、共同稳定身份、版本冲突和重置分项屏障 |
| DEP4-05 / #86 | 显式schema初始化、scoped JSON导入、私有备份/空目标恢复、独立数据库及最小权限 |
| DEP4-06 / #87 | strict模型/golden、适用核心回归、实际MySQL与进程重启证据、运维及UE交接 |

## 4. 提交与故障语义

请求先用短事务占有稳定逻辑ID，随后释放连接。业务生成阶段只做短读取与请求本地暂存；最终在原runtime→NPC→取消token屏障后，用短数据库事务同时采纳文档CAS、NPC确认版本、事件/指令/回执与请求结果。此提交必须发生在同会话FIFO放行前。事务用法参考[SQLAlchemy Core官方文档](https://docs.sqlalchemy.org/en/21/core/connections.html)。

SQL模式的记忆/关系对象不使用可泄漏暂存值的全局缓存；会话历史仍遵守短期策略，只在持久提交后加入进程历史，重启不恢复原文会话。诊断JSONL在提交后best-effort写入，数据库回执才是确认权威。已发上游调用额度独立预留，不随业务rollback返还。

事务失败无已提交业务效果；连接在COMMIT附近丢失或最终提交后检查失败则保守UNKNOWN，保持稳定身份占位而不重做。重启仍生成新service_instance，旧绑定保持无效；历史请求结果只通过恢复接口读确认/原关联，不给旧动作新的时钟。数据库不自动TTL删除逻辑身份；清理策略启用前另定，不通过遗忘UNKNOWN释放执行资格。

schema初始化是显式CLI操作，仅无任何表的专用空库允许DDL；非空目标先完整只读核对，符合v1时幂等返回，缺表或漂移时拒绝自动补建。运行时在SQL启动及首次获取数据库连接时使用同一metadata结构门禁，通过后缓存连接。MySQL DDL存在[隐式提交](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html)，不将 `create_all` 当通用升级/DDL自动回滚工具。版本或结构不符时拒绝业务，后续变更需要版本化迁移与备份；运行账号无DDL权限。

## 5. 服务端验收

| 编号 | 通过条件 |
| --- | --- |
| AT-PERSIST-01 | 至少两玩家/两档同NPC隔离，凭据由服务器验证；缺失/错误/过期/撤销拒绝，数据库失败不退回开发身份 |
| AT-PERSIST-02 | 普通业务凭据无console/reset权限；Bearer无legacy旁路，文档需管理读取；长生成中撤销/撤回存档后无最终写入 |
| AT-PERSIST-03 | 同事务的记忆/关系/epoch/版本/指令/回执/结果任一阶段故障均无部分业务状态；会话/缓存不泄漏回滚数据 |
| AT-PERSIST-04 | 确认丢失、进程重启、运行中断和跨保留窗口后同ID不再次应用；旧binding仍拒绝，UNKNOWN不自动抢占 |
| AT-PERSIST-05 | 历史恢复只返回自身快照/确认/原关联，无payload/有效期刷新；新binding不得把旧动作变新动作 |
| AT-PERSIST-06 | 实时/离线同稳定事实或回执不双计；同ID异语义冲突，原run/encounter和游戏目录核验，批内失败不部分应用 |
| AT-PERSIST-07 | 版本冲突拉权威状态；清记忆后旧epoch事实明确跳过记忆但关系独立确认；重复旧事实不重复加分，历史回执不恢复记忆 |
| AT-PERSIST-08 | 请求/上游额度按game/player隔离，预留并发正确；缓存重试不重复调用供应商，取消不返还已发调用额度 |
| AT-PERSIST-09 | 导入默认dry-run，归属不明legacy排除；全批验证、源SHA、冲突不覆盖且原JSON不改 |
| AT-PERSIST-10 | 私有备份覆盖schema/epoch/确认/授权撤销；空目标恢复校验计数与哈希，恢复后旧事实仍不再应用 |
| AT-PERSIST-11 | 实际MySQL版本/DOUBLE时间列/InnoDB及运行账号DML权限正确，无DDL或服务器系统库权限；现有5.7未变更 |
| AT-PERSIST-12 | 新模型/golden、适用核心与实际MySQL/重启命令留证；不把SQLite、TestClient或mock写成UE、真实模型或生产容量通过 |

第六步开放发布前仍需受限运行账号的OS隔离、Nginx HTTPS与传输频率门禁、备份调度/保留、费用预算及真实负载/故障演练。多worker、任意跨设备/分支存档合并、通用账号门户均不由本步默认启用。
