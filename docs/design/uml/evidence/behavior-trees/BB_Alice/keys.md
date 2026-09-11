# BB_Alice Keys

| Key 名称 | Key 类型 | Base Class/Enum | Instance Synced | 默认值 | 写入节点 | 读取节点 | 业务含义 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `SelfActor` | Object | 截图未显示 | 否 | 截图未显示 | UE Blackboard 运行时提供，具体来源待核验 | 当前已提供的 `BT_Alice` 节点未读取 | 当前 Blackboard 所属 AI 的自身 Actor |
| `TargetActor` | Object | `Actor` | 否 | `None` | `BTS_AliceUpdateTarget.ReceiveTickAI` 写入 `GetPlayerController(0)` | `TargetActor Is Set` Decorator；`Move To` Task | Alice 当前跟随的目标 Actor |

## 核验结论

- Blackboard 中当前仅有 `SelfActor` 和 `TargetActor`。
- 未发现战术订单、技能 ID、优先级或命令状态相关 Key。
- 仅凭 Blackboard 不能证明 `UTacticalOrderComponent` 已接入行为树。
- `TargetActor` 的写入方和读取方已经通过 `BT_Alice`、`BTS_AliceUpdateTarget` 的节点文本确认。

## 证据范围

- 来源：用户提供的两张 Unreal Editor 截图
- 核验日期：2026-09-11
- 未在截图中显示的字段保持“待核验”，未使用默认经验值补填
