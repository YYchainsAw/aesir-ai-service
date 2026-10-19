# NPC服务 UML

当前模型对应[NPC需求主文](../../planning/aesir-agent-sdd-v1.1.md)的7个UC、角色隔离、条件能力引用和重置规则。本轮根据服务`a2dd426`及UE的`COURSE-20261018-R1`重构，属于需求与协作分析，不证明程序或跨端联调已经验收。

## 当前图源与预览

| 标识 | 内容和范围 | 可编辑源 | Desktop导出 |
| --- | --- | --- | --- |
| UML-11 | UC-01～07服务用例；游戏/调试客户端为直接调用方，LLM为可选协作方 | [源](src/11-npc-service-use-cases.drawio) | [图](png/11-npc-service-use-cases.drawio.png) |
| UML-12a | 领域身份、职责、多重性、条件能力及事实追踪 | [源，第1页](src/12-npc-service-domain.drawio) | [图](png/12a-npc-service-domain.drawio.png) |
| UML-12b | 日常指令零技能的对象正例及规则反例；原UML-13并入 | [同源，第2页](src/12-npc-service-domain.drawio) | [图](png/12b-npc-object-example.drawio.png) |
| UML-14 | UC-07边界/控制/实体协作；会话已清、长期清理失败的部分结果 | [源](src/14-memory-reset-sequence.drawio) | [图](png/14-memory-reset-sequence.drawio.png) |
| UML-15 | 建议→UE校验/去重→实际执行→真实回执；明确当前协议差距 | [源](src/15-directive-execution-sequence.drawio) | [图](png/15-directive-execution-sequence.drawio.png) |

共4份源、5页。用例、类及对象连线以直线/斜直线为主；时序消息水平、生命线垂直，便于按时间阅读。图源由draw.io MCP写入，本地保存后由draw.io Desktop逐页导出含XML的PNG。源和预览是一套模型的编辑与阅读形式，不另留初稿/备份目录。

主题数为本项目的表达选择，不是老师固定图数。整组已有UE重试用例的深入对象分析，服务重置协作用于解释自身部分失败，不要求每个UC各建一套CRC/BCE。

## 图中的关键边界

- UML-11保留全部7UC；玩家是UC-01～04的目标属主，游戏输入经UE提交。UC-06/07也可由本机调试工具调用，不表示UE已制作对应按钮。本服务局部不重复画玩家到每个HTTP端点的连线。
- UML-12a中普通指令可不引用技能；需要技能时必须引用获准能力，具体数量待定。`0..*`不是施法免校验许可。
- 记忆与关系按游戏/角色隔离。memory/reset清会话与长期记忆，保留人格、关系和信号/回执日志；普通关联不推导自动级联销毁。
- 对象实例是说明性样例，未声称从运行快照取得。动作类别由统一信封和actionType区分，不冒称实现已创建五种实体子类。
- ExecutionReceipt对应真实反馈；当前回执模型仍有v0.2字段，directiveId与orderId的跨版本追踪未全面对齐。图中的事实依赖不证明已有完整历史检索或执行状态机。
- UML-14中的职责不要求逐个新增Python类。现有reset_memory可以承担边界和协调职责，失败不承诺跨存储原子回滚。
- UML-15明确accepted不等于完成，当前服务只追加JSONL。启动/命中/完成的阶段目标仍需跨端协议对齐，不能把新增阶段写成当前schema枚举。

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
