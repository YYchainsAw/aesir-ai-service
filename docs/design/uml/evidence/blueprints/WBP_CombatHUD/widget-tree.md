# WBP_CombatHUD Widget Tree

| Widget 变量名 | Widget 类型 | Is Variable | 业务用途 | 绑定事件/属性 |
| --- | --- | --- | --- | --- |
| `[Canvas Panel]` | `CanvasPanel` | 不适用（根容器） | HUD 布局根节点 | 截图未显示属性绑定 |
| `PB_PlayerHealth` | `ProgressBar` | 是（Function Graph 有变量引用） | 显示玩家生命值 | `SetPlayerHealth` 调用 `SetPercent` |

## Designer 默认值

- Visibility: 待核验
- Input/Focus 设置: 待核验
- 其他影响业务流程的默认值: 待核验

以上层级来自 2026-09-12 的 Designer Widget Tree 截图；`PB_PlayerHealth` 的变量类型和写入方式由 `SetPlayerHealth` Function Graph 进一步确认。
