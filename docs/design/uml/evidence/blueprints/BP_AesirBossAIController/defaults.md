# BP_AesirBossAIController Class Defaults

| 属性 | 当前值 | 业务影响 | 证据 |
| --- | --- | --- | --- |
| `BossBehaviorTree` | `BT_AesirBoss` | `OnPossess` 时由 C++ 调用 `RunBehaviorTree` | 用户编辑器核验；C++ 调用链交叉确认 |

## 证据

- 来源：用户在 Unreal Editor 中确认；`AAesirBossAIController::OnPossess` 源码交叉核验。
- 核验日期：2026-09-12。
