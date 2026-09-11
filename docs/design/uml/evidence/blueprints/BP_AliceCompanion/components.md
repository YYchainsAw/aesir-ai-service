# BP_AliceCompanion Components

| 组件实例名 | 组件类型 | 来源 | 关键默认值 | 业务用途 |
| --- | --- | --- | --- | --- |
| `Capsule Component` | `UCapsuleComponent` | `ACharacter` inherited | 待核验 | 角色碰撞 |
| `Arrow Component` | `UArrowComponent` | inherited | 待核验 | 编辑器朝向指示 |
| `Mesh` | `USkeletalMeshComponent` | `ACharacter` inherited | 待核验 | 角色模型与动画 |
| `AesirCombatState` | `UAesirCombatStateComponent` | Blueprint added | 待核验 | 同伴战斗状态 |
| `AesirHealth` | `UAesirHealthComponent` | Blueprint added | 待核验 | 同伴生命值与死亡状态 |
| `Character Movement` | `UCharacterMovementComponent` | `ACharacter` inherited | 待核验 | 同伴移动 |
| `TacticalOrder` | `UTacticalOrderComponent` | Blueprint added | 待核验 | 战术订单校验与生命周期 |

## 必查项

- `UTacticalOrderComponent`: 已确认，实例名 `TacticalOrder`
- `UAesirHealthComponent`: 已确认，实例名 `AesirHealth`
- `UAesirCombatStateComponent`: 已确认，实例名 `AesirCombatState`
- 战斗/技能相关组件: 截图中未见 `UAesirCombatComponent` 或独立技能组件
- Skeletal Mesh 与 Animation Class: 待核验

## 证据

- 来源：用户提供的 Unreal Editor Components 面板截图
- 核验日期：2026-09-11
- 限制：截图只证明组件存在，不能证明组件默认值或组件之间的执行连接
