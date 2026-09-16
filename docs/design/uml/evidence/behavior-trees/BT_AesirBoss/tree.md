# BT_AesirBoss 树结构

```text
Root
└─ Selector: Boss Decision
   ├─ Service: Update Boss State
   ├─ Sequence: Dead
   │  ├─ Decorator: IsDead is Set
   │  └─ Wait 0.2s
   ├─ Sequence: Stunned
   │  ├─ Decorator: IsStunned is Set
   │  └─ Wait 0.2s
   └─ Sequence: Engage
      ├─ Decorator: IsDead is Not Set [Abort Lower Priority]
      ├─ Decorator: IsStunned is Not Set [Abort Lower Priority]
      ├─ Decorator: TargetActor is Set
      ├─ Move To TargetActor [Acceptable Radius 180]
      │  └─ Service: Default Focus = TargetActor
      ├─ Boss Attack
      └─ Wait 0.6s
```

| 节点 | 类型 | 关键参数 | Node GUID |
| --- | --- | --- | --- |
| `Root` | Root | Blackboard = `BB_AesirBoss` | `4D39F82D4A87946F94F0A4B9F2C68ECF` |
| `Boss Decision` | Selector | 依次选择 Dead、Stunned、Engage | `3B5E2D6A491B1D9EF4BBFB9A39AFFF0F` |
| `Dead` | Sequence | `IsDead` 为 true 时等待 `0.2s` | `2C7E3D3945C606887CD00C8E2B622F2E` |
| `Stunned` | Sequence | `IsStunned` 为 true 时等待 `0.2s` | `AE0E6E494BC5D4FE67FB52B08490BEB3` |
| `Engage` | Sequence | 存活、未眩晕且有目标时移动、攻击、等待 | `F295B2C049710ECA5F4300A48410FD02` |
| Dead Wait | Task | `0.2s` | `D4D1C7B4428F7AB434BFB3B22EFA2E3F` |
| Stunned Wait | Task | `0.2s` | `2BFDADE844E0191766A078A25ED14F94` |
| `Move To` | Task | Key=`TargetActor`；Radius=`180`；Observe Blackboard=true | `80E9064B407137C7B54D8F9BF0629C5F` |
| `Boss Attack` | `UAesirBTTask_BossAttack` | 调用 Boss `TryAttack`，等待攻击结束 | `6F3EA6294117FEEEE377439C7FD33925` |
| Engage Wait | Task | `0.6s` | `A63D71D94D2038AA2447BE81B288F459` |
