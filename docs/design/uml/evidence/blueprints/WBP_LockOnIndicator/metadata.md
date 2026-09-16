# WBP_LockOnIndicator 元数据

- Asset Path: `/Game/Aesir/UI/Targeting/WBP_LockOnIndicator`
- Blueprint Type: Widget Blueprint
- Parent Class: 至少继承 `UUserWidget`；直接父类仍需 Class Settings 核验
- Interfaces: 待核验
- 核验日期: 2026-09-12
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## Graph 清单

| Graph 名称 | 类型 | 节点文本文件 | 状态 |
| --- | --- | --- | --- |
| `EventGraph` | Event Graph | `EventGraph.txt` | `EMPTY_GRAPH_VERIFIED` |
| 无 | Function/Macro | 不适用 | `NO_ADDITIONAL_GRAPHS_VERIFIED` |

## 当前职责

- Widget 自身没有 EventGraph 行为，当前证据只支持“纯展示控件”定位。
- `BP_AesirEnemyCharacter` 持有 `LockOnIndicator` Widget Component。
- 敌人的 `SetLockOnIndicatorVisible(bVisible)` Blueprint override 直接调用该组件的 `SetVisibility(bVisible)`。
