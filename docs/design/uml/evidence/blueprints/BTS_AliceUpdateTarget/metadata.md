# BTS_AliceUpdateTarget 元数据

- Asset Path: `/Game/Aesir/AI/Companions/BTS_AliceUpdateTarget`
- Parent Class: `UBTService_BlueprintBase`
- 实现事件: `ReceiveTickAI`
- Node Name: `BTS_AliceUpdateTarget`（行为树实例使用的资产名）
- Interval: `0.25s`（`BT_Alice` 中的实例值）
- Random Deviation: `0.0s`（`BT_Alice` 中的实例值）
- 核验日期: 2026-09-11
- 对应 UE 提交: `dead903156946ec6956342f02d587612baab1717`

## Blackboard Key Selectors

| 属性名 | 实际 Key | Key 类型 | 用途 |
| --- | --- | --- | --- |
| `TargetActorKey` | `TargetActor` | Object (`Actor`) | 每次 Service Tick 写入玩家控制器 |

## EventGraph 执行链

```text
ReceiveTickAI
└─ SetBlackboardValueAsObject
   ├─ Key   = TargetActorKey（BT 实例选择 TargetActor）
   └─ Value = GetPlayerController(PlayerIndex = 0)
```

## 节点 GUID

| 节点 | Node GUID |
| --- | --- |
| `ReceiveTickAI` | `05BCAEA041A96991283E559D2839E38E` |
| `SetBlackboardValueAsObject` | `66FCB0A24C4B1FF05FEE02907B632C0F` |
| Get `TargetActorKey` | `B68E853A49A27480F59E8C9E212D912F` |
| `GetPlayerController` | `4AF241CA4CA9B5D3903FCA919BCED409` |

## 核验备注

- `OwnerController`、`ControlledPawn`、`DeltaSeconds` 在当前 Graph 中没有连接。
- 写入 `TargetActor` 的对象是 `PlayerController(0)`，不是 `GetPlayerPawn(0)`。
- 该 Service 只负责跟随目标更新，不读取战术订单。
