# Input Actions

| Asset | Value Type | Triggers | Modifiers | 业务用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `IA_Evade` | `Digital (bool)` | `0 Array elements` | `0 Array elements` | 闪避 | 已核验 |
| `IA_HeavyAttack` | `Digital (bool)` | `0 Array elements` | `0 Array elements` | 重攻击 | 已核验；截图时资产显示未保存标记 |
| `IA_LightAttack` | `Digital (bool)` | `0 Array elements` | `0 Array elements` | 轻攻击 | 已核验 |
| `IA_LockOn` | `Digital (bool)` | `0 Array elements` | `0 Array elements` | 锁定目标 | 已核验 |
| `IA_PushToTalk` | `Digital (bool)` | `0 Array elements` | `0 Array elements` | 按键说话 | Action 默认值和主要玩家 EventGraph 调用均已核验 |
| `IA_ToggleCompanionChat` | `Digital (bool)` | `0 Array elements` | `0 Array elements` | 打开/关闭陪伴聊天 | Action 默认值、IMC 键位和 Controller C++ 绑定均已核验 |

## 六个 Action 的共同设置

| 字段 | 当前值 |
| --- | --- |
| Action Description | 空 |
| Trigger when Paused | `false` |
| Reserve All Mappings | `false` |
| Accumulation Behavior | `Take Highest Absolute Value` |
| Consume Lower Priority Enhanced Input Mappings | `true` |
| Consumes Action and Axis Mappings | `false` |
| Trigger Events That Consume Legacy Keys | `No Flags Set` |
| Player Mappable Key Settings | `None` |

> 核验日期：2026-09-12。用户确认截图中 `IA_Evade`、`IA_HeavyAttack`、`IA_LightAttack`、`IA_LockOn`、`IA_PushToTalk`、`IA_ToggleCompanionChat` 六个资产的上述设置完全一致。
