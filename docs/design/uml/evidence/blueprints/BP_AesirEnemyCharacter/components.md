# BP_AesirEnemyCharacter Components

| 组件实例名 | 组件类型 | 来源 | 关键默认值 | 业务用途 |
| --- | --- | --- | --- | --- |
| `Capsule Component` | `UCapsuleComponent` | `ACharacter` inherited | 待核验 | 敌人碰撞 |
| `Arrow Component` | `UArrowComponent` | inherited | 待核验 | 编辑器朝向指示 |
| `Mesh` | `USkeletalMeshComponent` | `ACharacter` inherited | 待核验 | 敌人骨骼模型与动画 |
| `WeaponMesh` | `UStaticMeshComponent` | Blueprint added | 待核验 | 武器显示与攻击表现 |
| `EnemyHealthBarWidget` | `UWidgetComponent` | Blueprint added | Widget Class = `WBP_EnemyHealthBar` | 世界空间敌人血条 |
| `LockOnIndicator` | `UWidgetComponent` | Blueprint added | Widget Class = `WBP_LockOnIndicator` | 世界空间锁定指示器 |
| `Health Component` | `UAesirHealthComponent` | C++ inherited | 待核验 | 生命、受击与死亡 |
| `Character Movement` | `UCharacterMovementComponent` | `ACharacter` inherited | C++ 默认 MaxWalkSpeed `250` | AI 移动 |
| `Combat Component` | `UAesirCombatComponent` | C++ inherited | 待核验 | 攻击和伤害窗口 |
| `Combat State Component` | `UAesirCombatStateComponent` | C++ inherited | 待核验 | Combat、Stunned、Dead 等状态 |
| `Poise Component` | `UAesirPoiseComponent` | C++ inherited | 待核验 | 韧性累计、破韧和恢复 |

## 证据

- 来源：用户提供的 Unreal Editor Components 面板截图；C++ `CreateDefaultSubobject` 与 `.uasset` 类型引用交叉核验。
- 截图文件：`codex-clipboard-96550895-1779-41e5-bbfc-79f4da938958.png`。
- 核验日期：2026-09-12。
- 限制：组件数值、动画和碰撞等其他默认值仍需核验。
