# UML 建模工作区

本工作区使用 PlantUML 描述 Aesir Combat Prototype 的业务域模型。

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
├── evidence/               # 源码与蓝图事实、追踪矩阵
└── src/                    # PlantUML 源文件
```

## 计划中的图

| 编号 | 文件 | 模型 | 状态 |
| --- | --- | --- | --- |
| UML-01 | `01-system-context-as-is.puml` | 系统上下文图 | 已核验 |
| UML-02 | `02-domain-components-as-is.puml` | 业务组件图 | 源码关系已核验，蓝图接线待核验 |
| UML-03 | `03-core-domain-classes-as-is.puml` | 核心领域类图 | 待制作 |
| UML-04 | `04-companion-chat-sequence-as-is.puml` | 陪伴文本聊天时序图 | 已按 Widget、C++ 与 Python 源码核验 |
| UML-05 | `05-combat-sequence-as-is.puml` | 近战攻击时序图 | 待制作 |
| UML-06 | `06-tactical-order-state-as-is.puml` | 战术订单状态图 | 待制作 |
| UML-07 | `07-companion-ai-activity-as-is.puml` | 同伴 AI 活动图 | 已按 BT/BTS/BB 节点文本核验 |
| UML-08 | `08-deployment-as-is.puml` | 部署图 | 待制作 |
| UML-09 | `09-voice-tactical-command-to-be.puml` | 语音战术指令目标时序图 | 待制作（To-Be） |

## 完成判定

一张图只有同时满足以下条件才标记为“已核验”：

- PlantUML 可以无错误渲染；
- 图中每个业务元素在 `evidence/traceability.csv` 中有证据编号；
- C++/Python 关系已通过源码复核；
- 涉及蓝图或行为树的关系已通过编辑器导出数据复核；
- 图中没有把规划功能误写为已接入功能。

## 本地预览与导出

本工作区只维护 `.puml` 源文件，不提交或自动生成 SVG/PNG。预览和导出由文档维护者使用自己的 PlantUML 工具完成。
