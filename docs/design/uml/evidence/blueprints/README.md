# 蓝图核验证据

本目录保存从 Unreal Editor 复制的蓝图节点文本，以及无法从节点文本表达的组件、默认值和 Widget Tree 信息。

## 填写规则

1. `.txt` 文件中的占位行需要被完整替换为 Unreal Editor `Ctrl+A`、`Ctrl+C` 得到的原始文本。
2. 一个 Graph 对应一个 `.txt` 文件，不要把多个 Graph 混在同一个文件中。
3. 不要整理、删减或手动修改节点文本中的 `NodeGuid`、`PinId` 和 `LinkedTo`。
4. Markdown 中不知道的字段填写 `待核验`，确认不存在则填写 `无`。
5. 打开资产仅用于读取；核验过程中不要保存或重新编译 UE 蓝图。

## 当前核验顺序

Alice 与聊天链已经完成第一轮。其他系统按业务闭环分批核验：

1. 玩家战斗：`BP_AesirGameMode` → `BP_AesirPlayerController` → `BP_AesirPlayerCharacter` → `ABP_AesirPlayer`。
2. 敌人/Boss：`BP_AesirEnemyCharacter` → `BP_AesirBossAIController` → `BT_AesirBoss` → `BB_AesirBoss`。
3. 战斗 UI：`WBP_CombatHUD` → `WBP_EnemyHealthBar` → `WBP_LockOnIndicator` → `WBP_CombatResult`。
4. 关卡装配：`L_AesirCombatTest` World Settings、业务 Actor 和 Level Blueprint。
5. 输入与动画数据：两个 Mapping Context、六个 Input Action、Montage Notify。
6. 候选/测试资产最后核验，先判定是否被当前 GameMode、关卡或其他蓝图引用。

完整资产范围和状态见 `../asset-inventory.md`。

填写完成后，根据节点文本中的 `NodeGuid`、`PinId` 和 `LinkedTo` 更新 `../traceability.csv`。
