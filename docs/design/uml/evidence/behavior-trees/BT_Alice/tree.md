# BT_Alice 节点层次

```text
Root
└─ Selector: Alice Decision
   ├─ Service: BTS_AliceUpdateTarget
   │  ├─ TargetActorKey = TargetActor
   │  ├─ Interval = 0.25 s
   │  └─ Random Deviation = 0.0 s
   └─ Sequence: Follow Player
      ├─ Decorator: TargetActor Is Set
      │  ├─ Notify Observer = On Value Change
      │  └─ Observer Aborts = Both
      ├─ Task: Wait
      │  └─ Wait Time = 0.5 s
      └─ Task: Move To
         ├─ Blackboard Key = TargetActor
         ├─ Acceptable Radius = 250.0
         └─ Observe Blackboard Value = true
```

## 节点 GUID

| 节点 | Node GUID |
| --- | --- |
| Root | `D10A438E40E7267EDBCBD89EDC415D0F` |
| Selector `Alice Decision` | `D0C45B4C465EAD12559724B851414514` |
| Sequence `Follow Player` | `BB4C88B74EDC95F30D9209BB7F4DB715` |
| Task `Wait` | `497D033949530D198B55D782E0773503` |
| Task `Move To` | `4D981A5441A9B31177AF359D3A2DE97C` |
| Service `BTS_AliceUpdateTarget` | `BC99EB8941AA8B66E5EEA7BA17405E5E` |
| Decorator `TargetActor Is Set` | `0C8F1D8E469F9FE688CA778BF6CBBB44` |

## 当前范围结论

- 当前 Selector 只有 `Follow Player` 一个业务分支。
- 当前行为树没有读取 `UTacticalOrderComponent`、订单 ID、技能 ID 或优先级。
- 当前行为树没有攻击、治疗、施法、撤退或条件施法任务。
