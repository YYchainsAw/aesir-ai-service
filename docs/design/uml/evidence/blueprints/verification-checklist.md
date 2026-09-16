# 当前蓝图核验清单

| 资产 | 元数据 | 组件/默认值 | EventGraph | 其他 Graph | 状态 |
| --- | --- | --- | --- | --- | --- |
| `WBP_CompanionChatTest` | 已填写 | EventGraph 引用的 6 个 Widget 已确认；完整层级待核验 | 34 个节点已分析 | 待检查是否有其他 Function | 基本完成 |
| `BP_AliceCompanion` | 部分待填写 | Components 已核验，默认值待填写 | 已核验为空 | 待检查 | 部分完成 |
| `BP_AliceAIController` | 待填写 | 待填写 | 待填写 | 待检查 | 未开始 |
| `BTS_AliceUpdateTarget` | 已填写 | TargetActorKey 与实例周期已核验 | 已核验 | 待检查是否有其他 Function | 基本完成 |
| `BT_Alice` | 已填写 | Service、Decorator 和 Task 已核验 | 已核验 | 不适用 | 已完成 |
| `BB_Alice` | 已填写 | 2 个 Keys 及 TargetActor 读写链已核验 | 不适用 | 不适用 | 已完成 |

## 其他业务系统

| 业务组 | 资产 | 已创建的证据入口 | 当前状态 |
| --- | --- | --- | --- |
| 玩家与框架 | `BP_AesirGameMode`、`BP_AesirPlayerController`、`BP_AesirPlayerCharacter`、`BP_AesirPlayer_MM_Reference`、`BP_AesirDeathCamera` | metadata / components / defaults / EventGraph / Functions | GameMode EventGraph 已导入；PlayerController 已核验；基础与主要玩家组件/EventGraph 已导入；主要玩家为 `BP_AesirPlayer_MM_Reference`；默认值与 DeathCamera 待填写 |
| 敌人与 Boss | `BP_AesirEnemyCharacter`、`BP_AesirCombatDummy`、`BP_AesirMiniBoss_Clean`、`BP_AesirBossAIController` | metadata / components / defaults / EventGraph / Functions | 普通敌人已核验；MiniBoss 继承组件、EventGraph 为空、Boss AIController 装配已核验；临时数值不建立基线；CombatDummy 待填写 |
| Boss 行为树 | `BT_AesirBoss`、`BB_AesirBoss` | Graph / tree / services-decorators / keys | BT 的 17 个节点及三分支已核验；BB 的 3 个已知 Key Details 和 Parent=None 已核验；完整 Key 列表待截图 |
| 战斗 UI | `WBP_CombatHUD`、`WBP_EnemyHealthBar`、`WBP_LockOnIndicator`、`WBP_CombatResult` | metadata / widget-tree / EventGraph / Functions | 四个核心 Widget 的业务 Graph 已核验；GameMode 已重新编译成功；Designer 样式和直接父类仍待核验 |
| 动画蓝图 | `ABP_AesirPlayer`、`ABP_Alice`、`ABP_Gideon_RuntimeRetarget` | metadata / EventGraph / AnimGraph / StateMachines / Functions | 待填写 |
| 关卡装配 | `L_AesirCombatTest` | metadata / world-settings / actors / LevelBlueprint | Level Blueprint 已核验为空；World Settings 与业务 Actor 待填写 |
| Enhanced Input | 6 个 Aesir `IA_*`、`IMC_AesirCombat`、`IMC_AesirLocomotion` | actions / mappings | 6 个 Aesir Action、Combat Context 与当前 Controller 装配已核验；Locomotion 的 16 个 Action/29 个键位以及 IA_Move、IA_Move_WorldSpace 方向 Modifier 已完整核验，其他映射细节和重叠键运行测试待补 |
| Montage/Retarget | 玩家、敌人 Montage 与 Retargeting 资产 | montages / retargeting | 待填写 |
| 候选/测试 | `BP_MMPlayerController`、`BP_AesirPlayerCharacter_MM_Test`、`BP_AesirPlayer_MM_Reference`、`BP_AesirEnemyCharacter_Clean` | 标准 Blueprint 证据模板 | 待判定运行引用 |

## 需要证明的关系

- [ ] UI 调用 `UVoiceCaptureComponent`（当前 Widget 未发现）
- [ ] UI 调用 `UCommandServiceSubsystem`（当前 Widget 未发现）
- [x] UI 调用 `UCompanionChatSubsystem`
- [ ] `OnCommandParsed` 的输出传给 `UTacticalOrderComponent.TryAcceptOrder`
- [ ] 战术订单进入同伴 AI、Blackboard 或行为树执行链

## 已确认的实现缺口

- `BP_AliceCompanion.EventGraph` 当前为空，没有在该 Graph 中把 `TacticalOrder` 接入同伴 AI 或技能执行。
- `BP_AliceCompanion` 已具备 `TacticalOrder`、`AesirHealth` 和 `AesirCombatState` 组件，可作为后续实现的结构基础。
- `BB_Alice` 当前只有 `SelfActor` 和 `TargetActor`，没有保存战术订单或技能信息的 Blackboard Key。
- `BT_Alice` 当前只实现跟随玩家：等待 `0.5s` 后移动到 `TargetActor`，接受半径为 `250`。
- `BTS_AliceUpdateTarget` 当前将 `GetPlayerController(0)` 写入 `TargetActor`，并未读取战术订单。
- `WBP_CompanionChatTest` 当前只实现文本陪伴聊天，没有语音采集、战术解析或订单提交节点。
