# 开发与课程文档

服务需求以[NPC需求主文](planning/aesir-agent-sdd-v1.1.md)为当前入口。UE整组Word、关卡和Boss模型在UE仓维护；本仓解释NPC服务和独立Boss RL，不再维护旧游戏全套模型。

## 按问题找资料

| 现在要解决的问题 | 阅读入口 |
| --- | --- |
| 怎样安装、启动、配置端口和实例 | [启动指南](guides/getting-started.md) |
| 哪些 AI 能力在本地或服务器、原计划是否覆盖 | [15 项部署分工对照](planning/ai-capability-placement.md) |
| 服务器远程开发与本地 Boss/云端队友怎样推进 | [六步开发方案](planning/local-boss-cloud-companion-roadmap.md) · [远程开发指南](guides/remote-development.md) |
| 第二步怎样定义玩家/存档归属、游玩身份和有效期 | [第二步实施计划](planning/step-02-identity-scope-plan.md) · [v0.4契约草案](protocols/npc-scope-contract-v0.4-draft.md)（分支实现及服务端回归通过，UE待验） |
| 怎样使用v0.4身份、显式绑定与隔离状态 | [v0.4开发与交接](guides/scoped-development.md) |
| 正式部署、玩家/存档隔离、缓存同步与断网 | [部署指南](guides/deployment.md)，含外部ASR、模型发布及AT-DEP验收 |
| 当前运行版本和后端怎样核对 | [联调复现](guides/repro.md) |
| LLM配置、外发上下文和本地数据保留 | [LLM与数据流](guides/llm-integration.md) |
| 指令在源码中怎样处理 | [命令处理导读](guides/command-execution.md) |
| UE该调用哪个端点、怎样检查结果 | [两端接入对齐](protocols/integration-alignment-v0.3.md) |
| 当前范围、45FR、7UC、规则和验收 | [NPC需求主文](planning/aesir-agent-sdd-v1.1.md) |
| 当前有哪些实现差距或未决规则 | [未决事项与跨仓依赖](planning/todo.md) |
| 对话编排、语音、游戏Agent、记忆和云端服务怎样分批演进 | [交互演进计划](planning/npc-interaction-evolution.md)，含20项UC/FR/DEP映射和AT-EVO验收 |
| 课程要求、真实修订过程和跨仓映射 | [课程索引](planning/course-requirements-index.md) |
| 图源、预览和维护方式 | [UML索引](design/uml/README.md) |
| Boss训练、冻结模型、独立评估边界 | [RL说明](../rl/README.md) |
| 真实测试/联调发生过什么 | [验证记录](logs/verification-records.md) · [里程碑](../CHANGELOG.md) |

## 字段定义看契约

| 契约 | 当前用途 |
| --- | --- |
| [v0.1订单与对话](protocols/ue-protocol-contract-v0.1.md) | 兼容文本/语音订单解析、陪伴对话与流式响应 |
| [v0.2战术决策](protocols/combat-tactical-protocol-v0.2.md) | 战斗快照、上下文决策、战斗事件与执行回执 |
| [v0.3代理入口](protocols/npc-contract-v0.3.md) | 心跳/文本主入口、世界事件、当前端点矩阵及回执兼容边界 |
| [v0.4作用域草案](protocols/npc-scope-contract-v0.4-draft.md) | 身份、生命周期、时效与兼容边界；分支实现及服务端回归见验证记录 |
| [人格包与游戏档案schema](protocols/persona-pack-schema-v0.2.md) | 数据资产格式；它的版本不等于API协议版本 |

这些契约按职责并存，不能仅因编号较旧删除仍使用的协议。指南只维护步骤与说明，字段表链接上述契约；当前接口的交互文档由运行实例的`/docs`提供。

## 维护方式

2026-10-21部署目标以SDD范围条款和部署指南的DEP编号为准；现有本机API、历史测试和课程图保留原覆盖范围。新协议字段、代码与图形/Word实现状态分别登记，其他指南链接规则，不复制平行规范。

同日采纳的`EVO-20261021`交互演进在planning主计划维护D1～C4和AT-EVO-01～10；原45FR/7UC计数不变，TTS/VAD/打断是新增后置扩展流。实施批次在todo引用，规则/字段/验收各有入口，不以计划登记代替实现或图源刷新。

规则、实现状态和验证结果分别登记。参数有代码默认值不等于全体成员已批准；模型能导出不等于人工已接受；HTTP成功不等于UE实际完成行为。

当前图源仅在`design/uml/src`维护一套draw.io文件，由MCP修改后用Desktop导出到`png`。旧长策划、阶段流水账和PlantUML通过Git历史回查，不在本目录另存备份。实际审查与修改摘要见课程索引，历史验证摘要保留日期、环境与结论范围。
