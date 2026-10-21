# NPC服务契约v0.3

> 2026-10-19按源码`a2dd426`校对。这里维护统一代理、世界事件、调试和回执的当前交界；需求目标见[SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)。本轮只修文档，未改变schema或执行运行验收。

云端身份、作用域与有效期见[v0.4契约](npc-scope-contract-v0.4-draft.md)和[第二步实施计划](../planning/step-02-identity-scope-plan.md)，已于2026-10-21批准并完成服务端实现及适用回归，随后合入main；配置/调用见[v0.4开发与交接](../guides/scoped-development.md)。旧入口仅在显式开发兼容模式开放，默认关闭。本页仍描述legacy v0.3，不能直接向旧请求添加scoped字段。

2026-10-21新增[远程部署目标](../guides/deployment.md)：v0.4已有开发身份、玩家/存档作用域与重置epoch子集；正式账号/HTTPS、数据库事务、版本同步、外部ASR和模型分发仍须分别验收。下表保留旧schema及兼容事实，不以旧入口限制概括新版。

同日采纳的[交互演进计划](../planning/npc-interaction-evolution.md)补轮次/取消、事件治理、TTS播放、来源记忆和持久幂等等完整目标。D1～C4及AT-EVO是计划/验收编号；新概念先核对v0.4已有字段，再按影响修改schema和golden，不向legacy请求混填。started/hit/completed、游标、TTS和取消等仍不因目标出现而成为当前API。

## 1. 端点与版本

API版本按端点解释；人格包0.2、统一指令格式0.3与健康接口的订单常量不是同一个版本号。v0.1/v0.2仍兼容，不能混用各自请求字段。

| 我想做什么 | 当前入口 | 请求/响应与边界 |
| --- | --- | --- |
| 文字闲聊 | `POST /v1/companion/chat`、`/chat/stream` | v0.1对话JSON/SSE，已注册角色；不产生战术订单 |
| 语音闲聊 | `POST /v1/companion/chat/voice` | multipart `audio`、角色、场景、可选会话/快照；返回对话及transcribed_text |
| 战斗文本指令 | `POST /v1/tactical/command` | v0.2 `text + combat_context`，L3；或v0.3 agent/step携带text和combat快照 |
| 旧订单解析/语音命令 | `/v1/commands/parse`、`/parse-command`、`/v1/voice/command` | v0.1 TacticalOrder；语音命令不是闲聊分流器。默认目录和门控差距见第7节 |
| 非战斗文本协作 | `POST /v1/agent/step`携带text | v0.3，按当前场景/目录解释follow、inspect、pickup、rest、wait等支持意图 |
| 心跳自主建议 | 同端点不传text | v0.3，L3、限频；服务不主动推送 |
| 游戏事实事件 | `POST /v1/world/events` | v0.3，按游戏档案声明事件；兼容combat/events仍用v0.2 |
| UE执行反馈 | `POST /v1/tactical/executions` | 单条/批量信封；每条回执当前版本0.2，202表示记录受理 |
| 查询/清理记忆 | `/v1/console/*` | 已注册角色；具体路由和部分失败见第5节 |

订单/对话和语音完整类型见[v0.1](ue-protocol-contract-v0.1.md)，战斗快照/意图/决策见[v0.2](combat-tactical-protocol-v0.2.md)。启动与接入步骤见[联调指南](integration-alignment-v0.3.md)。`GET /health`实际返回protocol_version=0.1和service_commit，前者不替代本表。

## 2. agent/step

请求由[AgentStepRequest](../../app/schemas/agent_step.py)定义：`protocol_version`为0.3，`request_id`为UUID，`companion_id`和`world_context`必填；可选`text`为1～500字符，`session_id`最多128字符。纯心跳不传text，空字符串不是心跳而是422。请求和响应配置extra=forbid。

```json
{
  "protocol_version": "0.3",
  "request_id": "99d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "companion_id": "companion.alice",
  "world_context": {
    "snapshot_id": "22222222-2222-4222-8222-222222222222",
    "captured_at": "2026-10-08T12:00:00Z",
    "scene": "exploration",
    "player": {"id": "party.player", "hp_percent": 80},
    "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70}
  }
}
```

响应字段为`protocol_version/request_id/companion_id/action/directive/reply_text/observability`：

- **action只允许`none|directive`**。无动作或澄清都可用none及reply_text/原因码表达，没有reply或idle动作枚举。
- directive是[DirectiveEnvelope](../../app/schemas/directives/common.py)：UUID directive_id、agent_id、domain、action_type、0～100的priority、expires、source、reason_codes、policy_revision、payload及可选presentation。domain是`combat/exploration/camp/conversation/idle`场景；行为类型为五类行为白名单的并集，不与domain枚举混为一层。
- expires为`immediate/encounter_end/before_seconds`，后者含非负remaining_seconds。source为`player_command/autonomy/event/fallback`。普通非施法可不引用技能，需要技能时必须引用获准能力，数量尚未冻结；不在本轮文档中虚构新的技能数组字段。
- observability含`source=rule|llm|rule_fallback`、原因码、策略/人格版本、使用快照、degraded、关系阶段/展示名和memory_layers。它们解释来源，不证明UE已执行。

玩家text分支复用意图解析：战斗意图需要world_context.combat，缺少时none + COMBAT_CONTEXT_MISSING；非战斗意图按场景、目录与可交互目标校验。无法识别时none + INTENT_UNRECOGNIZED并澄清。纯心跳按“禁打断→候选→目录→仲裁→节流”产生一个建议或无动作，默认同角色最小间隔2秒，超频429。配置和重启语义见[启动指南](../guides/getting-started.md)。

## 3. 世界事件与幂等

[WorldEventRequest](../../app/schemas/world_event.py)包含版本0.3、字符串request_id、companion_id、event和world_context。event有非空event_id、枚举event_type、occurred_at、非负sequence及字符串字典details；request_id当前不是UUID类型，不能把agent/step的UUID校验推广到此端点。

事件类型为六类战斗事件及六类生活事件：`region_first_entered/weather_changed/gift_given/companion_recovered/player_protected_companion/promise_kept`。先验证角色及当前游戏事件声明；未知角色404，未声明事件403，不合法枚举/结构422。服务使用事实更新记忆/关系，不从玩家一句请求推定游戏事件已发生。

响应包含event_id、duplicate、reaction、recommendation_text、可空companion_action及observability。companion_action当前仍是v0.2 DecisionAction，不是统一DirectiveEnvelope；生活事件没有可执行动作。关系变化、原因码和阶段按实际路径返回。

- 战斗键为`(companion_id, encounter_id, event_id)`，生活键的遭遇部分为空串；与combat/events共享1024项进程内缓存，锁内完成首次评估。
- 重试同一事实保留event_id。命中缓存回放首次反应/动作并标duplicate，不新生成order_id；不同角色或遭遇分别处理。
- 缓存淘汰最旧项，服务重启即丢失；不承诺永久恰好一次。UE仍对动作ID执行去重，并检查旧游玩、有效期、目标和当前状态，避免重放动作。

## 4. 执行回执

实际schema为[ExecutionReceiptRequest](../../app/schemas/tactical_execution.py)。信封为receipt或非空receipts二选一，可选game_id（默认aesir）；**信封没有protocol_version字段**。每条回执的protocol_version固定0.2，order_id/encounter_id为非空字符串，result为下表枚举；可选request_id、reason_code、agent_id、ability_id、reported_at、received_at、policy_revision、非负sequence。

```json
{
  "receipt": {
    "protocol_version": "0.2",
    "order_id": "99d7e6b4-f4f2-4d39-8c96-a23d293882f6",
    "encounter_id": "enc.demo.001",
    "result": "rejected",
    "reason_code": "UE_TARGET_GONE"
  }
}
```

| result | 当前可表达的事实与边界 |
| --- | --- |
| accepted | 登记/受理；不是启动、命中或完成 |
| executed | UE报告动作实际执行；具体算启动还是完成需在联调约定，不能用此枚举证明每个阶段 |
| rejected / expired / cancelled | UE报告拒绝、过期或取消及原因 |

成功返回202 + stored，单条含order_id，批量含count/order_ids，并带实际path。按UTC天追加`data/runtime/command_service/executions/<game_id>/<YYYYMMDD>.jsonl`，缺received_at由服务端补齐。当前存储只追加，不核验动作是否真的发生，不去重/合并乱序或维护状态机，也不自动用于训练。

“接收→启动→命中/完成”按真实适用阶段反馈是需求目标；当前没有started/hit/completed枚举。directive_id到order_id的跨端映射、适用阶段、终态、重复/乱序处理仍需两端确认，不新增假字段或把accepted称终态。回执game_id未绑定当前进程游戏、agent_id未强制注册，是已登记实现差距。

## 5. 调试与记忆重置

| 实际路由 | 输入与结果 |
| --- | --- |
| `GET /v1/console/state?companion_id=...` | 当前运行观测、注册角色、人格/策略版本、关系及近期记忆；最近状态不代表任意历史决策的完整解释 |
| `GET /v1/console/memory?companion_id=...` | 指定角色的四层记忆视图；存储读取失败503 |
| `POST /v1/console/memory/reset` | JSON仅指定companion_id；先清该角色会话，再清持久记忆，返回companion_id/reset/cleared_sessions |
| `GET /v1/console/ui` | 内联调试HTML；当前页面用Alice作为初始查询，其他游戏的首个角色适配仍有差距 |

这些操作先查注册角色，未知/跨游戏角色404。reset不重建人格、不重置关系、不清对话信号或回执日志，也不能证明远端LLM/ASR数据已删除。持久清理失败时返回reset=false，会话可能已清，不承诺回滚或原状态不变。无需为此新增UE重置按钮。

当前没有`/v1/console/relationship/*`通用读写API；关系可从state读取，不能把曾经的通配写法当已实现路由。调试接口默认无额外认证，仅适用当前本机开发边界；不要从监听回环推断外部LLM没有出站数据。

## 6. 错误与版本边界

| 结果 | 实际含义 |
| --- | --- |
| 200 + none/not_actionable等 | 合法请求但未给动作，不当成已执行或网络失败 |
| 202 | 回执记录受理，不证明动作或完整闭环 |
| 403 | 已配置的L3或游戏事件门控拒绝，detail带原因码；不表示每个旧端点都有同样门控 |
| 404 | 角色检查路径发现未知角色；不笼统保证所有v0.1/v0.2旧入口均返回同样404 |
| 422 | 模型实际验证的版本、类型、枚举、必填/长度等错误；forbid按各模型配置，不是全局机制 |
| 429 | 纯心跳间隔过短 |
| 502/503及其他错误 | ASR、人格/存储等路径的故障；解析LLM有回退，不等于所有I/O和配置错误都受控 |

agent/step与world/events顶层配置extra=forbid；v0.1对话及嵌套订单也有forbid。部分v0.2请求/快照和回执模型未配置，顶层额外字段可被忽略；回执order_id、世界request_id等也未统一强制UUID。若规范需收紧，先登记实现任务并评估旧客户端兼容，不以改文字冒充校验已完成。

## 7. 当前实现差距

| 目标 | 当前限制与接入处理 |
| --- | --- |
| 游戏/角色/能力隔离 | agent/step、world/events、对话/console有角色检查；旧parse/voice默认目录、v0.2战术与回执没有同等全面的角色/当前游戏绑定。正式接入显式提供当前目录，不能用L3门控替代逐角色授权 |
| 统一身份及阶段回执 | directive/order映射与阶段/终态待对齐；当前只存回执，不能宣称状态机已实现 |
| 幂等与旧局隔离 | 服务有限缓存与UE执行去重分开；UE必须检查游玩/遭遇/请求及有效期，不把重试等同清NPC长期状态 |
| 参数/性能 | 心跳2秒是配置；历史单次HTTP耗时不是P95。硬件、样本、计时边界与正式阈值按SDD/联调口径冻结 |
| 数据保留 | 无session仍可持久化，默认信号含完整文本；LLM可出站。允许字段/后端、保留/删除范围见[LLM指南](../guides/llm-integration.md)，未决定部分明示待确认 |

## 8. 来源与维护

本页按现存schema/路由静态核对，不否认2026-10-08在8000实例取得的历史HTTP样本；单次结果和环境见[联调记录](integration-alignment-v0.3.md#历史实测与适用范围)。当前默认8011，不全局改写历史端口。规则变更同步SDD、模型、对应契约及验收；历史材料和当前规范分别标识。
