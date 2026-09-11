# As-Is / To-Be 实现差距

> 更新日期：2026-09-11

本文件用于记录当前实现与目标设计之间的差距。未完成内容可以进入 To-Be UML，但不得在 As-Is UML 中表示为已经运行的调用关系。

| Gap ID | 业务目标 | 当前证据 | 当前状态 | UML 表达 |
| --- | --- | --- | --- | --- |
| GAP-BP-001 | 战术订单进入 Alice AI/技能执行 | `BP_AliceCompanion` 已挂载 `TacticalOrder`，但 `EventGraph` 为空 | 未实现或实现在其他资产中，待继续核验 | As-Is 不画实线；To-Be 使用 `<<planned>>` |
| GAP-BP-002 | UI 将解析结果交给 `TacticalOrder` | `WBP_CompanionChatTest.EventGraph` 的 34 个节点已分析；当前只调用 `UCompanionChatSubsystem.SendChatMessage` | 当前 Widget 未实现语音、命令解析、战术决策或订单提交 | As-Is 只画聊天；To-Be 使用 `<<planned>>` |
| GAP-BP-003 | 行为树读取并执行有效订单 | `BT_Alice`、`BB_Alice`、`BTS_AliceUpdateTarget` 已核验；当前仅实现跟随玩家 | 未实现战术订单、技能选择或施法分支 | As-Is 不画订单执行关系；To-Be 使用 `<<planned>>` |
| GAP-BP-004 | Alice 跟随玩家 Pawn | `BTS_AliceUpdateTarget` 实际把 `GetPlayerController(0)` 写入 `TargetActor` | 当前目标是 PlayerController，而不是 Player Pawn；需运行验证位置语义 | As-Is 按 PlayerController 绘制，不静默改为 Player Pawn |

## 建模规则

- `As-Is`：只包含源码、蓝图节点或运行证据能够证明的关系。
- `To-Be`：允许表达后续准备实现的关系，但组件和箭头必须标记 `<<planned>>`。
- `Gap`：每个未实现关系使用稳定的 `GAP-*` 编号连接需求、设计和后续代码提交。
