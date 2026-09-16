# BP_AesirPlayerController Class Defaults

| 属性 | 当前值 | 业务影响 | 证据 |
| --- | --- | --- | --- |
| `DefaultMappingContexts[0]` | `IMC_AesirLocomotion` | 注册移动、视角、姿态和 Push-to-talk 输入 | 用户于 2026-09-12 确认的当前 Class Defaults；旧截图曾显示 `IMC_Default` |
| `DefaultMappingContexts[1]` | `IMC_AesirCombat` | 注册战斗输入映射 | Class Defaults 截图 |
| `MobileExcludedMappingContexts[0]` | `IMC_MouseLook` | 非触控模式额外注册鼠标视角输入 | Class Defaults 截图 |
| `MobileControlsWidgetClass` | `UI_TouchSimple` | 触控模式使用的移动控制 Widget | Class Defaults 截图 |
| `bForceTouchControls` | `false`（未勾选） | 不强制桌面环境显示触控操作 | Class Defaults 截图 |
| `ToggleCompanionChatAction` | `IA_ToggleCompanionChat` | 打开/关闭陪伴聊天的输入 Action | `UI > Companion Chat` Class Defaults 截图 |
| `CompanionChatWidgetClass` | `WBP_CompanionChatTest` | 创建陪伴聊天 Widget | `UI > Companion Chat` Class Defaults 截图；显示名称末尾被控件截断，与项目内唯一同名候选资产交叉确认 |

## 配置变更记录

- 2026-09-11 的 Class Defaults 截图显示 `DefaultMappingContexts[0]=IMC_Default`。
- 用户于 2026-09-12 明确说明并再次确认当前 `DefaultMappingContexts` 使用 `IMC_AesirLocomotion + IMC_AesirCombat`，同时提供了 Locomotion Context 的完整 Mappings 截图。
- 当前基线采用最新确认值；旧截图保留为配置变更历史，不再作为当前状态。

## 证据

- 来源：用户提供的两张 `BP_AesirPlayerController` Class Defaults 截图。
- 截图文件：`codex-clipboard-703a8b7d-219d-44dc-8dcc-9e8b0320f632.png`、`codex-clipboard-c1d2c61f-9c74-44a7-9460-f8f369eb6562.png`。
- 核验日期：2026-09-11。
- 限制：组件、直接父类和其他非业务默认值仍未核验。
