# NPC与UE联调指南

> 当前说明按2026-10-19服务源码`a2dd426`整理。这里维护启动、接入检查和历史样例边界；字段以[NPC契约v0.3](npc-contract-v0.3.md)、[v0.2战术](combat-tactical-protocol-v0.2.md)、[v0.1订单/对话](ue-protocol-contract-v0.1.md)为准。需求与真实验收见[SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)。

> 部署目标更新（2026-10-21）：[15 项分工对照](../planning/ai-capability-placement.md)已明确 Boss 本地、队友语义与长期状态云端；下表 `127.0.0.1` 是当前默认/开发接入地址，不表示正式 NPC 仍需随游戏本机运行。当前服务器开发实例及 SSH 转发见[远程开发指南](../guides/remote-development.md)；部署目标不自动改变任何现有协议字段或版本。

## 当前实例与版本

| 实例 | 默认地址 | 接入边界 |
| --- | --- | --- |
| NPC本服务 | `http://127.0.0.1:8011` | `python -m scripts.run_server`读取Settings；与UE两个Subsystem的现有默认值对齐 |
| Boss RL独立服务 | `http://127.0.0.1:8012` | 独立进程，不共用NPC启动命令；部署与研究见[RL入口](../../rl/README.md) |
| 第二游戏样例 | 自行指定，如8002 | `AESIR_GAME_ID=demo-vn`，独立进程与端口，不能混用当前游戏目录 |

```powershell
.\.venv\Scripts\python -m scripts.run_server --reload
curl.exe http://127.0.0.1:8011/health
```

默认8011自FIX-10对齐；环境或`--port`可覆盖。不要直接运行未传端口的uvicorn后又访问8011。配置变更重启服务，操作细节见[启动指南](../guides/getting-started.md)。

`/health`当前返回status、service、protocol_version=0.1及service_commit。commit为运行进程读取后缓存的short SHA，非Git环境为unknown；不能用本机当前HEAD替代服务返回，也不能用health版本替代每端点版本。一次联调记录服务commit、UE代码/构建、地图/资产、后端、配置、两端地址和实际时间，不把历史端口或样本复制成当前结果。

## 按交互选择入口

| 交互 | 请求入口 | UE接收后做什么 |
| --- | --- | --- |
| 文字/语音闲聊 | companion/chat、chat/stream、chat/voice | 文本和表现ID按响应展示，流式以meta为权威；语音闲聊不用voice/command |
| 旧文本/语音订单 | commands/parse、voice/command | 显式提供当前能力目录；返回v0.1判别联合，先核验再登记 |
| 战斗上下文指令 | tactical/command，或agent/step携带text与combat | 按对应DecisionAction或DirectiveEnvelope解释，不混用两种信封 |
| 非战斗协作/心跳 | agent/step带text/不带text | action只有none/directive；无动作保持本地活动，不能当故障强执行 |
| 事实事件 | world/events；旧combat/events仍兼容 | 同一事实重试复用event_id，回放动作另做执行去重 |
| 执行反馈 | tactical/executions | 只报告实际阶段/原因；202及accepted不当动作完成 |
| 调试和记忆清理 | console/state、memory、memory/reset、ui | 指定当前注册角色；reset不重建角色，部分失败如实处理 |

一进程一游戏；角色、目标和能力来自本次有效上下文，非施法可不含技能，需要技能时必须获准，数量尚未冻结。旧语音默认目录、v0.2逐角色校验及回执game_id绑定未完全覆盖，见[实现差距](npc-contract-v0.3.md#7-当前实现差距)。接口存在不等于这些保护都已在UE生效。

## 端点×版本×必填字段速查表（T47/#64）

> 实测踩坑汇总：UE 侧若用同一结构体复用，必踩 422。每个端点的 `protocol_version`
> 是**字符串字面量**，不能混用；`world_context.scene` 枚举不含 `night`/`dungeon`
> （夜间属于 `world_time.time_of_day`，不是 scene）。

| 端点 | protocol_version | 必填字段 | 常见 422 踩坑 |
| --- | --- | --- | --- |
| `POST /v1/agent/step` | `"0.3"` | `request_id`（UUID）、`companion_id`、`world_context` | 传 `"0.2"` → 422；`text: ""` 不是心跳，是 422 |
| `POST /v1/world/events` | `"0.3"` | `request_id`（字符串，非 UUID）、`companion_id`、`event.event_id`、`event.event_type`（枚举）、`event.occurred_at`、`event.sequence`（单调递增 int）、`world_context` | `event_type` 拼错（如 `low_hp_warning` → 应为 `player_hp_critical`）；缺 `sequence`；payload 字段名是 `details` 不是 `payload` |
| `POST /v1/tactical/command` | `"0.2"` | `request_id`、`companion_id`、`text`、`combat_context` | 传 `"0.3"` → 422（本端点仍是 v0.2）；`combat_context` 缺 `mode: "combat"` / `encounter_id` / `boss` / `ability_states` → 422 |
| `POST /v1/companion/chat` | 无版本字段 | `companion_id`、`text` | — |
| `POST /v1/tactical/executions` | 每条回执 `"0.2"` | `order_id`、`encounter_id`、`result` | 信封本身无 `protocol_version` 字段；`result` 枚举仅 `accepted/executed/rejected/expired/cancelled` |

### `world_context.scene` 合法值

`combat` / `exploration` / `camp` / `conversation` / `idle`——**没有 `night`**。
夜间属于 `world_time.time_of_day`（`morning/noon/evening/night`），天气属于
`world_time.weather`（`clear/rain/snow/storm/fog`）。

### `combat_context` 必填字段（tactical/command 专用）

```json
{
  "snapshot_id": "...",
  "captured_at": "...",
  "encounter_id": "encounter.demo.001",
  "mode": "combat",
  "player": {"id": "party.player", "hp_percent": 80, "distance_to_boss_m": 12.0},
  "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 5, "ability_states": {"ability.alice.shield": "ready"}},
  "boss": {"id": "encounter.primary_hostile", "hp_percent": 100, "state_tags": []}
}
```

缺 `mode` / `encounter_id` / `boss` / `ability_states` 任一字段 → 422。

### 版本统一路线

2026-10-21 补充：带玩家/存档作用域的云端入口拟采用[v0.4契约草案](npc-scope-contract-v0.4-draft.md)，已于2026-10-21批准；下述旧路线保留为历史目标，实际实现版本仍按上表。第二步先做服务端契约与模拟客户端验收，不要求现在修改UE或测试连接。

`tactical/command` 仍是 v0.2，`agent/step` 与 `world/events` 是 v0.3。长期目标是
把 tactical/command 也升到 v0.3 统一信封，但这涉及 UE 侧结构体改造，不在本轮范围。

## 接入顺序与通过条件

以下从旧UE集成指南合并有效步骤，按风险推进；每步都记录实际结果，不预勾完成。

| 顺序 | 检查场景 | 通过条件 |
| --- | --- | --- |
| 1 服务可达 | 正常/服务关闭/地址错；核对health与端点版本 | 正确地址和commit可定位；失败有原因且UE主线程不被网络阻塞 |
| 2 纯文本订单 | v0.1五类golden、未知type/非法字段；同request_id回显 | UE按支持的类型解析，unsupported明确拒绝，不由HTTP200推定可执行 |
| 3 执行前七项 | 版本→角色存在/可控/存活→已实现类型→能力目录→目标可解析→有效期/优先级→触发时目标/冷却/资源/距离/忙碌 | 任一失败不动作且可关联原因；普通日常无技能不被误拒绝 |
| 4 世界身份 | 战斗结束、重试/返回后释放旧回包；重复请求或回执 | 旧游玩/遭遇/请求不污染当前世界，重复动作仅执行一次；服务缓存不替代UE检查 |
| 5 上下文战术 | 同一句治疗/爆发意图在不同快照；无技能/冷却/目标失效 | 合法建议经UE当前状态复核；不可执行清楚拒绝，不绕过GAS制造伤害 |
| 6 首个动作闭环 | 用实际已制作能力完成一次建议→UE启动/实际结果→回执 | 指令/订单ID与事实关联，接收、启动、命中/完成不混写；没有真实结果就不报告完成 |
| 7 语音 | 先mock验证上传，再用faster_whisper；空音频/转写失败/含糊文本 | 失败可改文本；语音使用当前角色/目录，不用默认Alice目录冒充授权；按约定WAV格式检查 |
| 8 心跳/事件 | 超频/过期/禁打断/无候选；同事件并发/跨端点重放/重启 | 建议或none符合场景；重复不重复计分/动作；如实说明1024项内存缓存与重启限制 |
| 9 查询/重置 | 指定角色与未知角色；注入持久记忆清理失败 | 未知角色拒绝；清目标记忆保留人格/关系/其他角色，失败可能会话已清，不能假称回滚 |
| 10 故障/构建 | LLM/ASR/存储失败、服务离线、Windows目标运行 | 本地游戏仍可结算/重试/菜单/退出；API、UE执行及Windows包分别有证据 |

能力资产以实际UE目录为准。2026-10-08核查起点UE`facba39`曾登记basic_attack/explosion为制作项，治疗/护盾尚未制作；这不是2026-10-19每份本地工程的当前能力清单。重新核对实际DataAsset与SupportedAbilityIds，不由Python声明全集推断UE有实现，也不从heartbeat成功推断战斗施法已通。

## 性能采样与正式验收

SDD的战斗P95<3秒、自主判定P95<1秒（无产出<100毫秒）、纯规则<100毫秒是需求口径；SC-011在T33/FIX-04另定义规则指令“UE输入到NPC开始可见响应”的P95≤300毫秒。它们边界不同，分别采集，不相互替代。

- SC-011起点t0为UE确认文本输入/发出语音请求，终点t1为UE收到响应且首次实际动作/语音/动画开始；两端打戳，另记服务处理分段，避免把仅HTTP返回当NPC开始。
- 既有T33计划为同一遭遇至少30条、文本与语音各半，覆盖不同意图；固定机器/地图/构建/后端并保存每个原始t1−t0、失败/超时样本。治疗等未制作能力不能伪造执行样本，先闭合可测意图及条件。
- LLM生成回复单独统计，不混进规则SC-011；规则P95与端到端目标都需注明计时边界。少量历史HTTP耗时不是当前正式P95。
- metrics_report的PASS包含覆盖/采集代理，不自动等于SC需求成立。完整记忆正确率、语气、隔离和UE执行需对应人工/运行材料；当前生产对话记录未自动填充latency_ms，不能承诺再聊一轮就得到SC-011结果。

## 历史实测与适用范围

保留旧对齐记录的日期和环境：服务核查起点`75ac7a3`、UE`facba39`；2026-10-08运行实例端口8000，后续FIX-10将当前默认改8011。以下为当时记录的单次HTTP样本，本轮未重新运行、不升级成当前全部能力验收。

| 当时链路 | 记录结果 | 可以说明什么 |
| --- | --- | --- |
| companion/chat | 200，2328.8ms，source=llm | 当时LLM对话样本 |
| tactical/command | 200，19.3ms，规则actionable，PLAYER_HP_CRITICAL | 返回候选，不证明UE治疗执行 |
| agent/step | 200，31.8ms，自主observe | 当时API心跳样本，不证明UE全部行为已接通 |
| world/events | 200，27.5ms，gift_given，delta=3 | 当时事件/关系API路径 |
| executions单条/批量 | 202，4.1/3.5ms | 当时落盘受理，不证明动作结果真实 |
| 未登记角色/违规结构/L0门控 | 404/422/403 | 对应当时具体端点和样本，不推广为所有模型统一门禁 |

后续记录按[复现手册](../guides/repro.md)保存实际输入/输出、版本和范围。课程模型、服务测试、真实LLM样本、UE指令执行与正式性能各自标状态，不把历史API样本当组装后的最终演示。两仓实现/需求差异先登记再修复，不改写过去记录使其看起来已经验收。


## v0.4分支接入边界

`feature/npc-scope-v04`已完成新版作用域JSON入口与适用服务端回归，见[v0.4契约](npc-scope-contract-v0.4-draft.md)和[开发与交接](../guides/scoped-development.md)。本页旧入口只在`AESIR_SCOPE_LEGACY_ENABLED=true`的显式开发兼容模式可用，默认关闭；UE结构体/生命周期接入与实际执行仍待第三步，不向旧请求混入新字段。
