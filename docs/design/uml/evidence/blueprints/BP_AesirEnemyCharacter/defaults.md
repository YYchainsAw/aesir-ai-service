# BP_AesirEnemyCharacter Class Defaults

| 属性 | 当前值 | 业务影响 | 证据 |
| --- | --- | --- | --- |
| `AI Controller Class` | `AesirEnemyAIController` | 敌人由项目 C++ AIController 驱动 | 用户编辑器核验；与 C++ 构造默认值一致 |
| `Auto Possess AI` | `Placed in World or Spawned` | 关卡放置和运行时生成的敌人都会自动创建 AIController | 用户编辑器核验；与 C++ 构造默认值一致 |
| `EnemyHealthBarWidget.Widget Class` | `WBP_EnemyHealthBar` | 世界空间组件创建敌人血条 Widget | 用户编辑器核验 |
| `LockOnIndicator.Widget Class` | `WBP_LockOnIndicator` | 世界空间组件创建锁定指示 Widget | 用户编辑器核验 |

## 证据

- 来源：用户在 Unreal Editor 中逐项确认 Class Defaults 和 Widget Component 设置。
- 核验日期：2026-09-12。
- 仍待核验：Skeletal Mesh、Animation Class、攻击 Montage、Health、Poise、碰撞和 Widget 空间参数等数值型默认值。
