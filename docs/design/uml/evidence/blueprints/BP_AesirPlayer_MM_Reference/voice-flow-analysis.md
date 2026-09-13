# BP_AesirPlayer_MM_Reference 语音流程切片

> 原始证据：`EventGraph.txt`（187 个节点）  
> 本文件只分析语音命令切片，不代表整个 EventGraph 已完成业务分析。

## 已核验调用链

```text
IA_PushToTalk
├─ Started → VoiceRecorder.StartRecording
├─ Completed → 停止录音处理
└─ Canceled → IsRecording
                └─ true → VoiceRecorder.StopRecording
                           → 成功/失败判断
                              └─ 成功路径读取 VoiceRecorder.GetLastWavData
                                 → Get CommandServiceSubsystem
                                 → ParseVoiceCommand(WavData)
```

## 关键节点

| 节点 | Node GUID |
| --- | --- |
| `IA_PushToTalk` | `1E7C893048FC46A3108C2B9F35112EE1` |
| `StartRecording` | `63D22CE04703A8129B66DF93CA07BCBB` |
| `StopRecording` | `6ADC545E43108A10C95D999A6BEB0F9D` |
| `IsRecording` | `47C7CB834093126EDDA816AEC2F12303` |
| `GetLastWavData` | `2C32DA0E48E32E8B89F62BBE65C901ED` |
| Get `CommandServiceSubsystem` | `B4DEB96C48C0A4B5FC7AC5B1690A0890` |
| `ParseVoiceCommand` | `E16AD7124AA6D539F9B67589E6A49EFE` |

## 当前边界

- 已证明主要玩家蓝图直接使用 `UVoiceCaptureComponent`。
- 已证明录音数据传入 `UCommandServiceSubsystem.ParseVoiceCommand`。
- 当前 EventGraph 未发现 `UTacticalOrderComponent.TryAcceptOrder`。
- 命令解析结果的后续委托处理仍需结合其他节点或资产继续分析。
