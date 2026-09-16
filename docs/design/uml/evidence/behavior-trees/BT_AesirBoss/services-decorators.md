# BT_AesirBoss Services / Decorators

| 所属节点 | 名称 | 类型 | 参数/条件 | Node GUID |
| --- | --- | --- | --- | --- |
| `Boss Decision` | `Update Boss State` | `UAesirBTService_UpdateBossState` | 每 `0.2s` 写入 `TargetActor=GetPlayerPawn(0)`、`IsStunned`、`IsDead`；Random Deviation=`0` | `21A2E7D24491C34226D4D59E83912AB8` |
| `Dead` | `IsDead?` | Blackboard Decorator | `IsDead is Set` | `6EF575FC4EC1709D1EEE10A1E82A641C` |
| `Stunned` | `IsStunned?` | Blackboard Decorator | `IsStunned is Set` | `4A099BF54395851076B466B12565330D` |
| `Engage` | `IsDead?` | Blackboard Decorator | `IsDead is Not Set`；Flow Abort=`Lower Priority` | `431531534CCC32E41CBF91A02AFD5EE1` |
| `Engage` | `IsStunned?` | Blackboard Decorator | `IsStunned is Not Set`；Flow Abort=`Lower Priority` | `A7DBC67745AF851CC2062ABBB7EC7449` |
| `Engage` | `IsTargeted?` | Blackboard Decorator | `TargetActor is Set` | `7098056A44C8BF5C1A23938A9271EB03` |
| `Move To` | `Default Focus` | `UBTService_DefaultFocus` | Key=`TargetActor` | `8104716644C0CC522BDE9DA3BC064DB6` |
