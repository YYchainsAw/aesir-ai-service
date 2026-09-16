# WBP_CompanionChatTest Widget Tree

| Widget 变量名 | Widget 类型 | Is Variable | 业务用途 | 绑定事件/属性 |
| --- | --- | --- | --- | --- |
| `InputMessage` | `EditableText` | 是（EventGraph 有变量引用） | 输入聊天文本 | SendButton 流程读取并在发送后清空 |
| `SendButton` | `Button` | 是（存在 ComponentBoundEvent） | 发送聊天内容 | `OnClicked` |
| `CloseButton` | `Button` | 是（存在 ComponentBoundEvent） | 关闭聊天界面 | `OnClicked` |
| `AliceReplyText` | `TextBlock` | 是（EventGraph 有变量引用） | 显示 Alice 的 `ReplyText` | `OnChatReply` 写入 Text |
| `DebugText` | `TextBlock` | 是（EventGraph 有变量引用） | 显示等待状态或回复元数据 | Send 与 OnChatReply 流程写入 Text |
| `ErrorText` | `TextBlock` | 是（EventGraph 有变量引用） | 显示请求错误 | Send 前清空；OnChatError 写入错误 |

## Designer 默认值

- Visibility: 待核验
- Input/Focus 设置: 待核验
- 其他影响业务流程的默认值: 待核验

以上只列出 EventGraph 能证明存在的 Widget 变量；完整 Widget Tree 层级仍需 Designer 面板截图核验。
