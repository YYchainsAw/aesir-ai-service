# BB_Alice 元数据

- Asset Path: `/Game/Aesir/AI/Companions/BB_Alice`
- Parent Blackboard: `None`
- Key 数量: 2（`SelfActor`、`TargetActor`）
- 核验日期: 2026-09-11
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## 证据

- 来源：用户提供的 Unreal Editor Blackboard 面板和 Key Details 截图
- 已确认：Key 名称、Key 类型、`TargetActor` Base Class、Instance Synced、Parent
- 已确认：`TargetActor` 在 `BTS_AliceUpdateTarget` 中写入，并由 Decorator 与 `Move To` Task 读取
- 尚未确认：`SelfActor` 是否被当前范围以外的节点读取
