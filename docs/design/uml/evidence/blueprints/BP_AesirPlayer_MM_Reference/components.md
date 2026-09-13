# BP_AesirPlayer_MM_Reference Components

| 组件实例名 | 组件类型 | 来源 | 关键默认值 | 业务用途 |
| --- | --- | --- | --- | --- |
| `AC_FoleyEvents` | Foley Actor Component（具体类待核验） | Blueprint added | 待核验 | 脚步、落地等 Foley 事件 |
| `Capsule Component` | `UCapsuleComponent` | inherited | 待核验 | 角色碰撞 |
| `Arrow Component` | `UArrowComponent` | inherited | 待核验 | 编辑器朝向指示 |
| `Camera Boom` | `USpringArmComponent` | C++ inherited | 待核验 | 基础第三人称相机臂 |
| `Follow Camera` | `UCameraComponent` | C++ inherited | 待核验 | 基础跟随相机 |
| `Mesh` | `USkeletalMeshComponent` | inherited | 待核验 | 基础角色骨骼模型 |
| `VisualOverride` | Visual Override Component（具体类待核验） | Blueprint added | 待核验 | 外观覆盖 |
| `GideonVisualMesh` | `USkeletalMeshComponent` | Blueprint added | 待核验 | Gideon 主视觉模型 |
| `GameplayCamera` | `GameplayCameraComponent` | Blueprint added | 待核验 | Gameplay Camera 系统接入 |
| `WeaponMesh` | `UStaticMeshComponent` | inherited from `BP_AesirPlayerCharacter` | 待核验 | 武器显示与攻击表现 |
| `SpringArm` | `USpringArmComponent` | Blueprint added | 待核验 | 扩展相机臂 |
| `Camera(NotUsedByDefault)` | `UCameraComponent` | Blueprint added | 待核验 | 非默认备用相机 |
| `AC_PreCMCTick` | Actor Component（具体类待核验） | Blueprint added | 待核验 | Character Movement Tick 前置处理 |
| `Character Movement` | `UCharacterMovementComponent` | inherited | 待核验 | 角色移动 |
| `AC_SmartObjectAnimation` | Smart Object Animation Component | Blueprint added | 待核验 | Smart Object 动画协调 |
| `BP_VisualOverrideManager` | Visual Override Manager Component | Blueprint added | 待核验 | 外观覆盖管理 |
| `Combat State Component` | `UAesirCombatStateComponent` | C++ inherited | 待核验 | 玩家战斗状态 |
| `AC_TraversalLogic` | Traversal Logic Component | Blueprint added | 待核验 | 攀爬/跨越等 Traversal 逻辑 |
| `Combat Component` | `UAesirCombatComponent` | C++ inherited | 待核验 | 轻重攻击与伤害窗口 |
| `MotionWarping` | `UMotionWarpingComponent` | Blueprint added | 待核验 | 动作位移校正 |
| `Health Component` | `UAesirHealthComponent` | C++ inherited | 待核验 | 生命、受击与死亡 |
| `Targeting Component` | `UAesirTargetingComponent` | C++ inherited | 待核验 | 目标搜索和锁定 |
| `VoiceRecorder` | `UVoiceCaptureComponent` | Blueprint added | 待核验 | Push-to-talk 录音与语音命令入口 |

## 证据

- 来源：用户提供的 Unreal Editor Components 面板截图；C++ 类型与 `.uasset` 类型引用交叉核验。
- 核验日期：2026-09-11。
- 当前定位：用户确认的主要玩家资产。
