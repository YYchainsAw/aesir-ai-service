# WBP_EnemyHealthBar 其他 Graph

每个业务 Function/Macro Graph 分别复制到本目录的 `<Graph实际名称>.txt`。

- 已导出函数：`SetEnemyHealth`
- 文件：`SetEnemyHealth.txt`
- 节点数：5
- 核验结果：`Clamp(CurrentHealth / MaxHealth, 0.0, 1.0)` 后调用 `PB_EnemyHealth.SetPercent`。
- 注意：与 `WBP_CombatHUD.SetPlayerHealth` 不同，本函数没有 `Max(MaxHealth, 1.0)` 分母保护节点。
