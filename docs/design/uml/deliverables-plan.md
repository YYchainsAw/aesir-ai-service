# UML 与设计表格交付计划

> 目标：形成一套既能用于课程答辩，又能作为后续开发蓝图持续维护的标准设计资料。
>
> 口径：当前实现使用 **As-Is**；未来实现使用 **To-Be**。二者不得混在同一张图中。

## 1. 建模范围

本项目不追求机械地覆盖 UML 的全部图种，而是选择能解释业务、结构、交互、状态、行为和部署的标准图。

核心 UML 图种：

1. 用例图：说明玩家和系统能完成什么。
2. 组件图：说明业务系统如何拆分、模块如何依赖。
3. 类图：说明核心领域对象、组件、数据结构及关系。
4. 时序图：说明一次业务流程中各对象如何协作。
5. 状态机图：说明对象状态、转换条件和终止条件。
6. 活动图：说明 AI、游戏流程和复杂决策分支。
7. 部署图：说明 UE、Python 服务、数据与端口的运行位置。
8. 包图：仅在源码模块继续扩大后补充，用于说明代码目录和模块依赖。

不建议当前制作：对象图、通信图、定时图、交互概览图、组合结构图、制品图和 UML Profile。这些图对当前答辩和开发指导的新增价值较低。

## 2. 当前图集

| 编号 | 文件 | UML/视图类型 | 口径 | 当前状态 | 主要用途 |
| --- | --- | --- | --- | --- | --- |
| UML-01 | `01-system-context-as-is.puml` | 系统上下文视图（辅助架构图） | As-Is | 已有 | 解释玩家、UE、Python 服务的系统边界 |
| UML-02 | `02-domain-components-as-is.puml` | 组件图 | As-Is | 已有 | 解释当前业务组件与已接入接口 |
| UML-03 | `03-core-domain-classes-as-is.puml` | 类图 | As-Is | 已有 | 解释玩家、敌人、战斗、战术订单和战局对象 |
| UML-04 | `04-companion-chat-sequence-as-is.puml` | 时序图 | As-Is | 已有 | 解释当前文本聊天闭环 |
| UML-05 | `05-combat-sequence-as-is.puml` | 时序图 | As-Is | 已有 | 解释近战攻击、伤害、韧性、死亡与胜利结算 |
| UML-06 | `06-tactical-order-state-as-is.puml` | 状态机图 | As-Is | 已有 | 解释订单接受、替换、复核、完成和取消 |
| UML-07 | `07-companion-ai-activity-as-is.puml` | 活动图 | As-Is | 已有 | 解释 Alice 当前只实现跟随的行为树 |
| UML-08 | `08-deployment-as-is.puml` | 部署图 | As-Is | 已有 | 解释 UE/Python 本地部署及端口差异 |
| UML-09 | `09-voice-tactical-command-to-be.puml` | 时序图 | To-Be | 已有 | 指导语音、上下文决策、本地校验、GAS 和回执接入 |

## 3. 下一批必须补充的图

这些图用于补齐标准 UML 体系，并直接服务后续开发。

| 优先级 | 编号与建议文件 | UML 类型 | 口径 | 必须表达的内容 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| P0（已完成） | `10-player-use-cases-as-is.puml` | 用例图 | As-Is | 移动、攻击、闪避、锁定、文本聊天、语音录制、重开战斗 | 每个用例均能追溯到 C++、输入资产或 Blueprint |
| P0 | `11-combat-state-machine-as-is.puml` | 状态机图 | As-Is | Idle、Combat、Attacking、Evading、HitReact、Stunned、Dead | 转换必须来自 Player、Enemy 和 CombatState 源码，不推测不存在的转换 |
| P0 | `12-match-flow-state-as-is.puml` | 状态机图 | As-Is | 战斗开始、进行中、Victory、Defeat、结果界面、Restart | 与 GameMode 和 WBP_CombatResult 完全一致 |
| P0 | `13-boss-ai-activity-as-is.puml` | 活动图 | As-Is | Dead、Stunned、Engage、Move To、Attack、Wait | 与 BT_AesirBoss、BB_AesirBoss 的实际节点和条件一致 |
| P0 | `14-voice-command-sequence-as-is.puml` | 时序图 | As-Is | Push-to-talk、WAV、`/v1/voice/command`、当前响应广播终点 | 必须停在当前真实终点，不能画成已驱动 Alice 技能 |
| P1 | `15-target-components-to-be.puml` | 组件图 | To-Be | 战术上下文、强类型决策适配器、订单执行器、GAS、反馈、回执 | 所有未实现组件标 `<<planned>>`，成为开发总蓝图 |
| P1 | `16-gas-ability-sequence-to-be.puml` | 时序图 | To-Be | ability_id 映射、GameplayTag、激活合法性、成本、CD、Montage、命中、完成回执 | 能用于指导第一条 Alice 技能垂直切片 |
| P1 | `17-rl-boss-policy-activity-to-be.puml` | 活动图 | To-Be | Observation、策略推理、高层 Action、BT/状态执行、GAS、Fallback | 明确 RL 只选择高层战术，低层动作保持可靠执行 |
| P1 | `18-vertical-slice-game-flow-to-be.puml` | 活动图 | To-Be | 主菜单、新游戏/读取、教程、战斗、Boss、胜负、重试、存档 | 覆盖答辩需要的 10–15 分钟完整流程 |
| P1 | `19-save-checkpoint-sequence-to-be.puml` | 时序图 | To-Be | 保存触发、SaveGame 数据、槽位写入、读取、关卡恢复 | 明确保存哪些状态、不保存哪些瞬时状态 |

## 4. 可在项目扩大后补充的图

| 建议文件 | UML 类型 | 何时需要 |
| --- | --- | --- |
| `20-source-packages-as-is.puml` | 包图 | C++、Blueprint、Python 模块数量继续增加，需要说明代码边界时 |
| `21-combat-event-sequence-to-be.puml` | 时序图 | 接入 `/v1/combat/events` 和事件幂等处理时 |
| `22-rl-runtime-state-machine-to-be.puml` | 状态机图 | RL 模型加载、健康检查、推理、超时和规则回退开始实现时 |
| `23-animation-combat-flow-to-be.puml` | 活动图 | 正式整合 Motion Matching、Montage、Motion Warping 和命中 Notify 时 |

## 5. 必须配套维护的表格

UML 图负责表达关系，表格负责保存精确字段、状态条件和证据。两者不能互相替代。

| 表格编号 | 建议文件 | 内容 | 当前情况 |
| --- | --- | --- | --- |
| TAB-01 | `evidence/traceability.csv` | 证据编号、领域、UML 元素、源码/资产路径、符号或 Graph、NodeGuid、核验状态 | 已建立，继续维护 |
| TAB-02 | `requirements-traceability.md` | 需求 → 用例 → UML → 实现 → 测试的双向追踪 | 待建立 |
| TAB-03 | `domain-glossary.md` | Player、Companion、Boss、Order、Decision、Ability、Encounter 等术语和唯一含义 | 待建立 |
| TAB-04 | `domain-data-dictionary.md` | TacticalOrder、CombatContext、TacticalDecision、Receipt 的字段、类型、范围和权威方 | 待建立 |
| TAB-05 | `interface-contract-matrix.md` | UE 调用方、HTTP 端点、请求/响应类型、端口、超时、错误与回退 | 待建立 |
| TAB-06 | `state-transition-matrix.md` | 每个状态的进入条件、允许事件、退出条件、非法转换和负责人 | 待建立 |
| TAB-07 | `class-responsibility-matrix.md` | 核心类的职责、拥有数据、发出委托、依赖对象和禁止职责 | 待建立 |
| TAB-08 | `blueprint-trace-matrix.md` | UML 消息/关系 → Blueprint 资产 → Graph → NodeGuid → Pin 连线 | 已有分散证据，待汇总 |
| TAB-09 | `gap-analysis.md` | As-Is 与 To-Be 的差距、证据、处理原则和关闭状态 | 已建立，继续维护 |
| TAB-10 | `verification-matrix.md` | UML 场景 → 自动化测试/PIE 步骤 → 预期结果 → 实际结果 → 证据 | 待建立 |
| TAB-11 | `rl-design-matrix.md` | Observation、Action、Reward、终止条件、基线、指标、种子和失败案例 | 开始 RL 前建立 |
| TAB-12 | `evidence/asset-inventory.md` | 第三方资产、来源、许可证、用途和个人贡献边界 | 已建立，继续维护 |

## 6. Blueprint 与 UML 一致性的执行规则

“与 Blueprint 完全一致”不等于把所有蓝图节点都塞进 UML。正确做法是：

1. UML 只画具有业务意义的调用、分支、状态和依赖。
2. UML 中的资产名、类名、函数名、事件名和 Blackboard Key 必须使用项目真实名称。
3. 一条 Blueprint 实线关系必须能在 `blueprint-trace-matrix.md` 中找到对应 Graph、NodeGuid、Pin 和连线。
4. 空 EventGraph 记录为 `EMPTY_GRAPH_VERIFIED`，不能据此补画规划逻辑。
5. 尚未实现的设计只能进入 `to-be.puml`，并使用 `<<planned>>` 或注释明确标记。
6. 临时数值可以记录为配置事实，但不能上升为固定业务规则。
7. Blueprint 更新后，先更新证据和追踪表，再修改 UML。

## 7. 每张图的标准完成条件

一张图只有满足以下条件才能标记为完成：

- 文件名明确标识 `as-is` 或 `to-be`。
- 标题、图种和建模目的清楚。
- 图的范围保持单一，不混入无关系统。
- 每个 As-Is 元素都有证据编号。
- 每条 As-Is 实线关系都能追溯到源码、Blueprint 或行为树。
- To-Be 中所有未实现元素均明确标记。
- 不把第三方框架能力写成个人实现。
- 通过本地 PlantUML 语法检查。
- 原 `.puml` 保存在 `src/`，同名 `.png` 按用户安排保存在 `png/`，脚本变更时同步刷新预览。
- 对应的表格、差距和测试项同步更新。

## 8. 推荐制作顺序

按以下顺序推进，不再继续无边界截图：

1. 补 `10` 用例图，确定系统功能边界。
2. 补 `11`、`12` 状态机图，固定战斗和战局规则。
3. 补 `13` Boss AI 活动图和 `14` 当前语音时序图，完成 As-Is 图集。
4. 建立领域术语表、数据字典、接口矩阵和状态转换矩阵。
5. 补 `15` 目标组件图，作为后续开发总蓝图。
6. 按开发顺序补 `16` GAS、`17` RL、`18` 完整游戏流程、`19` 存档图。
7. 每完成一个功能，使用追踪表把 To-Be 关系迁移到新的 As-Is 版本。

完成上述 P0、P1 图和 TAB-01 至 TAB-10 后，项目就具备一套足以支撑答辩、继续开发和后续作品集说明的标准 UML/设计资料。
