# BP_AesirPlayerCharacter Components

| 组件实例名 | 组件类型 | 来源 | 关键默认值 | 业务用途 |
| --- | --- | --- | --- | --- |
| `Capsule Component` | `UCapsuleComponent` | `ACharacter` inherited | 待核验 | 角色碰撞 |
| `Arrow Component` | `UArrowComponent` | C++ inherited | 待核验 | 编辑器朝向指示 |
| `Camera Boom` | `USpringArmComponent` | C++ inherited | 待核验 | 第三人称相机臂 |
| `Follow Camera` | `UCameraComponent` | C++ inherited | 待核验 | 第三人称跟随相机 |
| `Mesh` | `USkeletalMeshComponent` | `ACharacter` inherited | 待核验 | 角色骨骼模型与动画 |
| `WeaponMesh` | `UStaticMeshComponent` | Blueprint added | 待核验 | 武器显示与攻击表现 |
| `Combat State Component` | `UAesirCombatStateComponent` | C++ inherited | 待核验 | 玩家战斗状态 |
| `Character Movement` | `UCharacterMovementComponent` | `ACharacter` inherited | 待核验 | 角色移动 |
| `Combat Component` | `UAesirCombatComponent` | C++ inherited | 待核验 | 轻重攻击与伤害窗口 |
| `Health Component` | `UAesirHealthComponent` | C++ inherited | 待核验 | 生命、受击与死亡 |
| `Targeting Component` | `UAesirTargetingComponent` | C++ inherited | 待核验 | 目标搜索和锁定 |

## 证据

- 来源：用户提供的 Unreal Editor Components 面板截图；C++ `CreateDefaultSubobject` 与资产类型字符串交叉核验。
- 核验日期：2026-09-11。
- 当前定位：基础玩家战斗蓝图，不是用户确认的主要玩家资产。
