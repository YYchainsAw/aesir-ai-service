# IMC_AesirLocomotion Mappings

| Input Action | Key | Triggers | Modifiers | 状态 |
| --- | --- | --- | --- | --- |
| `IA_Move` | `W` | `0 Array elements` | `[0] Swizzle Input Axis Values (Order=YXZ)` | 已核验 |
| `IA_Move` | `S` | `0 Array elements` | `[0] Swizzle Input Axis Values (Order=YXZ)` → `[1] Negate (X=true, Y=true, Z=true)` | 已核验 |
| `IA_Move` | `A` | `0 Array elements` | `[0] Negate (X=true, Y=true, Z=true)` | 已核验 |
| `IA_Move` | `D` | `0 Array elements` | `0 Array elements` | 已核验 |
| `IA_Move` | `Gamepad Left Thumbstick 2D-Axis` | 待核验 | 待核验 | 键位已核验 |
| `IA_Move_WorldSpace` | `Up` | `0 Array elements` | `[0] Swizzle Input Axis Values (Order=YXZ)` | 已核验 |
| `IA_Move_WorldSpace` | `Down` | `0 Array elements` | `[0] Swizzle Input Axis Values (Order=YXZ)` → `[1] Negate (X=true, Y=true, Z=true)` | 已核验 |
| `IA_Move_WorldSpace` | `Left` | `0 Array elements` | `[0] Negate (X=true, Y=true, Z=true)` | 已核验 |
| `IA_Move_WorldSpace` | `Right` | `0 Array elements` | `0 Array elements` | 已核验 |
| `IA_Look` | `Mouse XY 2D-Axis` | 待核验 | 待核验 | 键位已核验 |
| `IA_Look_Gamepad` | `Gamepad Right Thumbstick 2D-Axis` | 待核验 | 待核验 | 键位已核验 |
| `IA_Sprint` | `Left Shift` | 待核验 | 待核验 | 键位已核验 |
| `IA_Sprint` | `Gamepad Left Thumbstick Button` | 待核验 | 待核验 | 键位已核验 |
| `IA_Jump` | `Right Alt` | 待核验 | 待核验 | 键位已核验 |
| `IA_Traverse` | `Space Bar` | 待核验 | 待核验 | 键位已核验 |
| `IA_Traverse` | `Gamepad Face Button Bottom` | 待核验 | 待核验 | 键位已核验 |
| `IA_Crouch` | `C` | 待核验 | 待核验 | 键位已核验 |
| `IA_Interact` | `E` | 待核验 | 待核验 | 键位已核验 |
| `IA_Interact` | `Gamepad Face Button Bottom` | 待核验 | 待核验 | 键位已核验 |
| `IA_Strafe` | `Thumb Mouse Button` | 待核验 | 待核验 | 键位已核验 |
| `IA_Aim` | `Left Ctrl` | 待核验 | 待核验 | 键位已核验 |
| `IA_Aim` | `Gamepad Left Trigger Axis` | 待核验 | 待核验 | 键位已核验 |
| `IA_NextPawn` | `N` | 待核验 | 待核验 | 键位已核验 |
| `IA_NextPawn` | `Gamepad D-pad Left` | 待核验 | 待核验 | 键位已核验 |
| `IA_NextVisualOverride` | `M` | 待核验 | 待核验 | 键位已核验 |
| `IA_NextVisualOverride` | `Gamepad D-pad Right` | 待核验 | 待核验 | 键位已核验 |
| `IA_TwinStick_AimDirection` | `Gamepad Right Thumbstick 2D-Axis` | 待核验 | 待核验 | 键位已核验 |
| `IA_TeleportToTarget` | `J` | 待核验 | 待核验 | 键位已核验 |
| `IA_PushToTalk` | `T` | 待核验 | 待核验 | 键位已核验 |

## Context 默认值

| 字段 | 当前值 |
| --- | --- |
| Mapping Profile Overrides | `0 Map elements` |
| Input Mode Filter Options | `Use Project Default Query` |
| Registration Tracking Mode | `Untracked` |
| Description | 空 |

> 核验日期：2026-09-12。用户确认当前使用 `IMC_AesirLocomotion`；两张 Details 截图确认 16 个 Action、29 条键位。除下方已展开的 `IA_Move` 键盘映射外，其余键位的 Triggers/Modifiers 尚未核验。

### IA_Move 共同 Mapping 设置

| 键位 | Setting Behavior | Player Mappable Key Settings |
| --- | --- | --- |
| `W` | `Inherit Settings from Action` | `None` |
| `S` | `Inherit Settings from Action` | `None` |
| `A` | `Inherit Settings from Action` | `None` |
| `D` | `Inherit Settings from Action` | `None` |

方向组合已完整核验：`D` 提供正 X；`A` 对输入执行 Negate；`W` 通过 `YXZ` Swizzle 将一维输入换到 Y；`S` 先以 `YXZ` Swizzle 换轴，再执行 Negate。这里对方向结果的说明来自已显示的 Modifier 顺序和参数。

### IA_Move_WorldSpace 共同 Mapping 设置

| 键位 | Setting Behavior | Player Mappable Key Settings |
| --- | --- | --- |
| `Up` | `Inherit Settings from Action` | `None` |
| `Down` | `Inherit Settings from Action` | `None` |
| `Left` | `Inherit Settings from Action` | `None` |
| `Right` | `Inherit Settings from Action` | `None` |

方向组合与 `IA_Move` 的 WASD 配置一致：`Right` 为正 X，`Left` 执行 Negate，`Up` 使用 `YXZ` Swizzle，`Down` 使用 `YXZ` Swizzle 后执行 Negate。

## 需要运行核验的重叠输入

- `Space Bar`：本 Context 的 `IA_Traverse`；`IMC_AesirCombat` 的 `IA_Evade`。
- `Gamepad Face Button Bottom`：本 Context 的 `IA_Traverse` 与 `IA_Interact`；`IMC_AesirCombat` 的 `IA_Evade`。
- `Gamepad Right Thumbstick 2D-Axis`：本 Context 的 `IA_Look_Gamepad` 与 `IA_TwinStick_AimDirection`。

C++ `AAesirCombatPrototypePlayerController::SetupInputComponent` 以优先级 `0` 添加所有 `DefaultMappingContexts`。以上重叠是否造成多 Action 同时触发，仍需 PIE 实测，不能仅凭映射表判定为缺陷。
