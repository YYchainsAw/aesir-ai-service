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
| Player | `BP_AesirPlayerCharacter` | `blueprints/BP_AesirPlayerCharacter/` | 待填写 |
| Player | `BP_AesirPlayerCharacter_MM_Test` | `blueprints/BP_AesirPlayerCharacter_MM_Test/` | 测试资产，待填写 |
| Player | `BP_AesirPlayer_MM_Reference` | `blueprints/BP_AesirPlayer_MM_Reference/` | 参考资产，待填写 |
| Enemy | `BP_AesirEnemyCharacter` | `blueprints/BP_AesirEnemyCharacter/` | 待填写 |
| Enemy | `BP_AesirEnemyCharacter_Clean` | `blueprints/BP_AesirEnemyCharacter_Clean/` | 候选，待填写 |
| Enemy | `BP_AesirCombatDummy` | `blueprints/BP_AesirCombatDummy/` | 待填写 |
| Enemy | `BP_AesirMiniBoss_Clean` | `blueprints/BP_AesirMiniBoss_Clean/` | 待填写 |
| Boss AI | `BP_AesirBossAIController` | `blueprints/BP_AesirBossAIController/` | 待填写 |
| Companion | `BP_AliceCompanion`、`BP_AliceAIController`、`BTS_AliceUpdateTarget` | 已有目录 | 已导入/部分核验 |

## UI 与动画蓝图

| 系统 | 资产 | 证据目录 | 状态 |
| --- | --- | --- | --- |
| Chat UI | `WBP_CompanionChatTest` | 已有目录 | EventGraph 已核验 |
| Combat UI | `WBP_CombatHUD` | `blueprints/WBP_CombatHUD/` | 待填写 |
| Combat UI | `WBP_EnemyHealthBar` | `blueprints/WBP_EnemyHealthBar/` | 待填写 |
| Result UI | `WBP_CombatResult` | `blueprints/WBP_CombatResult/` | 待填写 |
| Targeting UI | `WBP_LockOnIndicator` | `blueprints/WBP_LockOnIndicator/` | 待填写 |
| Animation | `ABP_Alice` | `blueprints/ABP_Alice/` | 待填写 |
| Animation | `ABP_AesirPlayer` | `blueprints/ABP_AesirPlayer/` | 待填写 |
| Retargeting | `ABP_Gideon_RuntimeRetarget` | `blueprints/ABP_Gideon_RuntimeRetarget/` | 待填写 |

## 行为树、输入与动画数据

- Boss：`behavior-trees/BT_AesirBoss/`、`behavior-trees/BB_AesirBoss/`。
- Alice：现有 `BT_Alice`、`BB_Alice` 证据已导入。
- Enhanced Input：`input/actions.md` 及两个 `IMC_*/mappings.md`。
- Montage/Retarget：`animations/`。
- 地图与 Level Blueprint：`levels/L_AesirCombatTest/`。

## 不进入业务 UML 的资产

`Content/LevelPrototyping`、材质、纹理、普通静态网格、压缩设置以及 World Partition 自动生成的 `__ExternalActors__`/ `__ExternalObjects__` 不单独建 UML 节点；它们不承载当前业务域行为。若后续发现其中 Actor 含业务脚本，再补充证据。

