# WBP_CombatResult 元数据

- Asset Path: `/Game/Aesir/UI/Results/WBP_CombatResult`
- Blueprint Type: Widget Blueprint
- Parent Class: 至少继承 `UUserWidget`；直接父类仍需 Class Settings 核验
- Interfaces: 待核验
- EventGraph 节点数: 9
- 核验日期: 2026-09-12
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## Graph 清单

| Graph 名称 | 类型 | 节点文本文件 | 状态 |
| --- | --- | --- | --- |
| `EventGraph` | Event Graph | `EventGraph.txt` | 9 个节点，已完成节点与 Pin 连线分析 |
| `SetCombatResult` | Function | `Functions/SetCombatResult.txt` | 6 个节点，已完成节点与 Pin 连线分析 |

## 当前职责

- `SetCombatResult(EAesirMatchResult)` 将 `TXT_Result` 设置为结果文本。
- `BTN_Restart.OnClicked` 恢复游戏、切回 Game Only 输入、隐藏鼠标，然后重载 `L_AesirCombatTest`。
- `PreConstruct`、`Construct` 与 `Tick` 均 Disabled 且没有业务连线。
