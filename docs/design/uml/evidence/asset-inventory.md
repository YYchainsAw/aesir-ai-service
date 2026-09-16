# Unreal 业务资产导入清单

> 盘点基线：UE commit `dead903156946ec6956342f02d587612baab1717`  
> “已建模板”只代表证据入口已创建，不代表内部节点已核验。

## 当前运行入口

| 类型 | 资产 | 配置证据 | 模板状态 |
| --- | --- | --- | --- |
| Map | `L_AesirCombatTest` | `DefaultEngine.ini`: EditorStartupMap + GameDefaultMap | 已建模板 |
| GameMode | `BP_AesirGameMode` | `DefaultEngine.ini`: GlobalDefaultGameMode | 已建模板 |

## 角色、AI 与框架蓝图

| 系统 | 资产 | 证据目录 | 状态 |
| --- | --- | --- | --- |
| Framework | `BP_AesirGameMode` | `blueprints/BP_AesirGameMode/` | 待填写 |
| Framework | `BP_AesirPlayerController` | `blueprints/BP_AesirPlayerController/` | 待填写 |
| Framework | `BP_MMPlayerController` | `blueprints/BP_MMPlayerController/` | 候选/测试，待判定是否运行 |
| Framework | `BP_AesirDeathCamera` | `blueprints/BP_AesirDeathCamera/` | 待填写 |
| Player | `BP_AesirPlayerCharacter` | `blueprints/BP_AesirPlayerCharacter/` | 基础战斗蓝图；组件与 EventGraph 已导入 |
| Player | `BP_AesirPlayerCharacter_MM_Test` | `blueprints/BP_AesirPlayerCharacter_MM_Test/` | 测试资产，待填写 |
| Player | `BP_AesirPlayer_MM_Reference` | `blueprints/BP_AesirPlayer_MM_Reference/` | 用户确认的主要玩家资产；组件与 EventGraph 已导入 |
| Enemy | `BP_AesirEnemyCharacter` | `blueprints/BP_AesirEnemyCharacter/` | 组件、AI/Widget 装配与 EventGraph 已导入 |
| Enemy | `BP_AesirEnemyCharacter_Clean` | `blueprints/BP_AesirEnemyCharacter_Clean/` | 候选，待填写 |
| Enemy | `BP_AesirCombatDummy` | `blueprints/BP_AesirCombatDummy/` | 待填写 |
| Boss Pawn | `BP_AesirMiniBoss_Clean` | `blueprints/BP_AesirMiniBoss_Clean/` | 继承普通敌人；EventGraph 为空；使用 `BP_AesirBossAIController` |
| Boss AI | `BP_AesirBossAIController` | `blueprints/BP_AesirBossAIController/` | EventGraph 为空；`BossBehaviorTree=BT_AesirBoss` 已核验 |
| Companion | `BP_AliceCompanion`、`BP_AliceAIController`、`BTS_AliceUpdateTarget` | 已有目录 | 已导入/部分核验 |

## UI 与动画蓝图

| 系统 | 资产 | 证据目录 | 状态 |
| --- | --- | --- | --- |
| Chat UI | `WBP_CompanionChatTest` | 已有目录 | EventGraph 已核验 |
| Combat UI | `WBP_CombatHUD` | `blueprints/WBP_CombatHUD/` | Widget Tree、12 节点 EventGraph 与 6 节点 `SetPlayerHealth` 已核验 |
| Combat UI | `WBP_EnemyHealthBar` | `blueprints/WBP_EnemyHealthBar/` | Widget Tree、空 EventGraph 与 5 节点 `SetEnemyHealth` 已核验 |
| Result UI | `WBP_CombatResult` | `blueprints/WBP_CombatResult/` | Widget Tree、9 节点 EventGraph、6 节点函数和 GameMode 调用链已核验 |
| Targeting UI | `WBP_LockOnIndicator` | `blueprints/WBP_LockOnIndicator/` | Widget Tree、空 EventGraph、无其他 Graph及敌人可见性控制链已核验 |
| Animation | `ABP_Alice` | `blueprints/ABP_Alice/` | 待填写 |
| Animation | `ABP_AesirPlayer` | `blueprints/ABP_AesirPlayer/` | 待填写 |
| Retargeting | `ABP_Gideon_RuntimeRetarget` | `blueprints/ABP_Gideon_RuntimeRetarget/` | 待填写 |

## 行为树、输入与动画数据

- Boss：`behavior-trees/BT_AesirBoss/`、`behavior-trees/BB_AesirBoss/`。
- Alice：现有 `BT_Alice`、`BB_Alice` 证据已导入。
- Enhanced Input：6 个 Aesir Action、`IMC_AesirCombat`、`IMC_AesirLocomotion` 的 16 个 Action/29 个键位及当前 Controller 装配已核验；Locomotion 映射细节和重叠键运行测试待补，见 `input/`。
- Montage/Retarget：`animations/`。
- 地图与 Level Blueprint：`levels/L_AesirCombatTest/`。

## 不进入业务 UML 的资产

`Content/LevelPrototyping`、材质、纹理、普通静态网格、压缩设置以及 World Partition 自动生成的 `__ExternalActors__`/ `__ExternalObjects__` 不单独建 UML 节点；它们不承载当前业务域行为。若后续发现其中 Actor 含业务脚本，再补充证据。
