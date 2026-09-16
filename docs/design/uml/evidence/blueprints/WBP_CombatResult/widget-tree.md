# WBP_CombatResult Widget Tree

| Widget 变量名 | Widget 类型 | Is Variable | 业务用途 | 绑定事件/属性 |
| --- | --- | --- | --- | --- |
| `[Canvas Panel]` | `CanvasPanel` | 不适用（根容器） | 结算界面布局根节点 | 截图未显示属性绑定 |
| `[Border_Background]` | `Border` | 待核验 | 结算界面背景 | 截图未显示属性绑定 |
| `[VerticalBox_Result]` | `VerticalBox` | 待核验 | 排列结果文本和重新开始按钮 | 截图未显示属性绑定 |
| `TXT_Result` | `TextBlock` | 是（Function Graph 有变量引用） | 显示 `VICTORY` 或 `DEFEAT` | `SetCombatResult` 写入 Text；Designer 当前文本为 `Victory` |
| `BTN_Restart` | `Button` | 是（存在 ComponentBoundEvent） | 重新开始战斗 | `OnClicked` |
| `[Text]` | `TextBlock` | 待核验 | 按钮标签 | Designer 当前文本为 `ReStart` |

## Designer 默认值

- Visibility: 待核验
- Input/Focus 设置: 待核验
- 其他影响业务流程的默认值: 待核验

层级来自 2026-09-12 的 Designer Widget Tree 截图。
