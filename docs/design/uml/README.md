# NPC服务 UML

当前模型对应[NPC需求主文](../../planning/aesir-agent-sdd-v1.1.md)的7个UC、角色隔离、条件能力引用和重置规则。本轮根据服务`a2dd426`及UE的`COURSE-20261018-R1`重构，属于需求与协作分析，不证明程序或跨端联调已经验收。

2026-10-21按用户后续授权同步DEP/EVO目标：4份源的5页均已由draw.io MCP读取并保存，再用draw.io Desktop 32.4.1逐页导出含XML的PNG。图形已表达认证玩家/存档作用域、外部ASR与后置TTS、记忆来源/重置世代和持久命令协作；这些是完整目标分析；main已有v0.4身份/分区/绑定/epoch及有界内存幂等子集，精确实现与限制见[scoped交接](../../guides/scoped-development.md)。跨重启事务、完整EVO、UE及生产验收仍待完成。整组Word由UE仓本轮同步，最终版本与排版结果以该仓记录为准。

2026-10-22补充：下文图形及“当前”实现说明保留2026-10-21的建模基线；第四步SQL事务、持久确认/回执及恢复已有独立服务端证据，JSON开发后端仍有自身边界，见[持久化指南](../../guides/persistent-development.md)。数据库的实体、8表结构与实际外键另见[ER/PDM及字典](../database/README.md)；本组UML不是数据库物理设计，也未因此重新绘制或视为跨端验收。

## 当前图源与预览

| 标识 | 内容和范围 | 可编辑源 | Desktop导出 |
| --- | --- | --- | --- |
| UML-11 | 保留7UC；外部LLM/ASR及后置可选TTS，认证作用域前置 | [源](src/11-npc-service-use-cases.drawio) | [图](png/11-npc-service-use-cases.drawio.png) |
| UML-12a | 认证作用域、共享人格/私有状态、来源/重置世代、轮次与持久命令/回执 | [源，第1页](src/12-npc-service-domain.drawio) | [图](png/12a-npc-service-domain.drawio.png) |
| UML-12b | 两玩家同名存档/同角色隔离的说明性对象例，保留零技能观察正例；原UML-13并入 | [同源，第2页](src/12-npc-service-domain.drawio) | [图](png/12b-npc-object-example.drawio.png) |
| UML-14 | 归属验证、重置屏障与旧代写入；保留先清会话/长期失败的当前边界 | [源](src/14-memory-reset-sequence.drawio) | [图](png/14-memory-reset-sequence.drawio.png) |
| UML-15 | 持久幂等/回放→UE条件监听/再校验→实际回执/事务确认；明确现协议差距 | [源](src/15-directive-execution-sequence.drawio) | [图](png/15-directive-execution-sequence.drawio.png) |

共4份源、5页。用例、类及对象连线以直线/斜直线为主；时序消息水平、生命线垂直，便于按时间阅读。图源由draw.io MCP写入，本地保存后由draw.io Desktop逐页导出含XML的PNG。源和预览是一套模型的编辑与阅读形式，不另留初稿/备份目录。

主题数为本项目的表达选择，不是老师固定图数。整组已有UE重试用例的深入对象分析，服务重置协作用于解释自身部分失败，不要求每个UC各建一套CRC/BCE。

## 图中的关键边界

- UML-11保留全部7UC；玩家是UC-01～04的目标属主，游戏输入经UE提交。UC-06/07也可由本机调试工具调用，不表示UE已制作对应按钮。本服务局部不重复画玩家到每个HTTP端点的连线。
- UML-12a中普通指令可不引用技能；需要技能时必须引用获准能力，具体数量待定。`0..*`不是施法免校验许可。
- UML-12a的可变记忆/关系归属InteractionScope，共享CompanionProfile只读；拥有者和版本约束见BR-DEP-01/02/06。memory/reset清相应会话与长期记忆，保留人格、关系和信号/回执日志；普通关联不推导自动级联销毁。
- 对象实例是说明性样例，未声称从运行快照取得。动作类别由统一信封和actionType区分，不冒称实现已创建五种实体子类。
- ExecutionReceipt对应真实反馈；当前回执模型仍有v0.2字段，directiveId与orderId的跨版本追踪未全面对齐。图中的事实依赖不证明已有完整历史检索或执行状态机。
- UML-14中的职责不要求逐个新增Python类。现有reset_memory可以承担边界和协调职责，失败不承诺跨存储原子回滚。
- UML-15明确accepted不等于完成，当前服务只追加JSONL。启动/命中/完成的阶段目标仍需跨端协议对齐，不能把新增阶段写成当前schema枚举。

## 交互演进待同步范围

`EVO-20261021`已采纳的20项增量及AT-EVO见[主计划](../../planning/npc-interaction-evolution.md)。本节标题保留以兼容既有锚点；以下范围已于2026-10-21完成MCP源页保存、Desktop同源导出和逐页AI目视检查，不代表成员模型接受或实现验收。语音/部署补充图统一由UE维护，不新增第8个用户目标型UC。

| 当前源页 | 最小修改 | 用例/演进依据 |
| --- | --- | --- |
| UML-11 服务用例 | 已同步：外部ASR、后置可选TTS与认证前置，保留7UC；不将VAD/数据库画成用户 | UC-01/03；V1～V4、C1；DEP-REQ-04 |
| UML-12a 领域对象 | 已同步：作用域、共享人格/私有状态、轮次、来源/版本/重置世代、命令及实际回执；多重性与条件能力仍明确 | 横切UC；D1/D3、G4、M2～M4、C1～C3 |
| UML-12b 对象实例 | 已同步：玩家A/B复用同一Alice人格和同名存档，但拥有独立记忆；A的普通observe可零技能，反例和reset范围保持 | UC-01/04；G3、M2、C1 |
| UML-14 记忆重置协作 | 已同步目标：认证、屏障提交、缓存清理与旧代写入拒绝；实际清理失败仍报告部分状态，不承诺现行原子回滚 | UC-07；M4/C3、BR-DEP-06、AT-EVO-08 |
| UML-15 指令与回执协作 | 已同步目标：同键同内容回放后结束、同键异内容冲突、首次持久化、UE条件监听、真实回执和事务确认；保留现枚举与目标阶段差异 | UC-02/04/05/06；D2、G3/G4、C2/C3、AT-EVO-07/09 |

完整部署与语音生命周期由UE仓的A11部署图 `Docs/UML/src/11_AIDeployment.drawio` 和A12输入/播放两页 `Docs/UML/src/12_NPCVoiceLifecycle.drawio`维护。A12a解释按键/最终转写与取消，A12b解释确认文本合成、有序播放和打断；生成、播放和动作结果分开。本仓不复制同义源，Word回填与运行验证各自登记。

## 历史图与来源

旧UML-01～10属于Aesir Combat Prototype的实现参考或旧提案，退出当前服务图集；旧11/12/13是本轮修订输入。历史原源、预览和旧需求稿均由Git提交`a2dd426`回查，不复制到项目内。

- [旧图索引](https://github.com/YYchainsAw/aesir-ai-service/blob/a2dd4265a8211d7e221e0d72e2e82864f7af1141/docs/design/uml/README.md)
- [旧需求稿及待核对记录](https://github.com/YYchainsAw/aesir-ai-service/blob/a2dd4265a8211d7e221e0d72e2e82864f7af1141/docs/planning/aesir-agent-sdd-v1.1.md)

真实审查问题、修改与尚缺的人工/同伴接受记录见[课程索引](../../planning/course-requirements-index.md)。Git旧稿不是完整调用提示；不补造历史输入、签名或已通过结论。

## 后续怎样修改

1. 先修改规则或协议，标明需求目标与当前实现差距；同步UC、BR、追踪及未决事项。
2. 用draw.io MCP修改对应源页并确认本地保存；UML-12有两页，不用单页导出覆盖另一页。
3. 用draw.io Desktop从该源页导出PNG并嵌入XML，保留当前源；不单独编辑预览。
4. 检查全部UC、关系两端多重性、条件、消息阶段、异常出口、字体和遮挡，再核对PNG与源同页。
5. 将真实发现和修改写入已有课程记录；运行结果写验证记录。只新增发生过的证据，不生成脚本/日志/备份树。
