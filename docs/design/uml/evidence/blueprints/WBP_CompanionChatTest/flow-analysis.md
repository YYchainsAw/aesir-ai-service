# WBP_CompanionChatTest EventGraph 分析

> 核验日期：2026-09-11  
> 原始证据：`EventGraph.txt`（34 个节点）

## 1. 初始化与委托绑定

```text
Construct
└─ Bind OnReplyReceived → OnChatReply
   └─ Bind OnRequestFailed → OnChatError
```

| 节点 | Node GUID |
| --- | --- |
| `Construct` | `6782FE1142D20EE6122A61BC01478B1E` |
| Get `CompanionChatSubsystem` | `4FE0BECA42E2C9E125A9B186BA9E6F56` |
| Bind `OnReplyReceived` | `708874184B6FCD25C7D7128D3969ADA0` |
| Bind `OnRequestFailed` | `198EA90B44615730E611E5A9639F94D0` |

`PreConstruct` 节点处于 Disabled 状态，没有业务连线。

## 2. 发送聊天

```text
SendButton.OnClicked
├─ 读取 InputMessage.GetText
├─ DebugText = “正在等待 Alice 回复……”
├─ ErrorText = 空文本
├─ CompanionChatSubsystem.SendChatMessage(TextToString(InputMessage.Text))
└─ InputMessage.Text = 空文本
```

| 节点 | Node GUID |
| --- | --- |
| `SendButton.OnClicked` | `395B28594F0724B33C8338ADD1D0FA65` |
| `InputMessage.GetText` | `1C6137A44E2D7A874DC98DAF443D7230` |
| `SendChatMessage` | `94D4FBF54C77A74F768F83963A36679C` |
| 设置等待文本 | `CCC4A8DF478210C9E52A358B5C43BC9D` |
| 清空 ErrorText | `16228E754E92420E0D3132A0052730F6` |
| 清空 InputMessage | `9B9A22B64A0D979FD7992CADD38E1224` |

输入内容的空值和长度校验位于 C++ `UCompanionChatSubsystem.SendChatMessage`，不在 Widget Graph 中。

## 3. 成功回复

```text
OnChatReply(CompanionChatReply)
├─ Break CompanionChatReply
├─ AliceReplyText = ReplyText
├─ DebugText = “Emotion: ... | Gesture: ... | Face: ... | Source: ...”
└─ ErrorText = 空文本
```

| 节点 | Node GUID |
| --- | --- |
| `OnChatReply` | `D5D46AB64ED76F7B7757D4B3FCB35472` |
| Break `CompanionChatReply` | `ADD21AC34F59CAB5B6C3B5893DD4D410` |
| 设置 AliceReplyText | `2832F0CE4BEC86F3B0BE0FBC6A3CD3EF` |
| Format Text | `058F8EF9443ED66F03D9ECB7258CC290` |
| 设置 DebugText | `0F7CFE5D4D919A2DF8186AA0A40FCD18` |
| 清空 ErrorText | `8AD01E344D83E64F40D222B57C43B262` |

调试文本使用 `EmotionId`、`GestureId`、`FacialExpressionId` 和 `Source`；当前没有使用 `ProtocolVersion`、`CompanionId` 或 `bInterruptible` 驱动其他节点。

## 4. 错误回复

```text
OnChatError(Error)
└─ ErrorText = StringToText(Error)
```

| 节点 | Node GUID |
| --- | --- |
| `OnChatError` | `C23886CF4AC16C3EA814AFB4FD485183` |
| 设置 ErrorText | `48BB28D44F53C0A0A22FAC8B33D2CD55` |

## 5. 关闭界面

```text
CloseButton.OnClicked
└─ GetOwningPlayer
   └─ Cast AAesirCombatPrototypePlayerController
      └─ CloseCompanionChat
```

| 节点 | Node GUID |
| --- | --- |
| `CloseButton.OnClicked` | `773DB545456380FEE0EF858214F8BF17` |
| `GetOwningPlayer` | `408944404968C69B892205A261D3BCBE` |
| Cast PlayerController | `4C303E734832F1EBFE23AEBEF699FE73` |
| `CloseCompanionChat` | `A8D93EAC4F1A1921121A3494E1E9BECD` |

## 6. 范围结论

- 已实现：文本陪伴聊天、成功/失败反馈、关闭界面。
- 未发现：`UVoiceCaptureComponent` 调用。
- 未发现：`UCommandServiceSubsystem` 调用。
- 未发现：`ParseCommand`、`ParseVoiceCommand`、`ResolveTacticalIntentForTest`。
- 未发现：`UTacticalOrderComponent.TryAcceptOrder`。
