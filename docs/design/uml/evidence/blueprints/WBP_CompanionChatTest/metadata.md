# WBP_CompanionChatTest 元数据

- Asset Path: `/Game/Aesir/UI/Companion/WBP_CompanionChatTest`
- Parent Class: 至少继承 `UUserWidget`；直接父类仍需 Class Settings 核验
- Blueprint Type: Widget Blueprint
- Interfaces: 待核验
- EventGraph 节点数: 34
- 核验日期: 2026-09-11
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## Graph 清单

| Graph 名称 | 类型 | 节点文本文件 | 状态 |
| --- | --- | --- | --- |
| `EventGraph` | Event Graph | `EventGraph.txt` | 已完成节点与 Pin 连线分析 |
| 待填写 | Function/Macro | `Functions/<实际名称>.txt` | 待检查 |

## EventGraph 当前职责

- Widget Construct 时获取 `UCompanionChatSubsystem` 并绑定成功/失败委托。
- SendButton 点击时读取 `InputMessage`，调用 `SendChatMessage`，更新等待状态并清空输入框。
- `OnChatReply` 更新 Alice 回复和调试信息。
- `OnChatError` 更新错误文本。
- CloseButton 点击时获取 Owning Player，转换为 `AAesirCombatPrototypePlayerController` 并调用 `CloseCompanionChat`。

当前 Graph 不包含语音录制、命令解析、战术决策或 `TryAcceptOrder` 节点。
