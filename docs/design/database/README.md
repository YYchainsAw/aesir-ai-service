# NPC持久化数据库设计

> 2026-10-22，`database-design-v1`。对应第四步PR #88已合入的源码schema v1；本轮在 `fix/npc-schema-validation` 继续完善结构门禁与既有dev库整改。这是实现后补齐的需求与数据库设计审查，不追记为编码前已完成。规则与接口仍以原需求、部署指南和持久化契约为准，运行结果另记[验证记录](../../logs/verification-records.md#database-design-20261022)。

## 1. 设计范围与阅读顺序

本组材料解释云端队友的身份与存档授权、NPC记忆/关系、稳定操作身份、指令/回执、事实同步和恢复。Boss本地模型、UE世界状态、原始音频和权重不进入本轮业务库。当前仍为单worker；本组图纸不是UE或正式发布验收。

| 需要审查什么 | 阅读入口 |
| --- | --- |
| 原始需求怎样落到实体、身份、关系和聚合 | [需求与逻辑模型](01-requirements-and-logical-model.md)，含需求追踪、17类逻辑实体和10个documents命名空间 |
| 实际有哪8张表、哪些关系是数据库约束 | [物理模型](02-physical-model.md)，含主外键、索引、访问路径与JSON拆表条件 |
| 每列是什么类型、可否为空、怎样赋值 | [数据字典](03-data-dictionary.md)，8表44列；区分数据库默认与Python客户端默认 |
| 怎样初始化、处理已有库漂移和后续升级 | [SQL与迁移规范](sql/README.md)，保留初始DDL与有依据的v1修复SQL |
| 怎样运行、授权、导入和备份恢复 | [持久化开发指南](../../guides/persistent-development.md) |

需求基线为[NPC SDD](../../planning/aesir-agent-sdd-v1.1.md)、[DEP规则](../../guides/deployment.md)及[第四步计划](../../planning/step-04-persistence-access-plan.md)；外部字段与错误见[持久化契约](../../protocols/npc-persistence-contract-v0.4.md)。任务状态继续由[DEP4里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/8)与PR维护，不另复制任务看板。

## 2. 图源与Desktop导出

| 标识 | 内容 | 可编辑源 | Desktop导出 |
| --- | --- | --- | --- |
| ER-01a | 可信主体、存档世代、run/encounter历史与NPC私有状态 | [两页源，第1页](src/01-npc-persistence-er.drawio) | [PNG](png/01a-npc-identity-state.drawio.png) |
| ER-01b | 操作日志、取消墓碑、指令/回执、事实确认及同步身份 | [同源，第2页](src/01-npc-persistence-er.drawio) | [PNG](png/01b-npc-operations-feedback.drawio.png) |
| PDM-02 | 当前MySQL schema v1全部8表44列、2条物理外键与索引说明 | [源](src/02-npc-persistence-pdm.drawio) | [PNG](png/02-npc-persistence-pdm.drawio.png) |

共2份源、3页及3张PNG。ER虚线表示业务逻辑关系，PDM实线才表示实际外键；NPC聚合是逻辑边界，没有独立NPC表，memory/relationship等10类记录当前共用documents。现有[UML领域图](../uml/README.md)继续表达职责与协作，不替代本组ER/PDM。

图源在本地由draw.io MCP的 `list_pages/set_page` 写入，再用draw.io Desktop 32.4.1逐页导出含XML的PNG；源与图一起上传服务器。PNG保留完整可编辑XML，仍按用户要求单独保留 `.drawio`。每次修改源后重新导出同源预览，不单独改图，不另存初稿/备份目录。

![当前MySQL物理模型](png/02-npc-persistence-pdm.drawio.png)

## 3. SQL、版本与实例差异

`sql/001-initial-schema.sql`是从当前SQLAlchemy metadata编译并核对的初始v1结构，只在明确选定的新空库执行。已有库不重跑初始DDL；`schema_versions`不是自动迁移器，`create_all()`不更新已有列。尚无v2结构，不制作空占位迁移。

`sql/repairs/001-v1-credential-expiry-not-null.sql`针对首次设计审查发现的v1漂移：dev库的credentials.expires_at允许NULL，而源码要求DOUBLE NOT NULL。后续推进已先备份dev库，再核对版本、DOUBLE及NULL=0并执行该修复；dev/test/restore三个项目库的只读结构审计现均通过，schema版本仍为1。原始发现与本轮整改分别保留在[验证记录](../../logs/verification-records.md#schema-gate-20261022)，不将当前一致倒写为历史无差异。

metadata是当前实现结构基线，保留SQL由检查器对照，图和字典不得另立一套表。运行时 `check_schema()` 与离线MySQL审计复用 `app/persistence/validation.py` 的结构检查；未声明的collation不硬编码为样本的0900规则，部署仍须明确大小写策略。逻辑模型与物理实现的差异有意保留：通用JSON文档适合当前有界快照，但高增长事实/回执账本、按scope/时间检索和保留治理需按测量结果设计独立表或投影索引，不能把JSON当作无限扩展的默认存储。

## 4. 维护与检查

1. 先修改来源需求或契约，说明实体、身份、原子性和恢复规则的变化。
2. 结构变更同步metadata、schema版本、有序SQL及数据回填/回退说明；v1实例漂移修复与真正版本升级分开。
3. 用draw.io MCP修改对应源页；再用Desktop逐页导出，确认页码、基数、类型、键、可空标记和无文字遮挡。
4. 核对SQL、图、数据字典和实际库；离线检查与只读MySQL审计分开执行，失败必须保留，不能由启动成功替代。
5. 将真实环境、命令、结果与未验范围追加到已有验证记录；私有连接文件、业务payload、token和备份不入Git。

```bash
.venv/bin/python -m scripts.check_database_design
.venv/bin/python -m scripts.check_database_design \
  --database-url-file /etc/aesir-ai/dev/mysql84-test-runtime.url
```

第二条只读检查既有目标；运行账号不因审计获得DDL权限。数据库业务测试、结构审计和图纸目视检查各证明不同事项，完整证据见[本轮记录](../../logs/verification-records.md#database-design-20261022)。
