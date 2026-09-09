# golden 快照（UE 联调 fixture）

四份 `CombatContext` 快照与回归评测集（`tests/services/test_tactical_regression.py`）
的 A/B/C/D 四类战况同源，覆盖状态空间的四个象限：

| 文件 | 战况 | 预期差异（同一句"帮我回一下血"） |
| --- | --- | --- |
| `snapshot_a_critical.json` | 濒危贴脸：玩家 HP 18、贴 Boss | 强效治疗 `major_heal`，priority 95 |
| `snapshot_b_steady.json` | 稳态消耗：玩家 HP 65、无特殊状态 | 快速治疗 `quick_heal` |
| `snapshot_c_stun_window.json` | 眩晕窗口：Boss 眩晕剩 4.5s | 爆发优先；`boss_stunned` 事件返回集火 |
| `snapshot_d_resource_dry.json` | 资源枯竭：艾莉 MP 10、爆裂/强疗 CD | `not_actionable` + 资源原因码 |

用法：UE 直接把文件内容作为 `/v1/tactical/resolve` 的 `combat_context` 字段、
或 `/v1/combat/events` 的快照上传；也可以用 `scripts/mock_ue_flow.py` 一键全链路演示。
修改字段须先改 `docs/protocols/combat-tactical-protocol-v0.2.md` 再改本目录。
