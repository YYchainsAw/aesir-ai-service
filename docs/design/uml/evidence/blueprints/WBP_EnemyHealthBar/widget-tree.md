# WBP_EnemyHealthBar Widget Tree

| Widget 变量名 | Widget 类型 | Is Variable | 业务用途 | 绑定事件/属性 |
| --- | --- | --- | --- | --- |
| `[Canvas Panel]` | `CanvasPanel` | 不适用（根容器） | Widget 布局根节点 | 截图未显示属性绑定 |
| `[Size Box]` | `SizeBox` | 待核验 | 约束敌人生命条布局尺寸 | 截图未显示属性绑定 |
| `PB_EnemyHealth` | `ProgressBar` | 是（Function Graph 有变量引用） | 显示敌人生命比例 | `SetEnemyHealth` 调用 `SetPercent` |

## Designer 默认值

- Visibility: 待核验
- Input/Focus 设置: 待核验
- 其他影响业务流程的默认值: 待核验

层级来自 2026-09-12 的 Designer Widget Tree 截图：`CanvasPanel → SizeBox → PB_EnemyHealth`。
