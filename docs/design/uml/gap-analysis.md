# As-Is / To-Be 实现差距

> 更新日期：2026-09-12

本文件用于记录当前实现与目标设计之间的差距。未完成内容可以进入 To-Be UML，但不得在 As-Is UML 中表示为已经运行的调用关系。

| Gap ID | 业务目标 | 当前证据 | 当前状态 | UML 表达 |
| --- | --- | --- | --- | --- |
| GAP-BP-001 | 战术订单进入 Alice AI/技能执行 | `BP_AliceCompanion` 已挂载 `TacticalOrder`，但 `EventGraph` 为空 | 未实现或实现在其他资产中，待继续核验 | As-Is 不画实线；To-Be 使用 `<<planned>>` |
| GAP-BP-002 | 玩家端将解析结果交给 `TacticalOrder` | `WBP_CompanionChatTest` 只负责文本聊天；主要玩家 `BP_AesirPlayer_MM_Reference` 已实现 `IA_PushToTalk`、录音和 `ParseVoiceCommand`，但其 187 节点 EventGraph 中未发现 `TryAcceptOrder` | 语音采集和命令解析已接入；战术订单提交仍未核验 | As-Is 画到 `ParseVoiceCommand` 为止；To-Be 的订单提交使用 `<<planned>>` |
| GAP-BP-003 | 行为树读取并执行有效订单 | `BT_Alice`、`BB_Alice`、`BTS_AliceUpdateTarget` 已核验；当前仅实现跟随玩家 | 未实现战术订单、技能选择或施法分支 | As-Is 不画订单执行关系；To-Be 使用 `<<planned>>` |
| GAP-BP-004 | Alice 跟随玩家 Pawn | `BTS_AliceUpdateTarget` 实际把 `GetPlayerController(0)` 写入 `TargetActor` | 当前目标是 PlayerController，而不是 Player Pawn；需运行验证位置语义 | As-Is 按 PlayerController 绘制，不静默改为 Player Pawn |
| GAP-RL-001 | RL 选择 Boss 高层战术 | 当前 `BT_AesirBoss` 是确定性基线：Dead / Stunned / Engage；Engage 固定执行 Move To → Boss Attack → Wait | 尚未发现 RL Policy、Observation、Action 或运行时回退接线 | As-Is 只画确定性 BT；RL 架构进入独立 To-Be 图并标记 `<<planned>>` |
| GAP-UI-001 | 敌人生命条安全计算 | `SetEnemyHealth` 直接执行 `CurrentHealth / MaxHealth` 后 Clamp；玩家 HUD 额外使用 `Max(MaxHealth, 1.0)` 保护分母 | 目前未证明运行时会出现 `MaxHealth <= 0`；属于防御性与一致性风险，不判定为已复现缺陷 | As-Is 保留实际公式；不把玩家 HUD 的保护逻辑套用到敌人 HUD |
| GAP-UI-002 | 战斗结果界面可靠显示 | `BP_AesirGameMode.EventGraph` 中设置 `bShowMouseCursor=true` 的节点导出曾包含 `ErrorType=1`；用户于 2026-09-12 在 UE 编辑器重新 Compile 并确认成功 | 已关闭；旧导出标记不是当前编译阻塞 | As-Is 调用链可保留为已验证；运行演示仍需后续单独验收 |
| GAP-INPUT-001 | 当前 Locomotion Context 装配一致 | 旧 `BP_AesirPlayerController` 截图显示 `IMC_Default + IMC_AesirCombat`；用户于 2026-09-12 确认当前为 `IMC_AesirLocomotion + IMC_AesirCombat`，且已提供 Locomotion 映射截图 | 已关闭；旧截图作为配置变更历史保留 | As-Is 使用当前确认的两个 Context，不再把 `IMC_Default` 画成当前配置 |
| GAP-INPUT-002 | 避免同优先级输入误触发 | Locomotion 与 Combat Context 存在 Space Bar、Gamepad Face Button Bottom 等重叠；Controller C++ 以相同优先级 0 添加默认 Context | 是否同时触发取决于实际 Context 装配、Action 消费与处理逻辑，需 PIE 实测 | UML 保留两个 Context 到玩家的关系；不在没有运行证据时标记为 Bug |

## 建模规则

- `As-Is`：只包含源码、蓝图节点或运行证据能够证明的关系。
- `To-Be`：允许表达后续准备实现的关系，但组件和箭头必须标记 `<<planned>>`。
- `Gap`：每个未实现关系使用稳定的 `GAP-*` 编号连接需求、设计和后续代码提交。
