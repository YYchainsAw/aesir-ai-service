# BT_Alice Services 与 Decorators

| 所属节点路径 | 类型 | 节点名称/类 | Blackboard Key | Abort Mode | 关键默认值 |
| --- | --- | --- | --- | --- | --- |
| `Root/Alice Decision` | Service | `BTS_AliceUpdateTarget` | `TargetActor` | 不适用 | Interval `0.25s`；Random Deviation `0.0s` |
| `Root/Alice Decision/Follow Player` | Decorator | `BTDecorator_Blackboard`：`TargetActor Is Set` | `TargetActor` | `Both` | Notify Observer `On Value Change` |
