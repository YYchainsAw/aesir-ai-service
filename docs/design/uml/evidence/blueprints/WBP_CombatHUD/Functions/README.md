# WBP_CombatHUD 其他 Graph

每个业务 Function/Macro Graph 分别复制到本目录的 `<Graph实际名称>.txt`。

- 已发现函数：`SetPlayerHealth`
- 已导出文件：`SetPlayerHealth.txt`
- 节点数：6
- 核验结果：`CurrentHealth / Max(MaxHealth, 1.0)` 后执行 `Clamp(0.0, 1.0)`，结果传给 `PB_PlayerHealth.SetPercent`。
- 边界处理：分母下限为 `1.0`，最终显示比例限制在 `[0.0, 1.0]`。
