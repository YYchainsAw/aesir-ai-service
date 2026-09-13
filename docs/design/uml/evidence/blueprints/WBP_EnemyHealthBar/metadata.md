# WBP_EnemyHealthBar 元数据

- Asset Path: `/Game/Aesir/UI/HealthBars/WBP_EnemyHealthBar`
- Blueprint Type: Widget Blueprint
- Parent Class: 至少继承 `UUserWidget`；直接父类仍需 Class Settings 核验
- Interfaces: 待核验
- 核验日期: 2026-09-12
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## Graph 清单

| Graph 名称 | 类型 | 节点文本文件 | 状态 |
| --- | --- | --- | --- |
| `EventGraph` | Event Graph | `EventGraph.txt` | `EMPTY_GRAPH_VERIFIED` |
| `SetEnemyHealth` | Function | `Functions/SetEnemyHealth.txt` | 5 个节点，已完成节点与 Pin 连线分析 |

## 当前职责

- 本 Widget 自身没有 EventGraph 事件逻辑。
- 外部调用 `SetEnemyHealth(CurrentHealth, MaxHealth)` 更新 `PB_EnemyHealth`。
- 已有 `BP_AesirEnemyCharacter.EventGraph` 证明 BeginPlay 初始化和 `OnHealthChanged` 回调都会调用该函数。
