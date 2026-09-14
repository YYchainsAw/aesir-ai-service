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

## v0.3 世界快照与主入口样例（SDD T017）

| 文件 | 场景 | 用途 |
| --- | --- | --- |
| `world_snapshot_exploration.json` | 探索：新区域 + 可交互物（POI/草药） | `/v1/agent/step` 的 `world_context`；US3 自主行为判定输入 |
| `world_snapshot_camp.json` | 营地休整：夜晚、篝火 | 同上（时间驱动行为：提议休息） |
| `world_snapshot_idle.json` | 待机：深夜、下雨、无可交互物 | 同上（天气/时间触发 + 无候选时空动作） |
| `world_snapshot_danger.json` | 非战斗危险：深夜暴雨、玩家 35% HP、洞口 | 同上（危险自保优先级输入） |
| `agent_step_heartbeat_request.json` | 主入口心跳请求完整样例 | UE 直接照此结构上传 |
| `agent_step_heartbeat_response.json` | 心跳空动作响应样例 | 联调对照；字段变更须先改 v0.3 契约 |
| `world_event_region_first_entered.json` | 世界事件请求完整样例 | `/v1/world/events` 上传结构 |

世界快照 schema 见 `app/schemas/world_context.py`（契约细节待 v0.3 协议文档定稿，
SDD 见 `docs/planning/aesir-agent-sdd-v1.0.md`）。
