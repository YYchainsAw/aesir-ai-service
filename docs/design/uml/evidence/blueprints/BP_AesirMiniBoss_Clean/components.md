# BP_AesirMiniBoss_Clean Components

| 组件实例名 | 组件类型 | 来源 | 关键默认值 | 业务用途 |
| --- | --- | --- | --- | --- |
| `Capsule Component` | `UCapsuleComponent` | C++ inherited | 继承/默认 | Boss 碰撞 |
| `Arrow Component` | `UArrowComponent` | inherited | 继承/默认 | 编辑器朝向指示 |
| `Mesh` | `USkeletalMeshComponent` | inherited | Mesh / Animation Class 保持默认 | Boss 骨骼模型与动画 |
| `WeaponMesh` | `UStaticMeshComponent` | inherited from `BP_AesirEnemyCharacter` | 继承父蓝图 | 武器显示与攻击表现 |
| `LockOnIndicator` | `UWidgetComponent` | inherited from `BP_AesirEnemyCharacter` | 继承 `WBP_LockOnIndicator` | 世界空间锁定指示器 |
| `EnemyHealthBarWidget` | `UWidgetComponent` | inherited from `BP_AesirEnemyCharacter` | 继承 `WBP_EnemyHealthBar` | 世界空间 Boss 血条 |
| `Health Component` | `UAesirHealthComponent` | C++ inherited | 当前差异值为临时调试值 | Boss 生命、受击与死亡 |
| `Combat Component` | `UAesirCombatComponent` | C++ inherited | 继承/临时配置 | Boss 攻击和伤害窗口 |
| `Character Movement` | `UCharacterMovementComponent` | C++ inherited | 继承/默认 | Boss AI 移动 |
| `Combat State Component` | `UAesirCombatStateComponent` | C++ inherited | 继承/默认 | Combat、Stunned、Dead 等状态 |
| `Poise Component` | `UAesirPoiseComponent` | C++ inherited | 当前差异值为临时调试值 | Boss 韧性和破韧状态 |

## 证据

- 来源：用户提供的 Unreal Editor Components 面板截图。
- 截图文件：`codex-clipboard-102311b1-2055-44f0-bc6d-3b08a8a86166.png`。
- 核验日期：2026-09-12。
- 当前未发现该子蓝图新增组件；业务差异主要来自 AIController 覆盖。
