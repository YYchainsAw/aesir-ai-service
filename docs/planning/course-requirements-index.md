# 课程需求与建模入口

当前需求主文是 [SDD v1.1](aesir-agent-sdd-v1.1.md)：8 REQ、7 UC、10 BR、5 NFR、12 AT，附原45 FR、8 US映射和13 SC目标。整组完整Word在UE仓维护，不另建服务版整组Word。本轮代码输入为 `a2dd4265a8211d7e221e0d72e2e82864f7af1141`（2026-10-19）；需求工作稿、AI检查、人工接受和运行结果分开。

## 当前资料与维护边界

| 材料 | 用途 |
| --- | --- |
| [SDD v1.1](aesir-agent-sdd-v1.1.md) | 服务需求、异常、对象职责、不变量、UC-07局部BCE、验收与实现差距 |
| [UML索引](../design/uml/README.md) | 4份正式draw.io源、5页Desktop导出；图种/数量按解释需要，不是老师固定数量 |
| [NPC契约v0.3](../protocols/npc-contract-v0.3.md)、[两端对齐](../protocols/integration-alignment-v0.3.md) | 精确接口、兼容及现有门控/幂等/回执差距；当前NPC默认8011，Boss独立8012 |
| [任务入口](todo.md) | 当前任务/跨仓依赖；SDD不再复制历史T001～T088勾选 |
| [Boss RL](../../rl/README.md) | 独立训练、选模、冻结与评估线；不并入NPC Spec范围 |
| [UE UML](../../../../Unreal-Projects/AesirWarden/Docs/UML/README.md)、[整组课程入口](../../../../Unreal-Projects/AesirWarden/Docs/09_Course_Analysis/README.md) | 游戏/整组分析和NPC集成视图；本仓维护服务局部模型，不互复制同义图源 |
| [整组Word](../../../../Unreal-Projects/AesirWarden/Docs/09_Course_Analysis/Word/AesirWarden需求分析文档.docx)、[重试对象分析](../../../../Unreal-Projects/AesirWarden/Docs/09_Course_Analysis/01_RetryObjectAnalysis.md) | 已有G-UC-06候选/CRC/不变量/BCE，可作为整组深入样例复用；不要求每仓/每UC再做一整套 |

来源边界：当前UE整组稿的SRC-07输入是服务`78c7c24`；本次服务输入更新为`a2dd426`，端口等变化是新的跨仓差异，不回写旧来源版本，也不表示UE Word已自动同步。

两端分工沿用：dyh负责Python NPC服务、策略/人格/协议与服务测试；yjx/YYchainsAw负责UE战斗/行为执行/UI/接入及Boss RL；能力ID、事件、golden样例与联调判据共同对齐。游戏里施法/命中/完成必须由UE证据证明，服务返回JSON或202不能代替。

## 需求与整组编号对应

下面是范围对应，不把两仓编号重命名为同一编号。REQ-08是横切需求；US6查证已纳入UC-01步骤，没有另外添加第8个UC。

| 服务REQ | 服务UC | 整组Word/UE对应 | 说明 |
| --- | --- | --- | --- |
| REQ-01 | UC-01 | NPC-FR01；NPC-UC01 | 人格、真实记忆/关系与只读查证 |
| REQ-02 | UC-02 | NPC-FR02/09；NPC-UC02 | 文本建议与实际阶段反馈分开 |
| REQ-03 | UC-03 | NPC-FR03；NPC-UC03 | 语音复用相应文本约束 |
| REQ-04 | UC-04 | NPC-FR04/09；NPC-UC04 | 心跳建议/无动作，不代表UE已经执行 |
| REQ-05 | UC-05 | NPC-FR05/09；NPC-UC05 | 事件反应与有限缓存、UE执行去重分层 |
| REQ-06 | UC-06 | NPC-FR06/09；NPC-UC06 | 当前状态可查；历史解释和执行回执仍有缺口 |
| REQ-07 | UC-07 | NPC-FR07；NPC-UC07 | 清记忆，保人格/关系，长期失败可能部分完成 |
| REQ-08 | 横切UC-01～07 | NPC-FR08；NPC-UC01～07 | 游戏/角色/能力作用域；现回执入口门控不能仅凭目录宣称全覆盖 |

当前服务图：UML-11对应7个UC；UML-12a领域对象与12b对象例共用一份源，旧UML-13映射到12b；UML-14解释UC-07正常/部分失败，UML-15解释建议、UE复核及实际回执。新14/15是局部解释补充，不是老师另定的必交图数。普通行为可无技能，需技能时引用获准能力；数量与目标阶段按UE DEC-03继续待定，另一位负责人协议接受未被本索引代签。

## 本轮真实AI审查与修订

本节是2026-10-19实际审查/修改的汇总，不是过去完整提示记录。用户授权按审查方案整理Docs和draw.io，要求不保留项目备份；没有因此批准全部未决游戏规则。

| 阶段 | 实际材料与动作 | 边界 |
| --- | --- | --- |
| 输入/人工基线 | 原v1.0/v1.1、总策划、13份puml/png、当前schema/源码，及UE COURSE-20261018-R1 | 原人工冻结签署与完整历史提示未找到，不能补造 |
| AI初稿/原模型 | 原UML-11～13直接来自旧Spec；01～10明确为旧CombatPrototype实现/提案 | 历史图不升级为当前AesirWarden执行证据；不另复制备份树 |
| 本轮审查 | 发现必选技能1..*与日常对象例冲突；reset整体回滚/关系销毁误述；解释追踪不足；接口枚举/数据保留/有限幂等/指标代理与现实现差距 | 是AI静态审查和已有真实记录核对，不代替成员/同伴接受 |
| AI修订 | SDD吸收有效章程/45FR/US/SC/分工，修UC异常和状态保证，补CRC不变量及UC07协作；协议/指南按实际schema修正；4主题5页迁draw.io，MCP保存后Desktop同源导出，主要直线/斜直线 | 不新增实现类/新协议阶段，不宣称门控、执行状态机或原子回滚已完成 |
| 自查与接受 | 核对原45FR/13SC逐条保留，稳定REQ/UC/BR/NFR/AT，7UC图覆盖、源/导出和本地链接；人工/同伴模型接受待做 | 语法、文件/版式检查不等于运行验收；本轮未启动服务、UE、训练、真实LLM/ASR或正式采样 |

旧稿、旧图与原修订记录按输入提交[Git树a2dd426](https://github.com/YYchainsAw/aesir-ai-service/tree/a2dd4265a8211d7e221e0d72e2e82864f7af1141/docs)回查：

- 原规格：`docs/planning/aesir-agent-sdd-v1.0.md`、本轮前v1.1；原总策划：`docs/planning/game-design-doc-v0.2.md`。原FR/SC已提取入当前SDD，不再作为现行并列规范。
- 原模型：`docs/design/uml/src/01-*.puml`～`13-*.puml`及`png/`。旧UML-11/12分别由新11/12替代，旧13并入12b；01～10退出现行服务图集。
- 原`baseline.md`、`gap-analysis.md`、`deliverables-plan.md`保留在Git历史；23图/12表旧计划不作为本轮课程要求。

仍须由负责成员完成模型解释/接受，并按实际环境验证角色隔离、语音/对话、事件、UE执行回执、故障及正式性能。旧日期测试、真实LLM样例、E盘临时工程心跳和当前D盘UE完整闭环各有范围，不能相互替代；缺少完整提示/人工或同伴验收的部分继续如实标缺口。
