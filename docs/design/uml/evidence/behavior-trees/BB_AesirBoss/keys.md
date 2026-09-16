# BB_AesirBoss Keys

| Key 名称 | Key 类型 | Base Class / Enum | Instance Synced | 默认值 | 写入方 | 读取方 |
| --- | --- | --- | --- | --- | --- | --- |
| `TargetActor` | Object | `Actor` | `false` | `None` | `Update Boss State` | `Engage` Decorator、`Move To`、`Default Focus` |
| `IsStunned` | Bool | 不适用 | `false` | 截图未展开该项 | `Update Boss State` | `Stunned`、`Engage` Decorator |
| `IsDead` | Bool | 不适用 | `false` | 截图未展开该项 | `Update Boss State` | `Dead`、`Engage` Decorator |

## 证据与边界

- `TargetActor`：Object、Base Class=`Actor`、Default=`None`、Instance Synced 未勾选。
- `IsStunned`、`IsDead`：Bool、Instance Synced 未勾选；截图没有展开 Bool 默认值。
- 三张截图均显示 Parent=`None`。
- 截图文件：`codex-clipboard-d47291ed-c31c-4b8a-8677-bbafb045519a.png`、`codex-clipboard-2ed8903e-dd29-4841-b05c-3b7eb13c46a1.png`、`codex-clipboard-3284feb8-3710-449a-bfdc-47826761bb47.png`。
- 核验日期：2026-09-12。
- 当前截图没有包含左侧完整 Key 列表，因此不能排除存在其他 Key。
