# WBP_CombatHUD 元数据

- Asset Path: `/Game/Aesir/UI/HealthBars/WBP_CombatHUD`
- Blueprint Type: Widget Blueprint
- Parent Class: 至少继承 `UUserWidget`；直接父类仍需 Class Settings 核验
- Interfaces: 待核验
- EventGraph 节点数: 12
- 核验日期: 2026-09-12
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## Graph 清单

| Graph 名称 | 类型 | 节点文本文件 | 状态 |
| --- | --- | --- | --- |
| `EventGraph` | Event Graph | `EventGraph.txt` | 已完成节点与 Pin 连线分析 |
| `SetPlayerHealth` | Function | `Functions/SetPlayerHealth.txt` | 已完成节点与 Pin 连线分析 |

## EventGraph 当前职责

- `Construct` 时获取 Owning Player Pawn，并转换为 `AAesirPlayerCharacter`。
- 从玩家读取 `HealthComponent`，绑定其 `OnHealthChanged` 委托。
- 委托绑定后读取当前生命与最大生命，调用 `SetPlayerHealth` 初始化 HUD。
- `OnHealthChanged_Event` 收到生命变化后再次调用 `SetPlayerHealth`。
- `PreConstruct` 与 `Tick` 均为 Disabled 且没有业务连线。

`SetPlayerHealth` 已核验为：`Clamp(CurrentHealth / Max(MaxHealth, 1.0), 0.0, 1.0)`，随后写入 `PB_PlayerHealth.SetPercent`。
