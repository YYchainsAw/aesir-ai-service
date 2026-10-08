# UML 建模工作区

本工作区保存旧 Aesir Combat Prototype 的实现模型，以及 NPC Spec v1.1 的独立需求模型。UML-01～10 保留旧工程基线；UML-11～13 面向 NPC 服务需求，不把旧工程的 As-Is 结论迁移到 AesirWarden。

完整的图表范围、优先级和完成标准见 `deliverables-plan.md`。

建模原则：

1. 先描述当前代码和蓝图真实存在的 **As-Is** 模型，再单独描述规划中的 **To-Be** 模型。
2. UML 保持业务域精简，不展开 Unreal Engine 通用框架类和无业务意义的蓝图辅助节点。
3. UML 中的类、参与者、调用和状态必须能在证据文件中追溯到文档、C++、Python、蓝图或行为树。
4. 蓝图关系只有在导出 Graph、Node GUID、Pin 和连线后才能标记为“已核验”。
5. 策划文档描述目标，不能单独作为“已经实现”的证据。

## 目录

```text
UML/
├── baseline.md             # 仓库、工具链和口径基线
├── gap-analysis.md         # 当前实现与目标设计的差距
├── src/                    # PlantUML 权威源文件
└── png/          # 用户安排的 PNG 预览目录
```

## 计划中的图

| 编号 | 图源 | PNG 预览 | 模型 | 状态 |
| --- | --- | --- | --- | --- |
| UML-01 | [01-system-context-as-is.puml](src/01-system-context-as-is.puml) | [预览](png/01-system-context-as-is.png) | 系统上下文图 | 已核验 |
| UML-02 | [02-domain-components-as-is.puml](src/02-domain-components-as-is.puml) | [预览](png/02-domain-components-as-is.png) | 业务组件图 | 源码关系已核验，蓝图接线待核验 |
| UML-03 | [03-core-domain-classes-as-is.puml](src/03-core-domain-classes-as-is.puml) | [预览](png/03-core-domain-classes-as-is.png) | 核心领域类图 | 已按 C++ 与 Blueprint 证据核验 |
| UML-04 | [04-companion-chat-sequence-as-is.puml](src/04-companion-chat-sequence-as-is.puml) | [预览](png/04-companion-chat-sequence-as-is.png) | 陪伴文本聊天时序图 | 已按 Widget、C++ 与 Python 源码核验 |
| UML-05 | [05-combat-sequence-as-is.puml](src/05-combat-sequence-as-is.puml) | [预览](png/05-combat-sequence-as-is.png) | 近战攻击时序图 | 已按 C++、输入与 UI 证据核验 |
| UML-06 | [06-tactical-order-state-as-is.puml](src/06-tactical-order-state-as-is.puml) | [预览](png/06-tactical-order-state-as-is.png) | 战术订单状态图 | 已按 C++ 与 Alice Blueprint 证据核验 |
| UML-07 | [07-companion-ai-activity-as-is.puml](src/07-companion-ai-activity-as-is.puml) | [预览](png/07-companion-ai-activity-as-is.png) | 同伴 AI 活动图 | 已按 BT/BTS/BB 节点文本核验 |
| UML-08 | [08-deployment-as-is.puml](src/08-deployment-as-is.puml) | [预览](png/08-deployment-as-is.png) | 部署图 | 已按 UE/Python 源码与启动配置核验 |
| UML-09 | [09-voice-tactical-command-to-be.puml](src/09-voice-tactical-command-to-be.puml) | [预览](png/09-voice-tactical-command-to-be.png) | 语音战术指令目标时序图 | 已制作（To-Be，未实现步骤均显式标记） |
| UML-10 | [10-player-use-cases-as-is.puml](src/10-player-use-cases-as-is.puml) | [预览](png/10-player-use-cases-as-is.png) | 玩家功能用例图 | 已按 C++、输入、Blueprint 与 Python 接口证据核验 |
| UML-11 | [11-npc-agent-use-cases-to-be.puml](src/11-npc-agent-use-cases-to-be.puml) | [预览](png/11-npc-agent-use-cases-to-be.png) | NPC Spec v1.1 用例图 | 2026-10-08 从规格提取；需求目标，非 UE 联调通过证据 |
| UML-12 | [12-npc-agent-analysis-classes-to-be.puml](src/12-npc-agent-analysis-classes-to-be.puml) | [预览](png/12-npc-agent-analysis-classes-to-be.png) | NPC Spec v1.1 分析类图 | 2026-10-08 从规格提取；关系重置/能力关联假设待再核对 |
| UML-13 | [13-npc-agent-object-example-to-be.puml](src/13-npc-agent-object-example-to-be.puml) | [预览](png/13-npc-agent-object-example-to-be.png) | NPC Spec v1.1 对象图正例 | 2026-10-08 从规格提取；文档示例，不是实测快照 |

UML-11～13 的权威图源仅在 `src/` 维护；[Spec v1.1](../../planning/aesir-agent-sdd-v1.1.md)引用脚本，不再保留重复内嵌副本。对应课程材料见 [提交资料索引](../../planning/course-requirements-index.md)。需求模型的核对依据为 REQ/UC/BR 与文档来源；上表“已核验”属于旧实现模型的既有记录，不能据此提升新需求模型的运行状态。

## 完成判定

一张图只有同时满足以下条件才标记为“已核验”：

- PlantUML 可以无错误渲染；
- 核对图中业务元素的源码或资产来源；原本地 `evidence/` 目录已由用户删除，不恢复旧证据副本；
- C++/Python 关系已通过源码复核；
- 涉及蓝图或行为树的关系已通过编辑器导出数据复核；
- 图中没有把规划功能误写为已接入功能。

## 本地预览与导出

2026-10-08 用户将 13 张 PNG 移到 `png/`，原 `.puml` 保留在 `src/`；按这一安排维护，不将预览移回源目录。例如 `src/11-npc-agent-use-cases-to-be.puml` 对应 `png/11-npc-agent-use-cases-to-be.png`。PNG 从对应原脚本生成；修改脚本后同步导出。文件名仍按脚本确定，不使用 `@startuml` 中不同的内部名称。

本次全部原脚本保持不变，仅补齐预览并同步目录引用。UML-01～10 的历史模型状态与 UML-11～13 的需求假设继续按各自基线解释，渲染成功不新增服务或 UE 运行通过结论。UE 的 SRS 目录已由用户删除，不再生成 NPC 素材副本或课程 ZIP；模型直接在本仓库维护。
