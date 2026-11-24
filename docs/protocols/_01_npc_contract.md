# NPC 服务协议

当前协议由 scoped v0.4 基础与 v0.5 文本异步增量组成。v0.5 不改变语音和控制接口的 v0.4 形状；legacy v0.1/v0.2/v0.3 仅作为仍受门禁保护的兼容入口。人格包 Schema 独立维护。

## 阅读入口

条目来源与授权遗忘：见[新增管理操作](#memory-management)，包含 entries/forget 路由、epoch 屏障与 trace 标签边界。

- [身份与作用域](#scope)
- [请求与回执](#loop)
- [持久化与恢复](#persistence)
- [异步提交](#async)
- [旧代理接口](#legacy-agent)
- [旧战术接口](#legacy-tactical)
- [旧订单/对话/SSE](#legacy-dialogue)

兼容章节保留对应有效字段，不表示这些旧接口默认开放。当前请求结构以运行实例 OpenAPI 和 schema 为准。


<a id="scope"></a>
## v0.4 身份、作用域与时效

<a id="scope-npc身份与有效期契约v04草案"></a>
### NPC身份与有效期契约v0.4草案

> 2026-10-21，按服务器工作区 `main@93d9d6c` 的现有实现设计。**已按批准方案完成服务端实现与适用回归，并经PR #74合入main；UE接入待第三步验收。** 本页对应[六步方案](../planning/_02_delivery_plan.md)第二步；现行scoped JSON字段以本页、对应schema及golden为准；旧格式仅见[legacy v0.3及其引用的兼容契约](_01_npc_contract.md#legacy-agent)。原开发分支为 `feature/npc-scope-v04`，实际结果见[验证记录](../records/_01_verification_records.md#scope-20261021)；文件名保留draft便于既有链接兼容，不表示可以省略服务端/UE验收。

<a id="scope-1-范围与已批准决策"></a>
#### 1. 范围与已批准决策

v0.4为队友服务增加可信身份、玩家/存档作用域、游玩绑定、相对有效期和明确的重复请求规则。Python仍返回建议，UE保留当前世界、动作合法性和实际执行权；Boss Schema 4、26维观测与9动作不变。

本阶段使用Python 3.12、FastAPI/Pydantic、标准库UUID/单调时钟、单worker和分区JSON。数据库、正式账号/令牌、离线事实同步、真实语音及UE实际联调分别在后续阶段验收；不能因本页定义字段而宣称这些能力已具备。

| 决策 | 本草案提案 | 审查状态与边界 |
| --- | --- | --- |
| DEC-SCOPE-01 | 同一存档死亡重试保留长期记忆和关系，只替换游玩身份并清单局状态 | 2026-10-21已批准；不新增持久存档界面或检查点。未来分支读档按新存档世代隔离，不能只换run来回滚长期状态 |
| DEC-SCOPE-02 | 每个玩家/存档同一时刻只有一个活动run | 2026-10-21已批准；显式替换使旧绑定失效，不由最后到达的普通请求抢占 |
| DEC-SCOPE-03 | 新增显式scoped入口承载v0.4；旧v0.1/v0.2/v0.3仅在开发兼容模式进入独立legacy作用域 | 2026-10-21已批准；严格模式拒绝旧入口旁路，不静默映射匿名玩家或默认存档 |

上述决策已于2026-10-21由用户审查通过。日常任务与完成状态由GitHub Issues维护；本文只维护字段、规则和验收定义，不另建进度看板。 实现工作包与依赖见[第二步实施计划](../planning/_03_identity_scope_plan.md)，执行入口为[DEP2里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/6)。

<a id="scope-2-身份与数据归属"></a>
#### 2. 身份与数据归属

| 标识 | 来源与规则 | 生命周期 |
| --- | --- | --- |
| game_id | 当前进程配置；请求不能切换到另一游戏 | 服务实例配置 |
| player_id | 可信身份提供器解析的主体，不接受请求体自报身份或未经验证的header | 玩家主体；开发期仅固定预登记身份和测试替身 |
| save_id | UUID，须属于当前主体；测试/开发档案显式预登记 | 独立游戏进度。普通重试不更换；新进度/分支世代另建ID |
| companion_id | 当前游戏已登记角色，如companion.alice | 角色目录标识，不是玩家身份 |
| run_id | UUID，代表一次游玩；激活须走第3节控制入口 | 重试、重新开始或读档建立新run；同档长期状态按DEC-SCOPE-01保留 |
| session_id | UUID，可省略；省略时使用run_id，不截断或拼接客户端字符串 | 一段对话；独立重置聊天时可更换；不能跨run复用短期历史 |
| encounter_id | 战斗请求必填，绑定当前run；同一遭遇的两条上报通道使用同值 | 本场物理战斗；不得以角色名或战斗布尔值代替 |
| request_id / event_id | 请求和事实事件的稳定逻辑标识；新契约统一UUID | 网络重试复用原ID；两者不能互相代替 |
| directive_id / order_id | 沿用对应建议/订单的标识，并记录明确关联 | 一条逻辑建议；回执不重新生成动作ID |
| snapshot_id | 客户端采集的快照UUID，响应回显实际使用值 | 一份观察；重试不伪造新快照来续期 |

世界对象 `party.player`、`encounter.primary_hostile` 和角色ID仍用于目标引用，不是已认证主体。所有ID先经类型、长度、目录/归属检查，再交给存储；不能直接把任意字符串作为文件路径。

内部统一使用不可变的请求上下文：可信 `game_id/player_id`、已授权 `save_id/companion_id`、有效run绑定、会话/遭遇以及请求时效。路由只解析一次，服务层、存储、缓存与观测均使用该上下文；不能只有agent/step隔离而chat、事件或console仍按全局角色工作。

| 数据/能力 | 作用域与说明 |
| --- | --- |
| 长期记忆、关系 | game + player + save + companion；两种状态保持独立重置边界 |
| 短期对话 | 上述归属 + run + session；缺省session=run |
| 心跳、自主节流、最近观测 | 上述归属 + run；配额和去重不可相互串玩家 |
| 请求去重 | 上述归属 + run + 逻辑操作 + request_id；epoch和绑定不能作为规避重复的新命名空间 |
| 世界/战斗事件去重 | 上述归属 + run + encounter或空值 + event_id；跨通道归一到同一事实键 |
| 指令、回执 | 上述归属 + run + 适用的encounter + directive/order关联 |
| 人格、世界观、能力目录 | 按游戏/角色/版本共享静态配置，不复制为每玩家资产 |

新JSON布局使用 `root/<game>/<player>/<save>/<companion>/`，每个根目录由服务配置控制。旧 `root/<game>/<companion>/` 保留并视为未归属数据；不自动导入首位玩家、不在新作用域读不到时回退旧路径。正式迁移归第四步。

新JSON写请求的公共字段按下表解释；上下文发现用查询参数，run/encounter控制用第3节专用CAS字段。game/player不允许请求体覆盖，session统一UUID，不再沿用128字符输入到64字符对话接口的截断兼容。

| 字段 | 必填范围与约束 |
| --- | --- |
| protocol_version、request_id | 所有scoped JSON写请求分别固定0.4、UUID；request_id标识逻辑操作，不是一次网络尝试 |
| save_id、companion_id | NPC业务请求必填；control只需save_id，角色相关context查询另带companion_id |
| service_instance_id、run_id、run_binding_id | 除首次context发现和runs/bind外，业务/控制写请求须携带有效绑定；runs/bind按第3节CAS字段申请新绑定 |
| memory_epoch | 读取生成上下文、产生记忆/关系副作用或reset的NPC请求必填；纯run/encounter控制不需要；回执只能关联原动作，不作为绕过epoch补写长期状态的通道 |
| session_id | agent/chat可省略；有值必须UUID并属于当前run，缺省使用run_id |
| encounter_id | 战斗建议、战斗事件/回执必填，并与当前活动遭遇及快照内encounter一致；非战斗可省略 |
| timing | 实时业务请求包含第6节年龄/预算；有world_context时执行快照年龄检查，无快照文本只检查请求预算 |
| world_context | agent与world/events必填，chat可选；复用现有世界快照对象并升级必要的UUID/时区校验，不把世界字段重复铺进身份对象 |
| text、event、receipt/receipts | 分别由agent/chat、world事件、回执入口使用；保留各自判别与二选一结构，不能把一个端点的字段混到另一个 |

<a id="scope-3-游玩控制与服务实例绑定"></a>
#### 3. 游玩控制与服务实例绑定

每次服务进程启动生成新的 `service_instance_id`（UUID）。该值是过期隔离标识，不是认证凭据。服务重启后不得只凭旧run_id恢复旧绑定；客户端取得新上下文并显式重新绑定，旧服务实例的控制请求和业务请求均拒绝。

最小控制入口如下，路径均为本草案提案：

| 入口 | 输入与结果 |
| --- | --- |
| GET /v1/scoped/context?save_id=...&companion_id=... | 两个查询参数必填；可信主体先检查该save归属和当前游戏已登记角色，再返回scope、service_instance_id、存档control_revision、当前run/binding或null、活动encounter及其revision，以及角色memory_epoch |
| POST /v1/scoped/runs/bind | v0.4、request_id、save_id、service_instance_id、expected_control_revision、expected_run_id（可为null）、拟绑定run_id；CAS成功后返回新run_binding_id和递增revision |
| POST /v1/scoped/runs/end | v0.4、request_id、save_id、service_instance_id、run_id、run_binding_id、expected_control_revision；CAS成功后关闭run及其遭遇、清当前绑定并递增revision |
| POST /v1/scoped/encounters/control | v0.4、request_id、save_id、service_instance_id、run_id、run_binding_id、op=begin/end、expected_encounter_revision、expected_encounter_id（可为null）；begin另带拟用encounter_id；同一绑定下CAS开始/结束遭遇，返回新revision和当前遭遇 |

控制状态按game/player/save维护。`control_revision`在同一服务实例内只增不减，结束run后也不回到0；它与expected_run_id共同做CAS，防止“空→活动→空”后旧激活请求再次成功。control_revision、当前run和绑定在同一锁内检查和更新。跨重启通过service_instance_id拒绝旧控制包，不把本地revision从头计数当旧请求再次生效的理由。

首次绑定在无当前run时提交预期revision和null；替换提交当前revision及旧run，成功后旧binding立即失效。服务重启后的显式重新绑定可保留客户端仍有效的逻辑run_id，但必须使用新service_instance_id和新binding；不能恢复重启前的待执行建议。存活实例上的重连可继续使用原有效绑定，不必每个HTTP请求重新绑定。

首期每个活动run绑定最多一个活动encounter，encounter_revision在该绑定内只增不减。begin要求预期revision和预期当前遭遇匹配；end必须匹配当前遭遇，不因重试再次结束新遭遇。普通world/agent请求不能凭自报encounter_id创建/切换遭遇；无活动遭遇、遭遇已结束或ID不匹配时拒绝战斗建议。换run、结束run或服务实例变化同时使原遭遇控制与建议失效。

普通业务请求必须携带 `save_id/run_id/service_instance_id/run_binding_id`。只校验或拒绝，不激活/替换run。`encounter_id`用于约束本次绑定下的战斗；旧run的事件、回执和建议在首期scoped入口拒绝，不实现离线事实归档。后续如允许旧事实归原身份归档，也不得产出当前世界动作。服务重启后，显式重绑仅允许基于新上下文和新快照发起新操作，不自动补发结果未知的旧请求，也不把它改成新ID再做一次。

| 转换 | 长期状态 | 单局状态/请求 |
| --- | --- | --- |
| 死亡重试、重新开始 | 按DEC-SCOPE-01保留当前存档记忆/关系 | 新run/binding；旧绑定、会话与建议失效 |
| 返回菜单、退出 | 保留已成功写入状态 | 显式结束或本地立即失效；退出不等待服务器成功 |
| 开新进度/分支读档 | 使用新save_id；复制/恢复策略另行设计 | 新run和新绑定，不把旧作用域写进新分支 |
| 服务重启 | 加载已持久化记忆/关系及epoch | runtime绑定和短期历史失效，显式重建；不重放待执行动作 |
| 单纯HTTP重试 | 不新建归属或游玩 | 原request/event ID与原逻辑载荷，遵守第5节 |

<a id="scope-4-记忆重置与晚到写入"></a>
#### 4. 记忆重置与晚到写入

每个长期记忆作用域拥有服务端生成并持久化的 `memory_epoch`（UUID）。创建新记忆状态或成功reset时生成新epoch；它不是玩家可自由填写的新版本号，也不是数据库schema版本。请求携带其读取到的epoch，服务端核对当前值。

| 规则 | 必须保证 |
| --- | --- |
| BR-SCOPE-01 | 所有玩家状态读写使用第2节作用域；可信主体/存档归属错误不得降级至匿名共享状态 |
| BR-SCOPE-02 | 普通请求不能激活run；run控制使用服务实例标识和CAS，旧绑定不得产生新动作或状态副作用 |
| BR-SCOPE-03 | 记忆reset只清该作用域的记忆和会话，不重建人格、不清关系、日志或其他角色；沿用现有reset范围 |
| BR-SCOPE-04 | reset持久提交新epoch后，旧epoch的在途LLM、缓存响应及后续补交请求不得写回记忆/历史或应用该轮关系副作用 |

reset在同一作用域锁下将“新epoch＋空记忆”作为同一JSON状态原子替换，然后清对应短期历史并发布结果；不得先宣布成功再落盘。部分失败返回实际结果，不能承诺跨文件事务回滚；失败时保持可判断的epoch/状态，不接受未知epoch的写入。已存在作用域的元数据损坏、丢失或备份世代不明时报告存储故障，不自动恢复旧备份或初始化为旧epoch。

LLM生成在锁外进行；发起时捕获run binding和epoch，完成后在写入锁内重新检查。检查与本轮记忆、关系、会话更新之间不能留出reset/换run可插入的空隙。跨run控制锁与NPC状态锁按固定顺序获取，不能持锁等待外部LLM。

epoch不进入请求/事件去重键。试图保持同一request/event ID、换成新epoch再次提交时，归一载荷不同，须拒绝；不能借reset把一次旧事实变成新事实。新epoch也不会令旧指令恢复有效。

<a id="scope-5-请求事件与回执去重"></a>
#### 5. 请求、事件与回执去重

请求去重和事实去重分别维护。请求指纹包含规范化的逻辑载荷、归属、run、首次绑定信息、epoch及不可变预算；排除认证凭据、HTTP通道等传输差异和只增不减的本次尝试年龄。指纹算法/字段集合在实现测试中固定，不能只比较text。去重键不包含memory_epoch或run_binding_id以绕开旧ID记录。

| 情况 | 处理 |
| --- | --- |
| 同作用域、同request_id、同逻辑载荷 | 在保留窗口内复用同一逻辑结果/建议ID；仍检查当前binding、epoch与有效期 |
| 同request_id、不同逻辑载荷 | 409 + REQUEST_ID_CONFLICT，不执行新副作用 |
| 并发同request_id | 先占位后执行；同一键single-flight，其他调用等待同一结果或返回明确处理中，不再次调用LLM/计分 |
| 同事实经world/combat两通道上报 | 归一到同一事实键；比较事件类型、发生时间、序号、details和原快照等语义字段，不以外层request_id或通道区分两次事实 |
| 同event_id、不同规范化事实载荷 | 409 + EVENT_ID_CONFLICT；不得仅凭ID命中就把冲突事实当正常重试 |
| 重复回执 | 使用相同动作/阶段/序号或回执标识关联；本步定义关联和重复识别，不宣称完整执行状态机已完成 |
| 缓存满且没有可释放的到期项 | 明确返回503 + IDEMPOTENCY_CAPACITY，未开始处理；不能静默淘汰仍在承诺窗口内的结果 |
| 处理已开始但持久提交结果不确定 | 保留UNKNOWN占位并返回503 + REQUEST_OUTCOME_UNKNOWN；相同ID不自动重新执行。跨JSON文件的事务保证留第四步，不能因重试把部分已落盘副作用再做一次 |

请求和事件的保留窗口、最大容量由服务配置并记录，样例数值不是正式性能指标。只在窗口内保证相同请求/事实不重复处理；客户端超过窗口后停止自动重试，不能重用原ID制造新操作。第二步的内存去重在服务重启、跨进程或窗口外不承诺永久恰好一次；跨重启可靠去重与关系写入的事务一致性由第四步持久化完成。

旧binding或旧epoch优先拒绝，不将已关闭游玩的原200响应重新当成可执行建议。对失败是否可重试、处理中等待上限和确定性失败的保留规则需要在实现中形成样例；不能将业务拒绝无条件重试为新输入。

<a id="scope-6-快照与指令有效期"></a>
#### 6. 快照与指令有效期

新请求的timing包含 `capture_age_ms`、`request_age_ms`、`max_snapshot_age_ms`、`max_request_age_ms`，均为有限非负整数并受服务端配置上限约束。capture_age描述快照采集至本次发送已过去多久，request_age描述首次发送至本次尝试已过去多久；网络重试必须累计，不能把两者重置为0；服务端对已有请求记录拒绝年龄倒退或采集基准变化。两项年龄来自同一客户端单调计时，capture_age_ms减request_age_ms所表达的首次发送时快照年龄保持不变。captured_at保留带时区UTC用于追踪，不承担跨机器精确倒计时。

服务端从首次接收开始使用单调时钟计算排队/处理耗时，扣除请求已报告年龄，建立不可延长的内部deadline。重试不能延后该deadline；服务端只掌握已知年龄和本机耗时，不能由客户端UTC推算精确单向网络延迟。超限不生成新建议/关系副作用。

响应timing中的 `valid_for_ms` 定义为**从该逻辑请求首次客户端发送起算的总有效预算**，不是从收到响应时重新倒计时。UE用首次发送时保存的本地单调时钟计算已耗时间，再扣除网络往返、重试间隔和本地排队；同时用采集时刻检查快照年龄。服务器生成建议时取请求、快照剩余窗口与动作语义允许窗口中的保守上限，并换算回同一首次发送基准，不能把“当前剩余”当成新的总预算。令首次发送时快照年龄为A、客户端首次发送至当前的单调耗时为E，接收端至少检查A+E不超过max_snapshot_age_ms、E不超过valid_for_ms；缓存重试沿用相同A和首次发送计时。

缓存回放保留首次结果、原预算和动作ID，不重新生成一个完整TTL；当前已过期则返回过期结果或无可执行建议。客户端若已丢失该请求的首次发送计时，不能把缓存回包当新指令执行。服务器重启后的旧绑定失效，不允许依赖跨重启单调时钟值续期。

`expires=encounter_end`还须匹配当前run/binding/encounter，并受有限总预算约束；`before_seconds`不得在每次回包后重新续满。实际触发条件时UE仍检查当前目标、能力、资源、冷却和忙碌状态。有效期是安全界限，不等于已达到原NFR时延目标。

以下仅演示v0.4信封关联；UUID和预算数字是golden候选样例，不是当前可发送的请求、最终参数或新增性能要求。world_context其余字段仍遵循本游戏快照结构。

```json
{
  "protocol_version": "0.4",
  "request_id": "11111111-1111-4111-8111-111111111111",
  "save_id": "22222222-2222-4222-8222-222222222222",
  "run_id": "33333333-3333-4333-8333-333333333333",
  "service_instance_id": "44444444-4444-4444-8444-444444444444",
  "run_binding_id": "55555555-5555-4555-8555-555555555555",
  "memory_epoch": "66666666-6666-4666-8666-666666666666",
  "companion_id": "companion.alice",
  "timing": {
    "capture_age_ms": 20,
    "request_age_ms": 0,
    "max_snapshot_age_ms": 3000,
    "max_request_age_ms": 3000
  },
  "text": "跟着我"
}
```

<a id="scope-7-端点与兼容边界"></a>
#### 7. 端点与兼容边界

本草案选择独立 `/v1/scoped/` 命名空间，JSON入口显式校验protocol_version=0.4；原入口保留已支持格式，不把0.4字段塞入extra=forbid的0.3模型。新旧入口共用业务服务和作用域解析，不复制人格/意图/规则策略。scoped JSON请求/响应的完整schema及golden须在开发任务中补齐，不能将上节缩略信封当完整字段表。

| 计划入口 | v0.4输入/输出与本步范围 |
| --- | --- |
| GET /v1/scoped/context、POST /runs/bind、/runs/end | 上下文发现与控制响应显式标0.4，按第3节解析可信归属与运行控制；不是账号注册/登录平台 |
| POST /v1/scoped/encounters/control | 同版begin/end控制响应，绑定当前run并校验遭遇revision/预期ID，按第3节显式开始或结束遭遇 |
| POST /v1/scoped/agent/step | 新请求/响应类型固定0.4，公共归属/绑定/epoch/timing完整回显；action保留none/directive，directive使用同版信封 |
| POST /v1/scoped/world/events（/combat/events同版别名） | 同版事实请求与响应；反应/关系信息保留明确含义，执行建议使用同一v0.4 directive，不直接嵌入旧v0.2 companion_action/DecisionAction |
| POST /v1/scoped/companion/chat | 非流式文本对话，新信封显式0.4并带request/run/epoch/timing；source仍区分mock/llm/fallback，不返回旧0.1响应冒充新格式 |
| POST /v1/scoped/tactical/executions | 单条/批量信封和每条回执均显式0.4，检查原scope/run/动作关联；沿用accepted/executed/rejected/expired/cancelled的已有含义，accepted及202不表示动作完成，执行阶段细化留第三步 |
| /v1/scoped/console/state、/memory、/memory/reset | 同版开发管理请求/响应使用相同主体/存档/角色范围；reset写操作也校验request/run/epoch，不能沿旧版仅companion_id跨玩家清理 |

scoped业务响应携带实际解析的game/player/save/companion、run/绑定/epoch及适用的快照关联，不从LLM生成身份。旧端点继续返回其原有版本与响应类型，v0.4不让旧固定版本模型作为嵌套对象混入新JSON；共享的业务枚举只有在语义一致时显式复用，不借升级新增未批准的动作/技能/回执阶段。所有新路径均以 `/v1/scoped/` 为前缀，上表控制行的简写亦如此。

| 新响应关联字段 | 必填范围与含义 |
| --- | --- |
| protocol_version | scoped成功JSON响应固定0.4；错误遵循第8节，不使用旧0.1/0.2响应模型 |
| request_id | 写操作回显原逻辑请求ID；GET context无请求ID时不伪造关联 |
| scope | 可信game_id/player_id及已授权save_id；NPC响应另含companion_id，控制响应不虚构角色 |
| service_instance_id、run_id、run_binding_id | 业务成功响应回显实际使用绑定；context在未绑定时run/binding为null；bind/end响应报告操作后的当前值 |
| control_revision、encounter_revision、encounter_id | context及适用控制响应必带revision；业务战斗响应带实际使用encounter，非战斗不编造遭遇 |
| memory_epoch、session_id | 记忆/对话/agent等适用响应带实际使用epoch及有效会话；不把生成后新epoch冒充该轮读取时的epoch |
| used_snapshot_id | 使用快照的agent/world/chat响应回显实际快照ID；未提供/使用快照时为null，不以当前最新快照替换旧关联 |
| timing.valid_for_ms | 实时建议/对话响应的首次客户端发送起算总预算，不是当前剩余TTL；缓存回放保持原预算和原建议ID |
| action、directive、observability | agent/world采用none/directive及同版信封，观测包含来源和原因；无动作不视为协议失败。chat和回执使用各自明确业务字段，不借通用信封宣称已执行 |

以下为无动作响应的关联示意，与第6节请求使用同一组样例身份；数字只演示总预算含义，不是性能要求。完整golden须随schema另建并校验。

```json
{
  "protocol_version": "0.4",
  "request_id": "11111111-1111-4111-8111-111111111111",
  "scope": {
    "game_id": "aesir",
    "player_id": "77777777-7777-4777-8777-777777777777",
    "save_id": "22222222-2222-4222-8222-222222222222",
    "companion_id": "companion.alice"
  },
  "service_instance_id": "44444444-4444-4444-8444-444444444444",
  "run_id": "33333333-3333-4333-8333-333333333333",
  "run_binding_id": "55555555-5555-4555-8555-555555555555",
  "memory_epoch": "66666666-6666-4666-8666-666666666666",
  "session_id": "33333333-3333-4333-8333-333333333333",
  "used_snapshot_id": "88888888-8888-4888-8888-888888888888",
  "timing": {"valid_for_ms": 2000},
  "action": "none",
  "directive": null,
  "reply_text": "当前没有可执行建议。",
  "observability": {"source": "rule", "reason_codes": ["NO_CANDIDATE"]}
}
```

legacy开发兼容模式把旧v0.1/v0.2/v0.3请求映射到显式固定、独立的legacy归属，不能访问scoped数据。严格模式关闭所有未接入作用域的旧业务入口，包括commands/parse、parse-command、tactical/command/resolve、combat/events、旧回执、console和其UI；不是只在agent/step门口检查一次。/health及必要只读服务发现单独列白名单。

scoped语音入口 `POST /v1/scoped/companion/chat/voice` 已提供 v0.4 multipart 适配：先校验可信作用域，再执行ASR，最后复用scoped chat链路并返回 `transcribed_text`。当前语音入口保持同步；v0.5异步只对JSON chat/agent-step开放。SSE仍未实现scoped关联，严格模式拒绝，不静默落入旧chat。外部ASR供应商、音频门禁和真实语音验收仍需单独配置与取证。历史兼容路径继续遵守其已有字段和行为，不在新协议中重写旧验收记录。

<a id="scope-8-错误与处理顺序"></a>
#### 8. 错误与处理顺序

统一错误体使用 `detail.code`、可读message及适用的request_id；不返回其他玩家路径、记忆或运行绑定。下列为v0.4边界原因码，实际服务端覆盖见本轮验证记录。

| HTTP/原因码 | 情况与调用方处理 |
| --- | --- |
| 401 IDENTITY_REQUIRED | 缺可信主体；开发身份提供器不能作为公网认证替代 |
| 403 SCOPE_FORBIDDEN / LEGACY_DISABLED | 存档不属当前主体或旧入口在严格模式禁用；不降级匿名 |
| 404 COMPANION_UNKNOWN | 当前游戏未登记角色 |
| 409 SERVER_INSTANCE_CHANGED / RUN_BINDING_STALE / ENCOUNTER_INACTIVE | 旧服务实例、关闭/替换的run绑定或无匹配活动遭遇；重新取得上下文，不重放旧动作 |
| 409 RUN_CAS_CONFLICT / ENCOUNTER_CAS_CONFLICT | 控制revision或预期run/遭遇不匹配；读取当前状态后由调用方决定，不盲目抢占 |
| 409 MEMORY_EPOCH_STALE | 重置前上下文；不写旧结果，不仅换epoch后重用原ID |
| 409 REQUEST_ID_CONFLICT / EVENT_ID_CONFLICT | ID相同但语义载荷不同 |
| 409 DIRECTIVE_UNKNOWN / DIRECTIVE_MISMATCH | 未发布于当前归属/绑定的指令，或回执与原请求/遭遇/能力关联不符；不写回执 |
| 409 REQUEST_IN_PROGRESS | 首次处理仍在进行，保留原逻辑请求ID并在原预算内查询；不得另发ID重做副作用 |
| 409 SNAPSHOT_EXPIRED / REQUEST_EXPIRED | 已超过相对预算；新操作需新快照和新请求，不为旧动作续期 |
| 422 INVALID_SCOPE_OR_TIMING | 非法UUID、超限/负数/非有限时效、缺字段或版本不匹配 |
| 429 HEARTBEAT_RATE_LIMITED | 当前作用域/游玩的心跳过频，不影响另一玩家 |
| 503 IDEMPOTENCY_CAPACITY / STATE_UNAVAILABLE / REQUEST_OUTCOME_UNKNOWN | 未开始处理的容量拒绝、状态不可用或已开始处理但提交不确定；后者不自动重新执行，不能统一按503重做副作用 |

处理顺序为结构/版本校验、可信归属、服务实例与绑定、epoch与预算、重复识别/占位、业务计算、锁内重验、状态写入、响应。控制请求走其CAS路径。服务器检查不替代UE最终验证，也不能由一次早期校验推断长LLM返回后仍有效。

<a id="scope-9-服务端验收与后续交接"></a>
#### 9. 服务端验收与后续交接

| 验收ID | 场景与通过条件 |
| --- | --- |
| AT-SCOPE-01 | 缺失/伪造主体、跨归属存档、非法路径ID、游戏与角色不符；副作用前拒绝，不回退匿名或旧目录 |
| AT-SCOPE-02 | 两玩家同角色、同玩家双存档、跨角色相同session；长期文件/关系与短期历史、心跳和自主抑制均隔离 |
| AT-SCOPE-03 | 同档新run、返回/重试及竞争控制；run与encounter控制CAS唯一生效，普通业务不隐式创建遭遇；结束后的旧activate请求不能因current_run再次为空而成功 |
| AT-SCOPE-04 | 同档重进和重新加载长期状态，按DEC-SCOPE-01保留；旧无归属JSON不自动迁移、不覆盖 |
| AT-SCOPE-05 | reset与在途LLM/写入竞争：epoch检查与提交受同一作用域保护；旧结果不恢复记忆，不追加该轮历史/关系副作用；原关系/人格/其他归属保留 |
| AT-SCOPE-06 | UTC偏差、快照过旧、排队/生成超时；单调耗时及已用预算生效，过期不发布可执行建议，原因可定位 |
| AT-SCOPE-07 | 同请求ID相同/冲突载荷、并发重复及跨归属同ID；single-flight和稳定建议ID，窗口内副作用不重复，跨归属不相互命中 |
| AT-SCOPE-08 | 同事件跨world/combat归一、回执跨归属、缓存容量/重启；原归属关联正确，不静默淘汰未到期结果或承诺持久恰好一次 |
| AT-SCOPE-09 | 缓存回放、旧run/遭遇、reset后请求重放；原时效不续期，epoch/binding不成为绕过去重和关系计分的新键 |
| AT-SCOPE-10 | 严格/legacy入口矩阵覆盖chat、SSE、语音、事件、回执、console；各入口明确同版支持或拒绝，legacy不触及scoped目录 |
| AT-SCOPE-11 | 服务重启后已落盘长期状态/epoch可重载；旧实例业务和控制绑定拒绝，显式重绑；状态元数据异常不回退旧世代，丢失内存去重如实报告 |
| AT-SCOPE-12 | 新schema/完整golden与适用核心回归保存真实版本/结果；只用服务端测试客户端和受控时钟，不把计划、Mock或服务端通过写成UE/真实LLM/ASR通过 |

UE后续需要保存可信会话关联、save/run/encounter与请求ID，在换局时取消在途请求并使旧回调失效；记录首次发送单调时间，复核预算和当前能力后执行。第二步先交付该字段与生命周期清单，不在本轮测试UE连接或修改UE运行行为。


<a id="scope-10-分支实现细节与交接"></a>
#### 10. 分支实现细节与交接

开发入口见[v0.4开发与交接](../guides/_04_scoped_development_guide.md)。新请求/响应已形成独立Pydantic模型与完整golden，OpenAPI按同版response_model声明；console GET无逻辑写请求时request_id为null，不伪造关联。`/v1/scoped/combat/events`与`/world/events`接受同一世界事件模型，共用逻辑操作及事件键。

同一request_id缓存回放保留原指令ID与总预算。对于同一event_id但不同request_id，事实/反应可以重放，执行建议为空（action=none、duplicate=true），防止原建议被新首次发送时钟续期；捕获基准或语义冲突仍拒绝。reset作为无动作控制写入，允许同一逻辑reset回放其已产生的新epoch，但仅当该epoch仍当前，且绑定仍有效；另一reset发生后拒绝该旧结果。其他旧epoch业务仍在缓存回放前拒绝。

兼容模式显式配置`AESIR_SCOPE_LEGACY_ENABLED=true`，旧请求的固定legacy归属沿用独立`root/game/companion`历史命名空间；scoped只访问含player/save的新路径，绝不自动迁移或认领旧数据。此处固定legacy命名空间不是生产玩家身份。默认关闭兼容；服务器现有环回开发配置显式开启。

实现的时效预算上限120000毫秒，0预算立即过期；请求/事件去重默认各1024项、300秒保留，处理等待上限30秒。未开始的容量拒绝与开始后的UNKNOWN区分，窗口内结果不因满额被静默淘汰。当前回执关联内存上限4096项、保留300秒；控制状态上限4096个存档。单worker与进程内窗口限制不构成跨重启恰好一次保证。磁盘多文件部分写入不具事务性，UNKNOWN不能自动换ID重做。

服务端实测与UE后续清单分别见[验证记录](../records/_01_verification_records.md#scope-20261021)和[开发与交接](../guides/_04_scoped_development_guide.md#4-验证与ue后续交接)。

<a id="loop"></a>
## v0.4 请求与执行反馈

<a id="loop-npc开发闭环增量契约v04"></a>
### NPC开发闭环增量契约v0.4

> 2026-10-22，`loop-contract-v1`，随[第三步计划](../planning/_04_execution_loop_plan.md)开发。基线 `main@e96151b`；新增支持以分支回归记录为准。本页是[v0.4作用域契约](_01_npc_contract.md#scope)的增量，不改变既有chat/agent请求或既有回执枚举；字段以`app/schemas/loop.py`及对应golden为准。

<a id="loop-1-请求生命周期"></a>
#### 1. 请求生命周期

chat和agent文本共享完整NPC/run/session队列，按服务接收并登记的顺序处理；网络重试仍由原request_id及作用域确定。规则心跳可登记状态但不占生成队列或生成并发；事件、回执和控制入口沿用自身协调器。request_id不是上游尝试ID，每次实际上游调用另有内部尝试UUID及计数。

状态为`queued/running/completed/cancelled/expired/failed/unknown`。completed表示该服务请求已完成，不表示UE动作完成。unknown表示开始提交后的结果不确定，不能换ID重做。状态键不加入epoch/binding作为绕过去重的新维度；原session、instance、binding、epoch和encounter仍逐项核对。

同会话默认最多4个等待项、全局最多16个等待项、同时2个生成请求；默认请求状态上限1024项、正常终态保留300秒。未到期项不因满额被静默淘汰。不确定提交保持占位至显式清理或进程退出。进程重启后旧绑定失效；此处不提供跨重启事务和永久查询。

| 入口 | 模型与结果 |
| --- | --- |
| POST `/v1/scoped/requests/cancel` | 原v0.4 NPC写信封加`target_request_id`、`operation=chat/agent-step`、`reason_code=USER_CANCELLED/SUPERSEDED`；响应带目标状态及`cancel_requested` |
| GET `/v1/scoped/requests/{target_request_id}` | 带`operation`和现有console相同的scope/binding/epoch查询参数；返回目标状态、原因、queue/processing/total毫秒和实际upstream_attempts |
| GET `/v1/scoped/directives/{directive_id}` | 带现有console同样的作用域参数；返回原request_id、状态、sequence及有效回执数量，不返回可执行payload或刷新有效期 |

取消未知目标可创建有界cancelled占位，阻止稍后同ID到达后继续生成。取消排队/运行中且尚未最终提交的目标生效；最终完整对话写入或指令发布开始后取消未生效，`cancel_requested=false`，不撤销已提交事实。客户端仍需独立丢弃其已取消回调。

LLM计算不持NPC/运行控制锁；最终提交在原绑定/epoch/预算及取消检查后线性化。同步供应商HTTP不保证在控制请求到来时被强制中断；返回后拒绝旧结果，并在每次后续上游尝试前重新检查。已到期/取消不按一般供应商错误回退重试或计入供应商熔断。若初次处理在最终提交后、外层校验/缓存阶段才失败，响应和生命周期改为unknown；后续读取已完成结果时遇到旧绑定或过期则拒绝回放，不把已提交事实撤销。

<a id="loop-2-最小执行反馈账本"></a>
#### 2. 最小执行反馈账本

现有`accepted/executed/rejected/expired/cancelled`不变。状态由`issued`开始，accepted仅记录收到；执行、拒绝、过期或取消是该最小账本的终态。executed只表示UE自报已执行，不推断技能命中、伤害或完整动画完成。`unknown`仅用于已知原指令的不确定写入，保留原request_id；不存在的ID不构造虚假的unknown对象。

所有回执先验证原scope/run/binding/epoch/encounter与指令关联。sequence存在时同一指令同序号不得换语义；无序号时同语义回执也去重。received_at不参与语义指纹；reported_at保留为自报记录，不用于改变处理顺序。终态后迟到accepted忽略，冲突终态拒绝；不能用重连、换HTTP请求ID或较晚reported_at倒退已记录状态。

同批回执先完整验证并在副本上演算，再一次追加成功后采纳状态。追加/flush/fsync失败后将可能受影响的订单标unknown，后续请求不得自动重做；并封锁该完整NPC/run的新指令注册和回执追加，防止后续成功记录接到损坏的JSONL尾部。封锁由unknown槽位承载，仍受总容量限制；其他run不受该封锁影响。显式clear或重启不会修复磁盘残片，重新使用日志前需人工核对。状态与日志仍不是数据库事务，跨重启恢复在第四步。

指令关联默认上限4096项、正常保留300秒，同ID同内容注册不续期；不同内容冲突。每单最多64个回执身份，超过容量明确拒绝。unknown占位保留到显式清理或进程退出，不能通过容量淘汰后自动重做。

<a id="loop-3-错误与兼容"></a>
#### 3. 错误与兼容

| HTTP / 原因码 | 处理 |
| --- | --- |
| 409 REQUEST_CANCELLED | 原逻辑请求已取消；新意图需新ID，不能重用旧ID恢复旧结果 |
| 404 REQUEST_UNKNOWN / DIRECTIVE_UNKNOWN | 当前实例没有可查询记录；不伪造完成状态 |
| 503 REQUEST_QUEUE_FULL | 队列、生成准入或状态容量未开始处理时拒绝；不承诺更多并发 |
| 409 RECEIPT_SEQUENCE_CONFLICT / RECEIPT_STATE_CONFLICT / DIRECTIVE_ID_CONFLICT | 同序号/终态/已发布身份冲突，不追加或覆盖原事实 |
| 503 STATE_UNAVAILABLE / REQUEST_OUTCOME_UNKNOWN | 容量/存储不可用或提交不确定；后者不换ID重做 |

回执写入未知指令仍沿用既有409 `DIRECTIVE_UNKNOWN`，只读查询未知ID用404。原身份、绑定、epoch、预算与载荷冲突等错误继续遵循v0.4主契约。新请求/响应显式0.4、UUID和extra=forbid；旧协议及scoped SSE/语音支持状态不变。

已有跟随/等待和战术能力只修复已声明目录的映射与原能力关联；未实现的条件执行不能下发伪动作。完整started/hit/completed、UE条件监听及执行去重需后续跨端协议和真实验收。

<a id="persistence"></a>
## v0.4 持久化与恢复

<a id="persistence-npc持久化与恢复增量契约v04"></a>
### NPC持久化与恢复增量契约v0.4

> 2026-10-22，`persistence-contract-v1`。随[第四步计划](../planning/_05_persistence_plan.md)实现。它补充[v0.4作用域契约](_01_npc_contract.md#scope)与[第三步闭环增量](_01_npc_contract.md#loop)，不改变原chat/agent/事件信封或五种回执结果。严格字段以 `app/schemas/recovery.py`、`app/schemas/sync.py` 及golden为准；运行支持以验证记录为准。

<a id="persistence-1-存储与认证模式"></a>
#### 1. 存储与认证模式

默认 `scope_storage_backend=json`，旧开发使用方式保留。显式SQL模式通过站点根外0600连接文件或SecretStr配置连接MySQL/PyMySQL，schema必须先由迁移账号初始化；SQL启动及首次接入用共享metadata门禁核对表列、约束、索引、引擎/字符集及唯一版本标记，通过才缓存连接。结构不符拒绝服务，业务请求不自动建表；现有库的init仅只读核对，只有完全空库可建表。SQLite只在 `scope_sqlite_test_mode=true` 时可作为配置后端用于隔离测试，没有MySQL故障回退。

`scope_identity_backend=bearer` 使用 `Authorization: Bearer <credential>`，数据库验证哈希、玩家活跃状态、过期/撤销、游戏、权限和存档授权；客户端不能自报身份。凭据由受限运维CLI签发/撤销，没有公网注册或发token接口。明文仅写指定私有新文件，不入库或日志，供应商key不下发。开发principal的固定身份不等于生产认证。

| 权限 | 可用入口 |
| --- | --- |
| `npc:use` | 归属内context/run/encounter、chat/agent/事件/回执、取消和状态、权威恢复及真实事实/历史回执归档 |
| `console:read` | scoped console调试查询；也可读取文档/OpenAPI |
| `memory:reset` | 指定NPC的记忆重置；不自动授予console读取或业务权限 |
| `docs:read` | 文档/OpenAPI；不自动授予业务或其他管理权限 |

Bearer模式始终封锁legacy，不接受开发兼容开关旁路；文档需要管理读取。`/health`仍为必要存活信息。普通npc:use可读取自有权威记忆/关系快照供UE恢复缓存；console权限约束调试入口，不能笼统解释为玩家无法读自己的缓存。长请求在上游/提交边界重新检查撤销与存档授权；已经进入提交后的撤销不回滚已有事实。

<a id="persistence-2-sql原子性与逻辑身份"></a>
#### 2. SQL原子性与逻辑身份

物理表、逻辑实体与字段说明见[数据库设计](../design/database/README.md)；本契约只维护接口和提交语义，不将通用documents中的每种记录视为独立物理表。

SQL文档用namespace和完整逻辑键的唯一哈希保存原key、scope、payload及CAS版本；NPC确认版本按完整game/player/save/npc递增。请求/事件journal保存原逻辑key、指纹、owner instance、状态、确认版本及结果。哈希不是玩家认证；原scope/key仍核对。

请求claim为独立短事务。LLM期间无长事务/行锁；最终事务一起提交记忆、关系、epoch、事件/指令/回执与请求结果。处理中的重试等待原owner，载荷或binding/epoch改动冲突；未开始准入失败可放开占位，已开始但提交不明保留UNKNOWN。逻辑身份不自动TTL删除，也不因换HTTP ID恢复未知的原事实执行资格。数据库事务回滚时会话历史不追加；提交后诊断失败不撤回数据库事实。

service_instance与run绑定仍是进程生命周期，重启需重新发现/显式bind，旧业务请求不能直接回放。旧journal owner的complete结果仅可读历史确认；遗留running保守unknown，不自动重新抢占。当前仍单worker，不以数据库存在宣称已支持多worker的队列、绑定和取消一致性。

已接入的业务准入、控制和同步入口按game/player累计请求额度；不覆盖全部HTTP传输，控制/同步重试可能计次，业务缓存回放不再重新准入。每次上游真正尝试前独立预留日调用额度，缓存不扣上游额度，取消或业务rollback不退还预留；这不是货币费用硬预算。规则心跳不调用LLM。认证、额度及SQL故障都不能退回匿名或共享JSON状态。

<a id="persistence-3-权威状态与历史确认"></a>
#### 3. 权威状态与历史确认

| 入口 | 查询/响应边界 |
| --- | --- |
| GET `/v1/scoped/recovery/state` | `save_id/companion_id`；返回完整自有scope、当前service_instance、state_version、save_generation、memory_epoch、MemorySnapshot和关系状态 |
| GET `/v1/scoped/recovery/operations/{request_id}` | 另带原run_id和operation；返回原请求状态、原实例、confirmed_version及原因，不返回旧响应或可执行payload |
| GET `/v1/scoped/recovery/directives/{directive_id}` | 另带原run_id；返回原请求/实例/epoch和最后自报反馈，不返回技能payload或刷新有效期 |
| GET `/v1/scoped/sync/state` | 返回自有scope、save_generation、epoch、state_version及权威关系，用于版本冲突后拉取；不返回动作或原对话 |

这些入口核对当前可信存档授权，不要求旧service_instance/binding仍有效。不存在记录返回明确404。恢复请求状态可能是complete/failed/unknown/cancelled；complete仅服务请求提交完成，executed仍只代表UE自报，不推断命中/动画完成。

save_generation按game/player/save独立持久登记；memory_epoch只表示NPC清记忆世代。当前不提供任意分支读档/跨设备合并，不能靠自行生成generation覆盖原档。原run/encounter须有该存档世代的持久控制历史。

<a id="persistence-4-离线真实事实确认"></a>
#### 4. 离线真实事实确认

`POST /v1/scoped/sync/facts`接收同版request_id、save_id、companion_id、save_generation、expected_state_version和facts（运行默认最多50条，可配置1～100，schema硬上限100）。每条仅含 `origin_run_id/origin_encounter_id/origin_memory_epoch/source=ue/event`；event复用原ScopedWorldEvent（稳定UUID、sequence、event_type、occurred_at、details），单条序列化不超过16KiB。战斗事实必须有原encounter。只接受该游戏已声明事件；不接受聊天、音频、旧心跳、命令、技能建议或整个本地关系分数。

同一完整NPC/原run/原encounter/event_id是共同持久身份，实时/world或/combat与离线通道共享确认。指纹核原事件内容，不因重连/新epoch/新批次变新事实；同ID改内容冲突。批次request_id另绑定完整载荷；冲突拉状态后使用新批次ID，原fact ID保留。批内先完整校验，再同事务应用全部新事实、状态版本及分项确认。已有事实只返回原确认，不再次应用；全已知重试可读取原确认而不要求旧expected版本仍为当前。

| 分项 | 规则 |
| --- | --- |
| 关系 | 仅现有关系规则计分，使用服务受理UTC维护冷却/日上限；UE occurred_at作为来源记录，不能倒退服务器计分日 |
| 记忆 | 原epoch为当前且有合法活动上下文时，只写现有共同经历模板；非经历事件not_applicable；无活动上下文明确not_applied_missing_context |
| 旧epoch | 记忆skipped_reset，不恢复已清内容；关系独立按原事实确认，已确认的关系不重复计分 |
| 响应 | event_id、duplicate、relationship_status/delta、memory_status和原confirmed_version；外层返回当前epoch/generation/state_version，不返回动作 |

客户端收到分项确认后才移出已确认事实；遇STATE_VERSION_CONFLICT先拉权威状态，再重试仍合法且未确认事实。服务端不提供本地队列实现，UE仍需配置容量/保留期限/退避/失败状态，满额不静默宣称成功，退出不等待云端。新鲜世界状态走原实时入口，不借离线通道补执行历史动作。

<a id="persistence-5-历史回执归档"></a>
#### 5. 历史回执归档

`POST /v1/scoped/recovery/receipts`专用于已发布原指令的历史事实归档。信封携带原run、原memory_epoch、save_generation及预期state_version，receipts复用严格原回执模型。允许原绑定失效或热关联窗口已过，但必须匹配数据库中的原指令/请求、能力、角色、遭遇与原epoch；未知指令不凭空认领。

与实时回执共用身份去重、序号冲突和终态演算，并与批次确认/版本同事务提交。归档不产生动作、不改变记忆/关系或撤销已确认事实；旧epoch回执可归档原事实，但不能恢复旧记忆。仅归档响应可按稳定批次ID跨重启取回原确认，普通业务仍不得回放旧实例动作。`stored=0`不必表示`duplicate=true`：终态后新的accepted身份可被忽略但已登记去重；同终态不同sequence仍为新身份。重试归档回放原安全确认，可能保留原service_instance，仅供历史关联。完整started/hit/completed仍未扩展现有枚举。

<a id="persistence-6-错误与迁移"></a>
#### 6. 错误与迁移

| HTTP / 原因 | 含义与处理 |
| --- | --- |
| 401 IDENTITY_REQUIRED | 缺失、错误、到期、撤销或玩家停用；重新获得合法凭据，无匿名回退 |
| 403 SCOPE_FORBIDDEN / PERMISSION_DENIED | 当前存档或入口权限不足，不使用其他玩家UUID绕过 |
| 409 STATE_VERSION_CONFLICT | 拉权威状态，新批次保持原事实身份；不上传整个分数覆盖 |
| 409 SAVE_GENERATION_STALE / ORIGIN_RUN_UNKNOWN / ORIGIN_ENCOUNTER_UNKNOWN | 存档世代或原来源控制历史不符，不冒认当前局 |
| 409 REQUEST_ID_CONFLICT / EVENT_ID_CONFLICT | 已有逻辑身份被改内容，保留原事实核对 |
| 429 REQUEST_QUOTA_EXCEEDED / UPSTREAM_QUOTA_EXCEEDED | 对应额度不足；不因换session/NPC逃逸同玩家额度 |
| 503 DATABASE_SCHEMA_MISMATCH / DATABASE_VERSION_UNSUPPORTED | 数据库结构或服务版本不符合要求；启动拒绝或首次SQL接入失败，由运维核对，不能由业务请求自动修复 |
| 503 AUTH_UNAVAILABLE | 凭据状态不可验证，含缺失或非有限的到期数据；不降为匿名或接受无期限凭据 |
| 503 STATE_UNAVAILABLE / REQUEST_OUTCOME_UNKNOWN | 状态不可用或提交确认不明；后者保留原关联核对，禁止自动换ID重做 |

旧instance/binding/epoch、回执sequence/终态等继续沿用原契约。只导入完整scoped JSON的已知归属；legacy文件不会自动归入玩家。恢复默认撤销所有恢复凭据，防较旧快照复活后续已撤销token；需核对授权后重新签发。业务数据只回到备份恢复点，不自动保留之后的reset/撤销，正式切换需另行收敛。导入/备份/恢复和切换操作见[运维与开发指南](../guides/_06_persistence_guide.md)，不以本页字段目标代替实测或UE接入。

<a id="async"></a>
## v0.5 异步提交增量

<a id="async-npc-异步请求契约-v05服务端已实现--待-ue-对齐"></a>
### NPC 异步请求契约 v0.5（服务端已实现 · 待 UE 对齐）

> 2026-10-27 起草。本页定义异步请求增量；服务端已实现、UE 联调仍待验。当前接入步骤见 [UE 服务适配](../guides/_05_client_integration_guide.md)，部署与推进边界见[六步方案](../planning/_02_delivery_plan.md)。旧阶段待办草案已于 2026-11-12 清理，本文保留契约及历史证据。
> 基线：develop-dyh@`9c25895`，阶段 0（Redis 外置调度）+ 阶段 1（status journal fallback）已闭环。
> **2026-10-27 进展**：§4 的 result 回放已实现（`ScopedRequestStatusResponse` 加 `result` 字段；内存 `_record()` 与 journal `read_status()` 在 completed 时回放业务结果，其余状态为 None）。同步模式下 UE 也可拿 POST 结果回查。
> **§3 的 202 提交已落地服务端（develop-dyh@`d0b6ffe`，受控 1566 绿）并通过 2026-10-28 真实端到端自证（commit `3e83ec5`）**：`chat`/`agent-step` 发 `protocol_version="0.5"` opt-in——提交线程只做校验/配额/容量准入即返回 §3.2 信封（202，不含业务结果），业务闭包投递进程内守护池（`app/scoped/async_pool.py`，contextvars 捕获 scope/principal/budget）执行；`coordinator.submit()`/`run_submitted()` 把登记入队与执行段拆开；幂等 `begin/settle/settle_failure` 不等待，同 request_id 网络重试在 `running` 时**不重复投递后台**（否则两 worker 把同一 action 跑两遍）。其余入口不放开 0.5（422）；v0.4 同步 200 永久保留。
> **端到端实测**（真实 server + 真实 LLM 后端）：202 POST 92ms 返回（同步 LLM 约 3s）、轮询 ~3.1s 到 completed、result 与 v0.4 同步 200 逐字段一致、两个并发 v0.5 均 completed 且 reply 各自连贯（后台池 contextvars 未串台）、server 日志无 Traceback。**第 8 节开放问题 3（预算默认值）已被实测澄清关闭**——预算取自 UE 请求 `max_request_age_ms`、服务端硬上限 120s，无默认值可调；问题 2（completed_at）已落地可配置（commit `c8357fb`，默认关、开了即开箱即用）；**只剩问题 1（终态保留期 300s）待 UE 联调时观测长尾拍板**。
> 阅读前提：[闭环增量契约 v0.4](_01_npc_contract.md#loop) 的请求生命周期与状态机全部沿用，本页只定义异步化带来的增量变更，未提及字段保持 v0.4 原样。

<a id="async-1-为什么要异步"></a>
#### 1. 为什么要异步

现状（v0.4 同步）：UE 调 `POST /v1/scoped/companion/chat` 或 `/agent/step`，服务端**在 HTTP 请求线程内**跑完整 LLM 生成再返回结果。多 worker 水平扩展后：

- 每个 worker 的 HTTP 连接被一次 LLM 调用占住数秒，并发上限 = HTTP 连接池大小，与生成并发（全局 2 槽）脱钩；
- 非粘性部署下同一 UE 的两次请求落到不同 worker，会话串行语义只能靠 Redis 调度兜底，但响应仍必须由接收 worker 自己跑完。

目标：接收 worker 登记后**立即返回 202**，业务执行交给后台 worker 池；UE 轮询 `GET /requests/{id}` 拿终态结果。

<a id="async-2-变更范围先划边界"></a>
#### 2. 变更范围（先划边界）

| 入口 | 模式 | 理由 |
| --- | --- | --- |
| `POST /v1/scoped/companion/chat` | **同步→异步（v0.5 opt-in）** | LLM 生成 1~3s，唯一占连接的入口 |
| `POST /v1/scoped/agent/step` | **同步→异步（v0.5 opt-in）** | 同上；text 非空时走 LLM，心跳可仍快速返回（见 §5） |
| `POST /v1/scoped/world/events` | 保持同步 | 纯规则 ~27ms，无 LLM，异步化无收益 |
| `POST /v1/scoped/tactical/executions` | 保持同步（已是 202 受理语义） | 回执落盘即返回 |
| runs/bind、runs/end、encounters/control、memory/reset | 保持同步 | 控制路径，毫秒级 |
| `POST /v1/scoped/requests/cancel` | 不变 | 短控制路径，本就在生成队列之外 |
| `GET /v1/scoped/requests/{id}` | **扩展**：completed 时携带业务结果（§4） | 轮询拿结果的唯一出口 |

<a id="async-3-提交入口的-opt-in-语义v05"></a>
#### 3. 提交入口的 opt-in 语义（v0.5）

**不做全局切换。** UE 在请求体中显式发 `protocol_version: "0.5"` 才进入异步模式；发 `"0.4"` 或不发的现有请求一律保持同步 200 行为不变。双跑期两类客户端并存，UE 改造一个端点切一个。

<a id="async-31-提交时仍同步完成的校验失败立即返回不进队列"></a>
##### 3.1 提交时仍同步完成的校验（失败立即返回，不进队列）

以下检查与当前同步路径完全相同，仍在提交线程内失败：

- 作用域/绑定/epoch 校验（403/409）；
- 请求体 schema 校验（422）；
- 配额（429）；
- **队列准入**：会话深度/全局等待/全局槽上限（503 `REQUEST_QUEUE_FULL`）。容量检查通过即视为已登记（v0.4 契约原文"不确定提交保持占位"）。

<a id="async-32-异步提交成功的响应"></a>
##### 3.2 异步提交成功的响应

HTTP **202**，响应体是当前 `_base(scope, request_id)` 信封加状态，**不含业务结果**：

```json
{
  "protocol_version": "0.5",
  "scope": { "game_id": "...", "player_id": "...", "save_id": "...", "npc_key": "..." },
  "service_instance_id": "...",
  "run_id": "...", "run_binding_id": "...", "memory_epoch": "...",
  "session_id": "...", "encounter_id": null,
  "request_id": "<原 request_id 回显>",
  "state": "queued",
  "timing": { "valid_for_ms": 6000 }
}
```

- `state` 只能是 `queued` 或 `running`（提交即获槽时）；**UE 不得假设 POST 返回即有结果**。
- `timing.valid_for_ms` 是**从提交时刻起算的总预算**。排队消耗预算；排队超时则该请求不执行，终态 `expired`（reason_code `REQUEST_EXPIRED`），UE 必须以**新 request_id** 重发，不能用旧 ID 续期（v0.4 契约：状态键不加入 epoch/binding 作为绕过去重的新维度）。
- 同 request_id 网络重试：幂等账本返回已登记项的当前状态（queued/running/completed），不会重复执行。

<a id="async-4-轮询出口get-v1scopedrequeststarget_request_id-扩展"></a>
#### 4. 轮询出口：`GET /v1/scoped/requests/{target_request_id}` 扩展

现有查询参数（scope/binding/epoch/operation）不变。响应在现有 `_record()` 字段基础上按状态分叉：

| state | 响应 |
| --- | --- |
| `queued` / `running` | 仅现有字段（状态、queue_ms/processing_ms、upstream_attempts、cancel_requested），**不带 result** |
| `completed` | 现有字段 **+ `result` 对象**——即原同步 200 响应体会原样回放（chat：对话回复+表现 ID；agent-step：output+directive 信封） |
| `cancelled` | 现有字段 + `reason_code`；不带 result |
| `expired` / `failed` | 现有字段 + `reason_code`；UE 以新 request_id 发起新意图 |
| `unknown` | 现有字段；**不得自动重发**（v0.4 契约原文），等人工核对或复用本 ID 后续查询 |

设计要点：

1. **result 回放是本阶段唯一新增读路径。** 现状 `ScopedRequestStatusResponse` 注释为"the read does not replay its business result"（同步模式下 UE 已从 POST 拿到结果）——v0.5 起 completed 请求必须回放。result 的 schema 与对应端点同步响应**逐字段相同**，不另造DTO（UE 同一套解析代码可复用）。
2. **跨 worker 结果已通。** 阶段 1 的 `journal.read_status()` 已能把 journal 行折成同形状 record；`stage_active_result(result)` 本就把业务结果落 journal。worker B 轮询 worker A 完成的请求，completed+result 从 journal 读出——无需新存储。
3. 回放不改变、不刷新任何指令有效期；directive 有效期仍以指令注册时刻起算（现状语义不变）。
4. 终态保留期维持 v0.4 口径（正常终态 300 秒可配置）；UE 超过保留期再查 → 404 `REQUEST_UNKNOWN`，只能重发新请求。UE 侧轮询设计须在保留期内拿到终态。

<a id="async-5-服务端实现要点给后续工程不在本契约稿范围"></a>
#### 5. 服务端实现要点（给后续工程，不在本契约稿范围）

- 提交线程：现有 `_execute()` 拆两段——校验/配额/容量（同步）+ 登记入队后立即返回 202；业务闭包投递到**进程内后台 worker 池**。
- 后台池线程执行与现有 `coordinator.execute(action)` 完全同一条代码路径（Redis 全局槽/会话串行/取消检查/预算裁剪全部复用），只是调用方从 HTTP 线程换成池线程。**不做跨进程 work-stealing**：闭包只活在接收进程内，跨进程只做槽位仲裁，不做任务搬运（本阶段非目标）。
- 心跳型 agent-step（text 为空、无 LLM）：池内执行也是毫秒级，可不入队直接同步完成返回 200——由服务端按 operation 是否触 LLM 决定，UE 无需区分。
- 池大小与全局生成槽（默认 2）解耦：池 >= 全局槽 × 预期 worker 数即可，真正的并发上限仍由 Redis 槽位裁决。

<a id="async-6-ue-侧适配清单双跑期对齐用"></a>
#### 6. UE 侧适配清单（双跑期对齐用）

1. 收到 202 后**立即丢弃等待 body 的逻辑**，转入轮询：建议起始 100~200ms 间隔、指数退避到上限 1s；拿到终态即停。
2. 轮询请求必须带与提交时相同的完整 scope/binding/epoch 查询参数（现状要求不变）。
3. `completed` → 用 result 字段驱动表现；`expired/failed/cancelled/unknown` → 走对应本地兜底（文案/重试入口），**unknown 绝不静默重发**。
4. 超时预算：UE 展示层的"思考中"计时不得超过提交时收到的 `valid_for_ms`，避免用户等一个已 expired 的请求。
5. 取消：用户中途打断时调 `/requests/cancel`；queued 中取消立即生效，running 中取消以终态轮询为准（v0.4 语义：已最终提交的事实不撤销）。

<a id="async-7-非目标本阶段明确不做"></a>
#### 7. 非目标（本阶段明确不做）

- 不引入服务端推送（SSE/WebSocket）——轮询是唯一出口；
- 不做跨进程任务搬运/工作窃取；
- 不改 LLM 供应商、熔断、超时口径；
- world/events / executions / 控制入口不同步化；
- v0.4 同步模式不下线（UE 全量切完前永久保留）。

<a id="async-8-待-ue-侧拍板的开放问题"></a>
#### 8. 待 UE 侧拍板的开放问题

> 2026-10-28 端到端自证（真实 server + 真实 LLM 后端，commit `3e83ec5`）后更新：v0.5 POST 92ms 立即返回 202（同步 LLM 约 3s），轮询 ~3.1s 拿到 completed，`result` 字段与 v0.4 同步 200 **逐字段一致**；两个并发 v0.5 均 completed、reply 各自连贯（contextvars 未串台）；server 日志无 Traceback。下列问题 3 已被实测澄清、关闭。

1. 轮询节奏与保留期匹配：默认终态保留 300s 是否够 UE 最坏轮询路径，还是延长到 600s？（实测单次完成约 3s，300s 保留期非常宽裕；建议联调时观测长尾再定，不预先放宽。）
2. ~~result 回放字段是否附 `completed_at`~~ **已落地可配置（commit `c8357fb`），待 UE 拍板是否开启**：response model 永远预留 `completed_at: str | None = None`（老 UE 看到 null 忽略，向后兼容）；config `AESIR_SCOPE_ASYNC_COMPLETED_AT`（默认 False）控制 completed 时是否填 UTC ISO 墙钟值。开了即开箱即用，不开零行为变化。UE 拍板"要"就开 env，"不要"保持默认。
3. ~~单请求预算上限默认值~~ **已澄清，无需拍板**：预算不是服务端写死的——`valid_for_ms` 直接取自 UE 请求自带的 `timing.max_request_age_ms`（[timing.py:38](../../app/scoped/timing.py#L38)），服务端硬上限 `max_budget_ms=120_000`（120s，[timing.py:25](../../app/scoped/timing.py#L25)）。异步化后排队**确实计入同一预算**，但实测排队 ~0ms + LLM 约 3s ≪ UE 自带的 30s，远未触顶。UE 侧只需在请求里给 `max_request_age_ms` 留足排队余量即可，服务端无默认值可调。

---

> 落地顺序建议：本稿与 UE 侧对齐开放问题后，先实现 §4 的 result 回放（同步模式下也能用：UE 同步拿到结果后仍可回查），再切 §3 的 202 提交。两步可独立上线，互不阻塞。

<a id="legacy-agent"></a>
## 兼容入口 v0.3

<a id="legacy-agent-npc服务契约v03"></a>
### NPC服务契约v0.3

> 2026-10-19按源码`a2dd426`校对。这里维护统一代理、世界事件、调试和回执的当前交界；需求目标见[SDD v1.1](../planning/_11_npc_requirements.md)。本轮只修文档，未改变schema或执行运行验收。

云端身份、作用域与有效期见[v0.4契约](_01_npc_contract.md#scope)和[第二步实施计划](../planning/_03_identity_scope_plan.md)，已于2026-10-21批准并完成服务端实现及适用回归，随后合入main；配置/调用见[v0.4开发与交接](../guides/_04_scoped_development_guide.md)。旧入口仅在显式开发兼容模式开放，默认关闭。本页仍描述legacy v0.3，不能直接向旧请求添加scoped字段。

2026-10-21新增[远程部署目标](../guides/_07_deployment_guide.md)：v0.4已有开发身份、玩家/存档作用域与重置epoch子集；正式账号/HTTPS、数据库事务、版本同步、外部ASR和模型分发仍须分别验收。下表保留旧schema及兼容事实，不以旧入口限制概括新版。

同日采纳的[交互演进计划](../planning/_06_interaction_evolution_plan.md)补轮次/取消、事件治理、TTS播放、来源记忆和持久幂等等完整目标。D1～C4及AT-EVO是计划/验收编号；新概念先核对v0.4已有字段，再按影响修改schema和golden，不向legacy请求混填。started/hit/completed、游标、TTS和取消等仍不因目标出现而成为当前API。

<a id="legacy-agent-1-端点与版本"></a>
#### 1. 端点与版本

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

订单/对话和语音完整类型见[v0.1](_01_npc_contract.md#legacy-dialogue)，战斗快照/意图/决策见[v0.2](_01_npc_contract.md#legacy-tactical)。启动与接入步骤见[联调指南](../guides/_12_legacy_integration_guide.md)。`GET /health`实际返回protocol_version=0.1和service_commit，前者不替代本表。

<a id="legacy-agent-2-agentstep"></a>
#### 2. agent/step

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

玩家text分支复用意图解析：战斗意图需要world_context.combat，缺少时none + COMBAT_CONTEXT_MISSING；非战斗意图按场景、目录与可交互目标校验。无法识别时none + INTENT_UNRECOGNIZED并澄清。纯心跳按“禁打断→候选→目录→仲裁→节流”产生一个建议或无动作，默认同角色最小间隔2秒，超频429。配置和重启语义见[启动指南](../guides/_02_local_setup_guide.md)。

<a id="legacy-agent-3-世界事件与幂等"></a>
#### 3. 世界事件与幂等

[WorldEventRequest](../../app/schemas/world_event.py)包含版本0.3、字符串request_id、companion_id、event和world_context。event有非空event_id、枚举event_type、occurred_at、非负sequence及字符串字典details；request_id当前不是UUID类型，不能把agent/step的UUID校验推广到此端点。

事件类型为六类战斗事件及六类生活事件：`region_first_entered/weather_changed/gift_given/companion_recovered/player_protected_companion/promise_kept`。先验证角色及当前游戏事件声明；未知角色404，未声明事件403，不合法枚举/结构422。服务使用事实更新记忆/关系，不从玩家一句请求推定游戏事件已发生。

响应包含event_id、duplicate、reaction、recommendation_text、可空companion_action及observability。companion_action当前仍是v0.2 DecisionAction，不是统一DirectiveEnvelope；生活事件没有可执行动作。关系变化、原因码和阶段按实际路径返回。

- 战斗键为`(companion_id, encounter_id, event_id)`，生活键的遭遇部分为空串；与combat/events共享1024项进程内缓存，锁内完成首次评估。
- 重试同一事实保留event_id。命中缓存回放首次反应/动作并标duplicate，不新生成order_id；不同角色或遭遇分别处理。
- 缓存淘汰最旧项，服务重启即丢失；不承诺永久恰好一次。UE仍对动作ID执行去重，并检查旧游玩、有效期、目标和当前状态，避免重放动作。

<a id="legacy-agent-4-执行回执"></a>
#### 4. 执行回执

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

<a id="legacy-agent-5-调试与记忆重置"></a>
#### 5. 调试与记忆重置

| 实际路由 | 输入与结果 |
| --- | --- |
| `GET /v1/console/state?companion_id=...` | 当前运行观测、注册角色、人格/策略版本、关系及近期记忆；最近状态不代表任意历史决策的完整解释 |
| `GET /v1/console/memory?companion_id=...` | 指定角色的四层记忆视图；存储读取失败503 |
| `POST /v1/console/memory/reset` | JSON仅指定companion_id；先清该角色会话，再清持久记忆，返回companion_id/reset/cleared_sessions |
| `GET /v1/console/ui` | 内联调试HTML；当前页面用Alice作为初始查询，其他游戏的首个角色适配仍有差距 |

这些操作先查注册角色，未知/跨游戏角色404。reset不重建人格、不重置关系、不清对话信号或回执日志，也不能证明远端LLM/ASR数据已删除。持久清理失败时返回reset=false，会话可能已清，不承诺回滚或原状态不变。无需为此新增UE重置按钮。

当前没有`/v1/console/relationship/*`通用读写API；关系可从state读取，不能把曾经的通配写法当已实现路由。调试接口默认无额外认证，仅适用当前本机开发边界；不要从监听回环推断外部LLM没有出站数据。

<a id="legacy-agent-6-错误与版本边界"></a>
#### 6. 错误与版本边界

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

<a id="legacy-agent-7-当前实现差距"></a>
#### 7. 当前实现差距

| 目标 | 当前限制与接入处理 |
| --- | --- |
| 游戏/角色/能力隔离 | agent/step、world/events、对话/console有角色检查；旧parse/voice默认目录、v0.2战术与回执没有同等全面的角色/当前游戏绑定。正式接入显式提供当前目录，不能用L3门控替代逐角色授权 |
| 统一身份及阶段回执 | directive/order映射与阶段/终态待对齐；当前只存回执，不能宣称状态机已实现 |
| 幂等与旧局隔离 | 服务有限缓存与UE执行去重分开；UE必须检查游玩/遭遇/请求及有效期，不把重试等同清NPC长期状态 |
| 参数/性能 | 心跳2秒是配置；历史单次HTTP耗时不是P95。硬件、样本、计时边界与正式阈值按SDD/联调口径冻结 |
| 数据保留 | 无session仍可持久化，默认信号含完整文本；LLM可出站。允许字段/后端、保留/删除范围见[LLM指南](../guides/_03_llm_integration_guide.md)，未决定部分明示待确认 |

<a id="legacy-agent-8-来源与维护"></a>
#### 8. 来源与维护

本页按现存schema/路由静态核对，不否认2026-10-08在8000实例取得的历史HTTP样本；单次结果和环境见[联调记录](../guides/_12_legacy_integration_guide.md#历史实测与适用范围)。当前默认8011，不全局改写历史端口。规则变更同步SDD、模型、对应契约及验收；历史材料和当前规范分别标识。

<a id="legacy-tactical"></a>
## 兼容战术 v0.2

<a id="legacy-tactical-战斗事件与上下文感知战术协议-v02"></a>
### 战斗事件与上下文感知战术协议 v0.2

> 状态：**正式版（2026-09-09 定稿）。** Schema 层（§3~§5）、`/v1/tactical/resolve`（规则策略 v1）、`/v1/tactical/executions`（回执落 JSONL）与 `/v1/combat/events`（事件策略 v1 + `event_id` 幂等）均已实现并有测试。v0.1 端点全部保留可用。UE 侧可按本协议开发；字段删除或语义变化必须升级 `protocol_version`。
>
> 目标：在不破坏 v0.1 的前提下，增加战斗状态快照、自动事件、上下文战术决策、可观察字段和 UE 执行回执。
>
> 校对日期：2026-10-19；源码基线`a2dd426`。接口存在、测试材料与UE实际执行分别记录，本轮未运行服务。
>
> **当前分工：**本页定义仍兼容的战斗快照、意图与决策；统一代理、世界事件、调试和回执边界见[NPC契约v0.3](_01_npc_contract.md#legacy-agent)。需求主文为[SDD v1.1](../planning/_11_npc_requirements.md)。v0.2保持规则决策，关系调制在agent/step编排，不能由此推断旧端点已经接入关系调制。

---

<a id="legacy-tactical-1-版本和端点矩阵"></a>
#### 1. 版本和端点矩阵

| 端点 | 状态 | 用途 |
| --- | --- | --- |
| `GET /health` | 已实现 v0.1 | 服务健康检查 |
| `POST /v1/companion/chat` | 已实现 v0.1 | 非战斗文本聊天 |
| `POST /v1/commands/parse` | 已实现 v0.1 | 文本 → 基础战术订单 |
| `POST /v1/voice/command` | 已实现 v0.1 | multipart 音频 → mock/ASR → 基础战术订单 |
| `POST /v1/speech/transcribe` | 已实现 | 单独转写音频，返回文本与语言 |
| `POST /v1/tactical/resolve` | 已实现（规则策略 v1） | 语义意图 + 状态快照 → 上下文战术决策 |
| `POST /v1/tactical/command` | 已实现（规则意图解析 v1） | **组合端点**：文本 + 状态快照 → 上下文战术决策，一次调用 |
| `POST /v1/combat/events` | 已实现（事件策略 v1 + 幂等） | UE 关键事件 → 艾莉反应/建议/候选动作 |
| `POST /v1/tactical/executions` | 已实现 | UE 回传接受、执行或拒绝原因 |

`/v1/commands/parse` 可以在 v0.2 中继续承担“文本到意图”的前半段；`/v1/tactical/resolve` 负责决定具体技能。当前可直接调用`/v1/tactical/command`；v0.1 parse返回的是TacticalOrder，不是本页TacticalIntent，不能把其响应原样当resolve请求。若分步调用，调用方须形成符合§4的意图。

---

<a id="legacy-tactical-2-共同规范"></a>
#### 2. 共同规范

<a id="legacy-tactical-21-id关联与时间"></a>
##### 2.1 ID、关联与时间

| 字段 | 生成方 | 规则 |
| --- | --- | --- |
| `request_id` | UE | 建议UUID v4；v0.2模型实际按字符串接收并回显 |
| `encounter_id` | UE | 本场 Boss 战唯一 ID；战斗结束后失效 |
| `snapshot_id` | UE | 状态快照唯一 ID；用于排查时效性 |
| `event_id` | UE | 一次状态边沿唯一 ID；重试必须复用同一 ID |
| `order_id` | Python | UUID v4；单一动作候选的关联 ID |
| `decision_id` | Python | UUID v4；一次策略决策的关联 ID |
| `ability_id` | UE DataAsset | 稳定白名单 ID，禁止使用中文名做逻辑键 |

时间字段用 ISO-8601 UTC，例如 `2026-09-03T12:00:00Z`；格式非法按 HTTP 422 拒绝（`captured_at` 与 `occurred_at` 均校验）。游戏内时间或剩余秒数用 number（秒）。

<a id="legacy-tactical-22-状态快照不是指令"></a>
##### 2.2 状态快照不是指令

- `CombatContext` 只描述 UE 观测到的事实；Python 不得对其修改后当作权威状态。
- 本页战斗链路在玩家命令或边沿事件发生时上传，不逐Tick请求。v0.3自主行为有单独的限频心跳，不与本页事件链路混淆。
- UE 接收响应时应比较 `encounter_id`；战斗已经结束、目标死亡或快照明显过期时，丢弃动作但仍可显示文本。
- UE 必须以当前本地状态重验动作，即使服务声明 `status:"actionable"`。

<a id="legacy-tactical-23-枚举与错误"></a>
##### 2.3 枚举与错误

- 已声明且受校验的类型、枚举、必填字段错误：HTTP`422`。v0.2多项ID仍是普通字符串，部分模型默认忽略额外字段；实际边界见末节，不保证所有UUID/额外字段都被拒绝。
- 合法请求但文本不可理解：HTTP `200`，`recognized:false`。
- 合法请求但当前无安全动作：HTTP `200`，`decision.status:"not_actionable"`。
- LLM/ASR 不可用：HTTP `200` 且 `source:"rule_fallback"`（可安全回退时），否则 `502/503` 并由 UE 执行本地降级。

---

<a id="legacy-tactical-3-combatcontext战斗状态快照"></a>
#### 3. `CombatContext`（战斗状态快照）

所有战术落地和自动事件共享该对象。字段先保持小而稳定；新增字段必须兼容旧客户端。

```json
{
  "encounter_id": "encounter.20260903.001",
  "snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd",
  "captured_at": "2026-09-03T12:00:00Z",
  "mode": "combat",
  "player": {
    "id": "party.player",
    "hp_percent": 18,
    "is_downed": false,
    "distance_to_boss_m": 4.5
  },
  "companion": {
    "id": "companion.alice",
    "hp_percent": 83,
    "mp_percent": 72,
    "current_behavior": "ranged_attack",
    "ability_states": {
      "ability.alice.basic_attack": "ready",
      "ability.alice.explosion": "ready",
      "ability.alice.quick_heal": "ready",
      "ability.alice.major_heal": "ready",
      "ability.alice.shield": "ready"
    }
  },
  "boss": {
    "id": "encounter.primary_hostile",
    "hp_percent": 42,
    "stun_percent": 100,
    "state_tags": ["state.stunned"],
    "stunned_remaining_seconds": 4.5,
    "phase": 2,
    "is_enraged": false
  }
}
```

<a id="legacy-tactical-31-字段约束"></a>
##### 3.1 字段约束

| 路径 | 类型/范围 | 说明 |
| --- | --- | --- |
| `mode` | `combat` | 本协议仅处理战斗；聊天用现有 chat 接口 |
| `*.hp_percent` / `mp_percent` / `stun_percent` | number, `[0,100]` | 使用百分比，避免跨端最大值差异 |
| `distance_to_boss_m` | number, `>=0` | 仅作策略参考，UE 最终判定距离 |
| `ability_states.*` | `ready` / `cooldown` / `unavailable` / `blocked` | 只列当前目录中能力 |
| `state_tags` | 稳定状态 ID 数组 | 例如 `state.stunned`、`state.enraged` |
| `stunned_remaining_seconds` | number 或 `null` | 不在眩晕时为 `null` |

首版不要上传完整位置向量、每个敌人的逐帧状态、动画帧或伤害流水；这些高频数据留在 UE。之后若做 RL，可另建低频观测接口，不污染该协议。

---

<a id="legacy-tactical-4-文本语义意图-tacticalintent"></a>
#### 4. 文本语义意图 `TacticalIntent`

语义意图表达“玩家想做什么”，不直接承诺施放哪一个技能。它由规则/LLM 解析生成，必须可验证。

```json
{
  "intent_id": "support_heal_player",
  "target_id": "party.player",
  "timing": "immediate",
  "preferences": {
    "strength": "unspecified",
    "resource_conservation": "normal"
  },
  "normalized_text": "艾莉，治疗玩家",
  "parse_confidence": 0.92
}
```

战斗意图的主要取值如下；实际`TacticalIntent`还保留`inspect_interactable/pickup_item/rest_here/wait_here`四项，用于v0.3非战斗分流。v0.2 CombatContext仍仅适用于combat，不能因意图枚举存在就认定其支持非战斗场景。

| ID | 说明 |
| --- | --- |
| `support_heal_player` | 治疗玩家 |
| `support_protect_player` | 给玩家护盾/保命 |
| `burst_boss` | 对 Boss 使用爆发输出 |
| `prepare_burst_on_stun` | Boss 眩晕时爆发 |
| `focus_fire_boss` | 集火 Boss |
| `retreat_and_survive` | 撤离保命 |
| `follow_player` | 跟随玩家 |

`parse_confidence` 是辅助观察字段，不能独自允许危险动作；低置信度时应返回澄清或保守策略。

---

<a id="legacy-tactical-5-post-v1tacticalresolve已实现规则策略-v1"></a>
#### 5. `POST /v1/tactical/resolve`（已实现：规则策略 v1）

<a id="legacy-tactical-51-请求"></a>
##### 5.1 请求

```json
{
  "protocol_version": "0.2",
  "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "intent": {
    "intent_id": "support_heal_player",
    "target_id": "party.player",
    "timing": "immediate",
    "preferences": {
      "strength": "unspecified",
      "resource_conservation": "normal"
    },
    "normalized_text": "艾莉，治疗玩家",
    "parse_confidence": 0.92
  },
  "combat_context": { "...": "见第 3 节" }
}
```

<a id="legacy-tactical-52-响应濒危治疗示例"></a>
##### 5.2 响应：濒危治疗示例

```json
{
  "protocol_version": "0.2",
  "request_id": "88d7e6b4-f4f2-4d39-8c96-a23d293882f6",
  "recognized": true,
  "source": "rule",
  "decision": {
    "decision_id": "32b8d0f4-5432-4374-a972-7c0da10c272e",
    "status": "actionable",
    "intent_id": "support_heal_player",
    "action": {
      "order_id": "527b4c0d-0fe1-4e4c-9057-3c991ba1616c",
      "agent_id": "companion.alice",
      "type": "cast_ability",
      "ability_id": "ability.alice.major_heal",
      "target_id": "party.player",
      "priority": 95,
      "expires": { "type": "immediate" },
      "authority": "player_requested"
    },
    "reason_codes": [
      "PLAYER_HP_CRITICAL",
      "BOSS_IN_MELEE_RANGE",
      "MAJOR_HEAL_READY"
    ],
    "explanation": "玩家生命值危急，强效治疗当前可用。"
  },
  "companion_reply": {
    "reply_text": "别硬撑！这次我会彻底把你拉回来。",
    "emotion_id": "emotion.concerned",
    "gesture_id": "gesture.cast_support",
    "facial_expression_id": "face.concerned",
    "interruptible": false
  },
  "observability": {
    "normalized_text": "艾莉，治疗玩家",
    "policy_revision": "support-policy-001",
    "used_snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd"
  }
}
```

<a id="legacy-tactical-53-决策状态"></a>
##### 5.3 决策状态

| `decision.status` | 含义 | UE 行为 |
| --- | --- | --- |
| `actionable` | 有候选动作 | 本地校验后可登记到队友 AI |
| `advisory` | 只有建议，无自动动作 | 显示 UI/台词，不强制 AI 施法 |
| `not_actionable` | 当前没有安全动作 | 显示说明；保持当前本地 AI |
| `clarification_needed` | 指令歧义较大 | 请求玩家重述或提供候选 |

`authority` 为 `player_requested` 或 `event_policy`。无论其值是什么，UE 均拥有最终否决权。

<a id="legacy-tactical-54-post-v1tacticalcommand组合端点已实现"></a>
##### 5.4 `POST /v1/tactical/command`（组合端点，已实现）

等价于「文本 → 意图 → resolve」的**一次调用**版本，UE 可省一次往返。请求把
`intent` 字段换成 `text`：

```json
{
  "protocol_version": "0.2",
  "request_id": "<uuid4>",
  "text": "艾莉，帮我回一下血",
  "combat_context": { "...": "见第 3 节" }
}
```

- 响应结构与 `/v1/tactical/resolve` 完全一致（`ResolveResponse`）。
- 文本先经规则意图解析（`app/services/tactical/intent_parser.py`），由关键词匹配当前11项意图白名单，并按角色配置检查唤醒词（例如艾莉/Alice），
  再走同一份上下文策略；`AESIR_INTENT_BACKEND=llm`已可选择LLM解析，失败回退规则，具体配置见[LLM指南](../guides/_03_llm_integration_guide.md)。
- 文本不可识别时按当前SDD回复澄清：HTTP 200 + `recognized:false` +
  `decision:null` + 澄清台词——不猜测、不施放。
- 多意图冲突按意图优先级判序（撤退 > 等眩晕爆发 > 治疗 > 保护 > 爆发 > 集火 > 跟随），
  与 v0.1 规则解析器同一纪律。

---

<a id="legacy-tactical-6-post-v1combatevents服务端已实现"></a>
#### 6. `POST /v1/combat/events`（服务端已实现）

> **实现注记（2026-09-08）**：`app/api/v1/combat.py`、`app/schemas/combat_event.py`、
> `app/services/tactical/event_policy.py`。事件反应从data/personas人格包reactions.yaml的
> `combat_event_reactions` 读取（ID 越界回退安全默认）；动作候选仅在能力就绪
> 且蓝量允许时返回，否则为 `null`（不虚构动作）。眩晕窗口的动作过期时间
> 绑定快照 `stunned_remaining_seconds`。治疗/蓝量阈值复用 resolver 常量。

<a id="legacy-tactical-61-请求"></a>
##### 6.1 请求

```json
{
  "protocol_version": "0.2",
  "request_id": "779a1aa2-6358-4641-8393-e8c20e5e827d",
  "event": {
    "event_id": "event.encounter.001.boss_stunned.002",
    "event_type": "boss_stunned",
    "occurred_at": "2026-09-03T12:00:00Z",
    "sequence": 2
  },
  "combat_context": { "...": "见第 3 节" }
}
```

`event_type` 首版固定为：`player_hp_critical`、`boss_stun_near`、`boss_stunned`、`boss_enraged`、`companion_mp_low`、`boss_defeated`。

<a id="legacy-tactical-62-响应boss-眩晕示例"></a>
##### 6.2 响应：Boss 眩晕示例

```json
{
  "protocol_version": "0.2",
  "request_id": "779a1aa2-6358-4641-8393-e8c20e5e827d",
  "event_id": "event.encounter.001.boss_stunned.002",
  "source": "rule",
  "reaction": {
    "reply_text": "就是现在！它动不了了，我们一起解决它！",
    "emotion_id": "emotion.excited",
    "gesture_id": "gesture.point_target",
    "facial_expression_id": "face.focused",
    "interruptible": true
  },
  "recommendation": {
    "type": "focus_fire",
    "target_id": "encounter.primary_hostile",
    "reason_codes": ["BOSS_STUNNED", "BURST_WINDOW_OPEN"],
    "display_text": "Boss 眩晕中，建议集火。"
  },
  "companion_action": {
    "order_id": "c5a116c3-9c7b-4c72-98a0-db8f41bc155a",
    "agent_id": "companion.alice",
    "type": "cast_ability",
    "ability_id": "ability.alice.explosion",
    "target_id": "encounter.primary_hostile",
    "priority": 85,
    "expires": { "type": "before_seconds", "remaining_seconds": 4.0 },
    "authority": "event_policy"
  },
  "observability": {
    "policy_revision": "event-policy-001",
    "used_snapshot_id": "a59b0eb4-79b8-49b0-a17c-f4c6ae5119bd"
  }
}
```

`companion_action` 可为 `null`：例如艾莉蓝量低、爆裂 CD 中，服务仍可返回反应和建议，但不得虚构可施放动作。

<a id="legacy-tactical-63-事件幂等与ue执行去重"></a>
##### 6.3 事件幂等与UE执行去重

服务使用`(companion_id, encounter_id, event_id)`作为战斗事实幂等键，与v0.3世界事件通道共享缓存；生活事件的遭遇部分为空串。

- 首次处理返回`duplicate:false`；相同键重试回放首次反应/候选动作并标`duplicate:true`，请求ID回显本次请求，order_id不重新生成。
- 缓存是单进程内存的1024项有界表，淘汰最旧项；进程重启不保留。它不承诺跨重启或淘汰后的永久恰好一次，冷却也不代替幂等。
- 同一event_id在不同角色/遭遇中是不同作用域。UE重试同一事实应保留ID，并对回放的order_id另外做执行去重；相同order_id本身不能证明世界动作不重复。
- 返回候选建议不等于已经启动或命中。旧游玩、结束遭遇或过期建议必须由UE拒绝。

---

<a id="legacy-tactical-7-执行回执单条兼容与批量"></a>
#### 7. 执行回执（单条兼容与批量）

`POST /v1/tactical/executions`支持`{"receipt":{...}}`或`{"receipts":[...]}`，二选一且批量非空。单条兼容v0.2，批量为后来增加的能力；实际信封没有顶层protocol_version字段，每条ExecutionReceipt的protocol_version固定0.2。完整字段及示例集中见[NPC契约回执节](_01_npc_contract.md#legacy-agent-4-执行回执)。

`result`实际只允许`accepted/executed/rejected/expired/cancelled`。accepted表示登记/受理，不是命中或完成；202仅表示记录受理。当前仅追加JSONL，没有按order维护状态机、重复/乱序合并或验证真实动作。需要的开始、命中、完成阶段是需求目标，不能无版本设计就改成已支持的新枚举。

按UTC日期写入`data/runtime/command_service/executions/<game_id>/<YYYYMMDD>.jsonl`。旧文中缺game_id层的路径不再是当前默认。请求game_id尚未绑定当前进程游戏，是待修差距；回执不自动用于训练，也不能反向制造战斗事实。

---

<a id="legacy-tactical-8-语音规范化与安全"></a>
#### 8. 语音、规范化与安全

<a id="legacy-tactical-81-音频传输"></a>
##### 8.1 音频传输

语音命令入口`/v1/voice/command`使用multipart字段`file`、可选UUID `request_id`和`context_json`，返回v0.1 ParseCommandResponse；纯转写入口`/v1/speech/transcribe`使用`audio`、可选request_id/locale，实际返回`request_id/text/language`，没有协议版本、置信度或source字段。二者完整格式见[v0.1契约](_01_npc_contract.md#legacy-dialogue-53-语音转写)。

传输约定为16kHz、单声道、16-bit PCM WAV。当前入口未统一限制大小/时长或验证全部音频参数，不能把建议格式当已实现门禁。闲聊语音使用`/v1/companion/chat/voice`，不把语音命令入口当对话分流器。

<a id="legacy-tactical-82-词典输入输出示例"></a>
##### 8.2 词典输入/输出示例

```json
{
  "raw_text": "艾莉奶我一口，等它出破绽就丢大招",
  "normalizations": [
    { "source": "奶我一口", "canonical": "治疗玩家", "kind": "controlled_alias" },
    { "source": "出破绽", "canonical": "state.stunned", "kind": "controlled_alias" },
    { "source": "大招", "canonical": "ability.alice.explosion", "kind": "catalog_alias" }
  ]
}
```

词典优先级：UE 当前能力目录 > 玩家已确认别名 > 项目受控词典 > LLM 推断。任一步出现冲突时，不能静默选择危险技能。

---

<a id="legacy-tactical-9-ue-接入伪流程"></a>
#### 9. UE 接入伪流程

```text
OnPlayerVoiceCommand(audio):
  1. 获取一次当前CombatContext（非Tick）
  2. 调/v1/speech/transcribe得到文本
  3. 以text + combat_context调/v1/tactical/command；不把v0.1 order误当TacticalIntent
  4. 校验 encounter_id、agent_id、ability_id、CD/MP/距离/角色状态
  5. 若通过：TacticalOrderComponent.Register(order)
  6. 显示 companion_reply / explanation
  7. 执行完成后上报 execution result

OnBossStunned():
  1. 若 event_id 已处理：return
  2. 生成 snapshot 与 event_id，调用 /v1/combat/events
  3. 立即播放/显示 reaction
  4. 本地校验 companion_action；通过才登记
```

HTTP 回调不可直接操作角色 Actor；回调应投递到子系统/指令组件，由该组件在游戏线程和当前局面下作最终处理。

---

<a id="legacy-tactical-10-v01-迁移原则"></a>
#### 10. v0.1 迁移原则

1. v0.1的`/v1/commands/parse`、TacticalOrder和golden JSON继续按兼容契约维护，不由v0.2或v0.3的存在推断删除。
2. `companion.eirin` 是旧默认样例，v0.2 联调统一改为 `companion.alice`；修改默认目录、规则解析和 UE DataAsset 时必须一起提交。
3. 不修改旧响应字段语义；新能力采用新端点和 `protocol_version:"0.2"`。
4. 先写 Pydantic schema、golden tests 和 mock response，再实现策略，最后接 UE。
5. 正式升级前，以“同一治疗命令、至少四份状态快照”的回归集验证行为稳定。


<a id="legacy-tactical-11-当前验证与实现边界"></a>
#### 11. 当前验证与实现边界

- `ResolveRequest/TacticalCommandRequest`校验版本0.2，request_id为普通字符串；CombatContext.snapshot_id等也不是UUID类型。它们及若干决策模型未设置extra=forbid，额外字段可能被忽略，严格拒绝仍需实现与兼容评估。
- L3端点等级门控已经存在，但v0.2 resolver没有完整统一执行“已注册角色404、当前游戏逐能力授权”的入口校验；能力ready检查不等同人格注册或游戏能力目录全验证。UE最终复核仍必需。
- 策略YAML、配置及JSONL存储仍可能失败；LLM解析有回退不等于整条链路保证永无500。按实际响应和日志处理故障，未验收能力列入SDD实现差距。
- 本页示例是契约/历史样例，不是当前UE联调结果；当前配置、分阶段检查与历史样本见[联调指南](../guides/_12_legacy_integration_guide.md)。Boss RL为独立服务，训练/部署/评估见[RL入口](../../rl/README.md)。

<a id="legacy-dialogue"></a>
## 兼容订单、对话与 SSE v0.1

<a id="legacy-dialogue-aesir-combat-prototypeue5--模型服务-协议契约-v01"></a>
### Aesir Combat Prototype｜UE5 × 模型服务 协议契约 v0.1

> 兼容契约：v0.1订单、对话及语音接口。2026-10-19按源码基线`a2dd426`校对；需求主文见[SDD v1.1](../planning/_11_npc_requirements.md)。
> 适用范围：仍兼容的单机ARPG订单、语音解析和人格对话。Boss RL是独立工作流，不由本页规定其训练或部署。
> 本轮只修正文档说明，不升级接口或修改模型。Golden示例用于类型核对，不代表已完成UE执行验收。

本文由原《协议格式契约》与《UE5 × 模型服务联调技术规范》合并而成，只保留**类型穷尽定义**与**两端共同契约**，删除会随进度过期的「进度/目标」章节。

> **实现状态说明：** 本文是当前代码已经实现的 v0.1 格式基线。战斗状态快照、自动事件、上下文技能选择、执行回执不属于本版本；请参见[战斗事件与上下文感知战术协议v0.2](_01_npc_contract.md#legacy-tactical)。v0.2 中 `/v1/tactical/resolve`（规则策略 v1）、`/v1/combat/events`、`/v1/tactical/executions` 均已在 Python 侧实现。
>
> **当前分工：**本页保留仍兼容的`TacticalOrder`和对话协议；统一指令、世界事件、调试及回执的当前说明见[NPC契约v0.3](_01_npc_contract.md#legacy-agent)。API版本与人格包版本分开管理，不因存在v0.3删除旧端点。

---

<a id="legacy-dialogue-1-目标边界与本契约要回答的问题"></a>
#### 1. 目标、边界与本契约要回答的问题

本项目让玩家以文本或语音下达战术命令；Python 服务将自然语言转换为受限的 `TacticalOrder`，UE5 验证并执行该命令。

典型体验：

> “艾莉，等 Boss 眩晕时使用爆裂魔法。”

```text
语音（可选） → ASR 转写 → LLM/规则解析 → TacticalOrder JSON
→ UE 再校验 → 队友任务队列 → Boss 状态触发 → 走位与施法
```

本文要明确回答五个问题：

1. 一个 order 到底有哪些合法形态？（按 `intent` 判别 → 5 份 golden JSON）
2. `when` / `then` / `expires` 各有哪些合法形态？（按 `type` 判别）
3. `priority` 是数字，范围 / 默认 / 排序规则？
4. 协议版本在哪一层校验？（外层 or order 内）
5. 哪些 ID 合法、越界怎么回？（能力目录白名单约束）

<a id="legacy-dialogue-本契约不覆盖的事"></a>
##### 本契约不覆盖的事

- 不让 LLM 逐帧操控角色、移动、碰撞或技能伤害。
- 不让 Python 作为战斗规则的唯一裁决者。
- 不在首版引入向量数据库、长期记忆、多智能体编排或开放世界任务规划。
- 不让强化学习直接决定伤害、CD、资源消耗或技能是否合法。

---

<a id="legacy-dialogue-2-架构与职责划分"></a>
#### 2. 架构与职责划分

| 层 | 唯一职责 | 不得负责 |
| --- | --- | --- |
| UE5 / C++ | 战斗状态、命中、CD、蓝量、导航、动画、技能执行、最终校验 | 调用大模型进行逐帧决策 |
| Python API | 请求编排、Schema 校验、日志、规则/LLM/ASR 适配 | 修改游戏世界或绕过 UE 规则 |
| ASR | 音频转文字 | 解释战术语义 |
| LLM | 文本转受限战术命令 | 直接发出移动、伤害或 Tick 级操作 |
| Boss RL独立服务 | 由[RL入口](../../rl/README.md)定义观测、动作、冻结部署与评估 | 不属于本页NPC订单接口 |

<a id="legacy-dialogue-运行时拓扑"></a>
##### 运行时拓扑

```text
UE5 客户端                                        Python 本地服务
────────────────────────────                      ───────────────────────────
Push-to-Talk → Audio Capture → WAV/PCM ────────→  /v1/speech/transcribe
                                                    ASR → 转写文本
UE UI / 文本输入 ──────────────────────────────→  /v1/commands/parse
                                                    规则解析器或 LLM
                                                    Pydantic + 能力目录校验
             ←──── TacticalOrder JSON ─────────
UE 再校验 → TacticalOrderComponent → BT/StateTree → GAS/技能系统
```

语音、ASR、LLM 均必须异步。游戏主线程不等待网络响应；超时或服务故障时，队友回退到基础 AI。

---

<a id="legacy-dialogue-3-当前技术与权威位置"></a>
#### 3. 当前技术与权威位置

服务使用FastAPI/Pydantic、规则/可配置LLM解析和mock/本机faster_whisper转写。依赖版本与启动命令集中在[启动指南](../guides/_02_local_setup_guide.md)。UE使用异步HTTP及JSON解释本页类型，实际模块/组件和资产接线由UE仓维护；历史AudioCapture或组件布置建议不是本仓已接入事实。

LLM后端、数据出站与配置生命周期见[LLM指南](../guides/_03_llm_integration_guide.md)。Boss冻结PPO现由独立HTTP服务与UE共享动作执行器接入，见[RL入口](../../rl/README.md)；旧队友走位/ONNX设想不是当前Boss契约或启动前置。

---

<a id="legacy-dialogue-4-协议总则"></a>
#### 4. 协议总则

<a id="legacy-dialogue-41-核心原则"></a>
##### 4.1 核心原则

1. **LLM 输出不可信。** Python 和 UE 都必须校验。
2. **显示名不进入协议。** 协议只使用稳定 ID；“艾莉”“爆裂魔法”只用于 UI 与 Prompt 映射。
3. **能力目录与命令结构分离。** Schema 定义字段；UE 能力目录决定哪些 ID 当前可用。
4. **低频命令、事件驱动执行。** 仅在按住说话结束或文本提交时请求服务，禁止 Tick 请求。
5. **UE 最终裁决。** 即使命令合法，也必须检查目标存活、距离、资源、冷却和角色状态。

<a id="legacy-dialogue-42-id-命名"></a>
##### 4.2 ID 命名

所有 ID 使用小写英文与点号分层：

```text
角色：companion.alice
技能：ability.alice.explosion
技能：ability.alice.basic_attack
状态：state.stunned
状态：state.phase_two
目标选择器：encounter.primary_hostile
目标选择器：party.player
```

这些 ID 应与 UE Gameplay Tag 或 Data Asset 的主键建立一对一映射；不要使用资产路径、动画名或中文显示名作 ID。

---

<a id="legacy-dialogue-5-api-契约"></a>
#### 5. API 契约

<a id="legacy-dialogue-51-健康检查"></a>
##### 5.1 健康检查

```text
GET /health
```

成功响应：

```json
{
  "status": "ok",
  "service": "aesir-ai-service",
  "protocol_version": "0.1",
  "service_commit": "<运行实例的short SHA，非Git环境为unknown>"
}
```

`/health.protocol_version`当前来自v0.1订单常量，不代表每个端点都使用0.1；端点版本见[v0.3入口矩阵](_01_npc_contract.md#legacy-agent-1-端点与版本)。`service_commit`用于识别运行实例，不应写死成本地HEAD。

<a id="legacy-dialogue-52-文本命令解析"></a>
##### 5.2 文本命令解析

```text
POST /v1/commands/parse
Content-Type: application/json
```

请求：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "text": "艾莉，等 Boss 眩晕时使用爆裂魔法。",
  "context": {
    "catalog_revision": "dev-001",
    "locale": "zh-CN",
    "agents": [
      {
        "id": "companion.alice",
        "ability_ids": [
          "ability.alice.explosion",
          "ability.alice.basic_attack"
        ]
      }
    ],
    "target_selectors": ["encounter.primary_hostile", "party.player"],
    "state_tags": ["state.stunned", "state.phase_two"]
  }
}
```

成功响应见 §6/§11。不识别文本时仍返回 HTTP `200`，但明确不执行：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": false,
  "message": "当前无法确认该技能或目标。",
  "order": null
}
```

> `POST /parse-command`是保留的调试别名，只传`text`并回填`DEFAULT_CONTEXT`。语音命令不传`context_json`也会使用该目录。正式接入应显式提交当前角色、能力及目标，不用默认Alice目录证明当前游戏/角色授权。

错误语义：

| 情况 | HTTP 状态 | UE 行为 |
| --- | --- | --- |
| 请求字段不合法 | 422 | 显示“命令格式错误”，不创建任务 |
| 文本不可识别 | 200 + `recognized: false` | 显示原因，维持原 AI |
| LLM / ASR 不可用 | 解析LLM可回退规则；ASR失败可502 | 根据实际状态显示原因，维持本地AI；不把降级当动作完成 |
| 超时（UE 建议 3 秒） | UE 本地取消 | 不阻塞主线程，维持原 AI |
| UE 本地校验失败 | UE 记录原因 | 不执行，显示“技能不可用”等原因 |

<a id="legacy-dialogue-53-语音转写"></a>
##### 5.3 语音转写

```text
POST /v1/speech/transcribe
Content-Type: multipart/form-data
```

字段：`audio`（WAV/PCM 文件）、`request_id`、`locale`。首版统一上传 **16 kHz、单声道、16-bit PCM WAV**。

响应：

```json
{
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "text": "艾莉，等 Boss 眩晕时使用爆裂魔法。",
  "language": "zh"
}
```

UE 收到转写后再调用 `/v1/commands/parse`。两步请求便于单独调试 ASR 和 LLM；后续可保留组合端点但不得删除这两个基础端点。

> **现状：** 组合端点 `POST /v1/voice/command`（multipart `file` + 可选 `request_id`/`context_json`）已实现，内部先 ASR 再送同一解析层，一次返回 `ParseCommandResponse`。`AESIR_ASR_BACKEND=faster_whisper` 走真实本机 Whisper（默认`small`模型，具体本机识别效果需按配置验证），`mock` 返回固定文本。专用 `POST /v1/speech/transcribe` 已实现，与组合端点并存，长期保留。

---

<a id="legacy-dialogue-6-顶层响应parsecommandresponse"></a>
#### 6. 顶层响应（`ParseCommandResponse`）

```json
{
  "protocol_version": "0.1",
  "request_id": "<uuid4 回显，来自请求>",
  "recognized": true,
  "message": "<给 UE HUD 的中文说明，仅展示用途，不作为逻辑字段>",
  "source": "rule | llm | rule_fallback",
  "order": { "order_id": "<uuid4>", "...see §7" },
  "companion_reply": { "reply_text": "...", "emotion_id": "..." }
}
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `protocol_version` | string | 固定 `"0.1"`，**只在响应外层校验**（见 §10.1） |
| `request_id` | string(uuid4) | 必须原样回显请求的 `request_id`；格式校验失败按 422 |
| `recognized` | boolean | `false` 时 `order` 必须为 `null`，且仍 HTTP 200 |
| `message` | string | 仅 UI 用，不含可被 UE/LLM 逻辑依赖的内容 |
| `source` | string | `rule` / `llm` / `rule_fallback`（LLM 失败回退规则的标记），供 UE 日志与降级观测 |
| `order` | order 判别联合 \| null | `recognized=false` 时必为 `null` |
| `companion_reply` | object \| null | 队友人设确认回复 `{reply_text, emotion_id}`（见 `data/personas/` 人格包）；`recognized=false` 时为 `null`。UE 可仅取 `reply_text`/`emotion_id` 做字幕与表情 |

---

<a id="legacy-dialogue-7-order-判别联合按-orderintent"></a>
#### 7. `order` 判别联合（按 `order.intent`）

<a id="legacy-dialogue-71-共享字段所有意图"></a>
##### 7.1 共享字段（所有意图）

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `order_id` | string(uuid4) | 服务端生成，跨端日志关联 |
| `agent_id` | string(ID) | 必须在请求 `context.agents[].id` 内 |
| `intent` | string(枚举) | 判别的判断字段 |
| `when` | when 判别联合 \| null | 见 §8；`null` = 立即生效 / 持续性指令 |
| `then` | then 判别联合 | 见 §8 |
| `priority` | int | `[0,100]`，默认 `50`，**数值高者优先覆盖**（见 §9） |
| `expires` | expires 判别联合 | 见 §8.4，默认 `{type:"encounter_end"}` |

<a id="legacy-dialogue-72-分支总览"></a>
##### 7.2 分支总览

| `intent` | `when` | `then` | 语义 |
| --- | --- | --- | --- |
| `conditional_cast` | `state_entered`(subject+tag) | `cast_ability`(ability_id+target) | 条件满足时施法一次 |
| `hold_ability` | `null` | `hold_ability`(ability_id, active) | 这一整段不释放某技能 |
| `prioritize_attack` | `null` | `set_priority`(mode) | 持续性：调整输出优先级 |
| `follow_keep_distance` | `null` | `follow`(target, keep_distance) | 持续性：跟随并维持距离 |
| `retreat` | `null` | `retreat` | 持续性：撤离、降进攻优先级 |

命令只表达高层意图：`when` 描述何时，`then` 描述做什么。`TacticalOrderComponent` 负责命令生命周期；Behavior Tree/StateTree 决定如何走位；GAS 或既有技能系统决定能否施放。

---

<a id="legacy-dialogue-8-when--then--expires-判别联合按-type"></a>
#### 8. `when` / `then` / `expires` 判别联合（按 `.type`）

`order` 按 `order.intent` 判别；`when` 按 `when.type` 判别；`then` 按 `then.type` 判别；`expires` 按 `expires.type` 判别。未知 `type` / 未知 `intent` / 未知 `then.type` → **目的地拒绝**（两端都必须校验，§4.1 原则 1）。

<a id="legacy-dialogue-81-whenv01-交付一种"></a>
##### 8.1 `when`（`v0.1` 交付一种）

| `type` | 字段 | 类型 | 约束 |
| --- | --- | --- | --- |
| `state_entered` | `subject` | string(目标选择器ID) | 必须在请求 `context.target_selectors` 内 |
| | `tag` | string(状态Tag) | 必须在请求 `context.state_tags` 内 |

> 持久/Tick 级调度不在本层表达：`when` 只描述“何时条件达成”，达成判断交给 `TacticalOrderComponent` + Boss 状态事件，不放进 `order`。

<a id="legacy-dialogue-82-then"></a>
##### 8.2 `then`

各 `then.type` 与现有动作词表**一比一映射**，UE `USTRUCT` 可平滑对应：

| `then.type` | 字段 | 类型 | 对应理论意图 |
| --- | --- | --- | --- |
| `cast_ability` | `ability_id` | string(ID) | `conditional_cast` |
| | `target` | 引用对象 或 目标选择器ID | 见 §10.2 |
| `hold_ability` | `ability_id` | string(ID) | `hold_ability` |
| | `active` | boolean | 默认 `true` |
| `set_priority` | `mode` | string(枚举) | `prioritize_attack` |
| `follow` | `target` | string(目标选择器ID) | `follow_keep_distance` |
| | `keep_distance` | boolean | 默认 `true` |
| `retreat` | — | — | `retreat` |

**`set_priority.mode` 枚举字典（v0.1）：**

| 值 | 含义 |
| --- | --- |
| `basic_attack_first` | 优先普通攻击 |
| `ability_first` | 优先技能（保留） |

<a id="legacy-dialogue-84-expiresv01-交付一种"></a>
##### 8.4 `expires`（`v0.1` 交付一种）

| `type` | 字段 | 说明 |
| --- | --- | --- |
| `encounter_end` | — | 本场遭遇结束前保持有效（默认） |

---

<a id="legacy-dialogue-9-priority-语义"></a>
#### 9. `priority` 语义

- 范围 `[0,100]`，默认 `50`。
- **数值高者覆盖低者**（`TacticalOrderComponent` 只在接到更高 `priority` 或 `expires` 到期时才替换当前命令）。
- 同源意图（如两次 `retreat`）不互相覆盖，用 `order_id` 区分。
- 越界（`<0` 或 `>100`）→ 422。

---

<a id="legacy-dialogue-10-格式约束收口"></a>
#### 10. 格式约束收口

<a id="legacy-dialogue-101-protocol_version-归属"></a>
##### 10.1 `protocol_version` 归属

只在**响应外层**校验（`"0.1"`）。`order` 对象内**不**携带 `protocol_version`，避免两端在两处各校验一份、版本漂移。UE 校验清单第 1 步的“版本不支持”只针对响应最外层字段。

<a id="legacy-dialogue-102-thentarget-的两种合法形态"></a>
##### 10.2 `then.target` 的两种合法形态

1. **目标选择器 ID 字符串**：引用请求 `context.target_selectors`（如 `"party.player"`）。
2. **引用对象**：`{ "ref": "when.subject" }`——引用 `when.subject` 已在条件里解析过的对象，避免重复解析。

> 不允许多义字符串自引用（如裸写 `"when.subject"`）。UE 端对 `{ref:...}` 只有「解析成功 / 报错」两种结果，无字符串前缀猜测逻辑。

<a id="legacy-dialogue-103-能力目录白名单硬约束"></a>
##### 10.3 能力目录白名单（硬约束）

**响应 `order` 只能引用请求 `context` 里出现过的 ID：**

- `agent_id` ∈ `context.agents[].id`
- `when.subject` / `then.target`（字符串形态）∈ `context.target_selectors`
- `when.tag` ∈ `context.state_tags`
- `then.ability_id` ∈ `context.agents[agent_id].ability_ids`

**越界边界（错误表划清）：**

| 情况 | 返回 |
| --- | --- |
| 请求 JSON 结构非法（缺字段 / 非 uuid / priority 越界） | HTTP `422` |
| 文本不可识别 / 意图落不到目录内 ID | HTTP `200` + `recognized:false` + `order:null` |

> 即：**“请求本身不合法”回 422；“合法请求但语义落空”回 200+recognized:false**。绝不把“目录外的 ID”当成 422，也不把“结构非法”静默降级成 recognized:false。

---

<a id="legacy-dialogue-11-golden-json5-份完整示例"></a>
#### 11. Golden JSON（5 份完整示例）

以下请求均使用同一能力目录：

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "text": "<不同意图的不同输入>",
  "context": {
    "catalog_revision": "dev-001",
    "locale": "zh-CN",
    "agents": [
      {
        "id": "companion.alice",
        "ability_ids": ["ability.alice.explosion", "ability.alice.basic_attack"]
      }
    ],
    "target_selectors": ["encounter.primary_hostile", "party.player"],
    "state_tags": ["state.stunned", "state.phase_two"]
  }
}
```

<a id="legacy-dialogue-111-conditional_cast唯一带-when-的意图"></a>
##### 11.1 `conditional_cast`（唯一带 `when` 的意图）

**请求 text：** `艾莉，等 Boss 眩晕时使用爆裂魔法。`

**响应 order：**

```json
{
  "order_id": "ea876be5-d861-4064-8f64-4ccb8a74db99",
  "agent_id": "companion.alice",
  "intent": "conditional_cast",
  "when": {
    "type": "state_entered",
    "subject": "encounter.primary_hostile",
    "tag": "state.stunned"
  },
  "then": {
    "type": "cast_ability",
    "ability_id": "ability.alice.explosion",
    "target": { "ref": "when.subject" }
  },
  "priority": 80,
  "expires": { "type": "encounter_end" }
}
```

<a id="legacy-dialogue-112-hold_ability"></a>
##### 11.2 `hold_ability`

**请求 text：** `艾莉，这一整场都不要放爆裂魔法。`

**响应 order：**

```json
{
  "order_id": "9f1b8c3a-c2d4-4f6e-8a0b-5e3d7f9c11a2",
  "agent_id": "companion.alice",
  "intent": "hold_ability",
  "when": null,
  "then": {
    "type": "hold_ability",
    "ability_id": "ability.alice.explosion",
    "active": true
  },
  "priority": 60,
  "expires": { "type": "encounter_end" }
}
```

<a id="legacy-dialogue-113-prioritize_attack"></a>
##### 11.3 `prioritize_attack`

**请求 text：** `艾莉，优先普通攻击。`

**响应 order：**

```json
{
  "order_id": "4d7a2ef1-9b3c-4c5d-8e6f-0a2b4c6d8e10",
  "agent_id": "companion.alice",
  "intent": "prioritize_attack",
  "when": null,
  "then": {
    "type": "set_priority",
    "mode": "basic_attack_first"
  },
  "priority": 50,
  "expires": { "type": "encounter_end" }
}
```

<a id="legacy-dialogue-114-follow_keep_distance"></a>
##### 11.4 `follow_keep_distance`

**请求 text：** `艾莉，跟着我并保持距离。`

**响应 order：**

```json
{
  "order_id": "b1c2d3e4-5f67-489a-bcde-f01234567890",
  "agent_id": "companion.alice",
  "intent": "follow_keep_distance",
  "when": null,
  "then": {
    "type": "follow",
    "target": "party.player",
    "keep_distance": true
  },
  "priority": 40,
  "expires": { "type": "encounter_end" }
}
```

<a id="legacy-dialogue-115-retreat"></a>
##### 11.5 `retreat`

**请求 text：** `艾莉，撤退并优先保命。`

**响应 order：**

```json
{
  "order_id": "c3d4e5f6-7089-4bcd-ef01-234567890123",
  "agent_id": "companion.alice",
  "intent": "retreat",
  "when": null,
  "then": {
    "type": "retreat"
  },
  "priority": 90,
  "expires": { "type": "encounter_end" }
}
```

<a id="legacy-dialogue-116-不可识别golden-负例"></a>
##### 11.6 不可识别（golden 负例）

**响应：**

```json
{
  "protocol_version": "0.1",
  "request_id": "1fad2e69-4a2d-4308-ad4f-2f8abb338b89",
  "recognized": false,
  "message": "当前无法确认该技能或目标。",
  "order": null
}
```

---

<a id="legacy-dialogue-12-两张必须同步的映射表"></a>
#### 12. 两张必须同步的映射表

| 现有动作类型（模型服务旧式） | `then.type`（本契约） |
| --- | --- |
| `CastAbility` | `cast_ability` |
| `HoldAbility` | `hold_ability` |
| `Attack` | `set_priority`(`basic_attack_first`) |
| `Follow` | `follow` |
| `Retreat` | `retreat` |

| 现有 intent 名（旧式） | `intent`（本契约，不变） |
| --- | --- |
| `conditional_cast` | `conditional_cast` |
| `hold_ability` | `hold_ability` |
| `prioritize_attack` | `prioritize_attack` |
| `follow_keep_distance` | `follow_keep_distance` |
| `retreat` | `retreat` |

---

<a id="legacy-dialogue-13-执行边界与维护"></a>
#### 13. 执行边界与维护

UE接收后核对支持版本、当前可控角色、已实现订单类型、获准能力、可解析目标、有效期/优先级；真正触发时再验目标存活、资源、冷却、距离和忙碌。具体接入顺序与失败场景统一见[联调指南](../guides/_12_legacy_integration_guide.md#接入顺序与通过条件)，本页不把建议组件表当UE实现清单。

LLM只形成受约束建议，服务与UE都需校验；其配置可来自本机.env或进程环境，密钥不传给UE或提交Git，具体数据流见[LLM指南](../guides/_03_llm_integration_guide.md)。不要由旧订单解析路径推断所有LLM只在commands/voice调用，也不要将NPC rl占位或旧队友走位实验当当前Boss部署。

字段删除或语义变化须升级并协调双方schema、接口测试、示例和UE反序列化；可选扩展也需明确兼容行为。改规则时同步当前需求与验收；新增公开端口、训练或模型格式不是仅改本文能完成的功能。

---

<a id="legacy-dialogue-附录-a-陪伴对话-sse-流式端点v01-附加扩展2026-09-15"></a>
#### 附录 A. 陪伴对话 SSE 流式端点（v0.1 附加扩展，2026-09-15）

`POST /v1/companion/chat/stream` 是 `/v1/companion/chat` 的**流式变体**：请求体
复用 `CompanionDialogueRequest`（原样），响应改为 `text/event-stream`（SSE）。
现有 JSON schema 零改动、非流式端点行为零改动，故为 v0.1 附加式扩展、不升版本。

<a id="legacy-dialogue-帧语法"></a>
##### 帧语法

每帧两行 + 空行，`data` 为单行 JSON：

```
event: delta
data: {"protocol_version":"0.1","text":"好的"}

event: meta
data: {"protocol_version":"0.1","companion_id":"companion.alice","session_id":"...","reply_text":"...完整文本...","emotion_id":"emotion.bright","gesture_id":"gesture.cheerful_idle","facial_expression_id":"face.bright_smile","interruptible":true,"source":"llm","relationship_stage":""}

event: error
data: {"detail":"LLM stream interrupted; this turn is incomplete."}
```

- **delta**（0..N 帧）：`reply_text` 的文本增量，只用于即时展示。
- **meta**（终结帧，1 帧）：完整的 `CompanionDialogueResponse`，**权威数据**——
  最终文案、表现 ID、来源（mock/llm/fallback）以此帧为准，UE 应在收到后
  用它覆盖已展示的增量拼接结果。
- **error**（可选终结帧）：流中途故障（见下），该轮对话不完整。

<a id="legacy-dialogue-语义规则"></a>
##### 语义规则

- **meta 为权威，delta 尽力而为**：delta 可能缺失（LLM 未按 JSON 顺序输出
  `reply_text` 时服务端不猜测），不能只靠 delta 渲染最终状态。
- **回退语义**：LLM 在发出任何 delta 之前失败 → 服务端静默回退 mock 回复，
  `source:"fallback"`，与非流式路径一致；mock 后端输出单 delta（全文）+ meta。
- **中断行为（与非流式的唯一差异）**：已发出 delta 后流中断 → `error` 帧，
  该轮**不写**会话/长期记忆；非流式路径回退回复会照常写入。已展示一半的
  文本由 UE 自行处理（建议淡出或保留）。
- HTTP 状态恒为 200；流开始前的错误照常返回 404（未登记角色）/ 422（参数
  校验）。
- 建议代理层禁用缓冲（服务端已带 `Cache-Control: no-cache`、`X-Accel-Buffering: no`）。

<a id="legacy-dialogue-附加扩展2026-09-17sdd-us6可选-world_context-请求字段"></a>
##### 附加扩展（2026-09-17，SDD US6）：可选 `world_context` 请求字段

`CompanionDialogueRequest` 新增**可选**字段 `world_context`（`WorldContext` 结构，
与 `/v1/agent/step`、`/v1/world/events` 使用的世界快照同构）。缺省不传时行为与
v0.1 完全一致，属附加式扩展、不升版本。

- 用途：艾莉回答「现在战况如何 / 周围有什么 / 你状态怎样」这类问题时，先经
  只读查证工具**查证本轮快照**再作答，不用过期状态（US6 验收场景 3）。
- 建议传法：UE 发起对话时附带当前快照（与心跳同一份即可）；不传时上述三类
  问题她将明确表示「说不清」，而不是凭印象编。

<a id="legacy-dialogue-附加扩展2026-09-17语音陪伴对话-post-v1companionchatvoice"></a>
##### 附加扩展（2026-09-17）：语音陪伴对话 `POST /v1/companion/chat/voice`

`/v1/companion/chat` 的**语音入口**：multipart 音频 → ASR 转写 → 既有对话
链路（记忆 / 关系 / 信号埋点全部生效）。与 `POST /v1/voice/command` 同款
模式，尾部接陪伴对话而非战术指令解析。

- **请求**（multipart/form-data）：`audio`（WAV 16kHz / 单声道 / 16bit，同
  `/v1/speech/transcribe` 约定）+ `companion_id`（默认 `companion.alice`）+
  `game_state`（`exploration|conversation`，默认前者）+ 可选 `session_id` +
  可选 `world_context_json`（`WorldContext` 的 JSON 字符串，同上）。
- **响应**：`CompanionDialogueResponse` 全部字段 + `transcribed_text`（ASR
  转写文本，供 UE 展示「你说了什么」与调试转写质量）。
- **错误语义**：转写后端故障 → 502；未识别出语音内容 → 422（对话里「听错
  还硬答」比「明确听不清」更糟，**不**回退 mock 文本）；参数非法 → 422；
  未登记角色 → 404。
- `AESIR_ASR_BACKEND` 与转写端点共用：`mock` 返回 `AESIR_ASR_MOCK_TEXT`，
  `faster_whisper` 走真实本机 Whisper。


<a id="legacy-dialogue-附录-b-对话json状态和数据副作用"></a>
#### 附录 B. 对话JSON、状态和数据副作用

`POST /v1/companion/chat`请求由`CompanionDialogueRequest`定义：`text`必填（1～500字符）；`companion_id`默认`companion.alice`；`game_state`为`exploration|conversation`；可选`session_id`（1～64字符）、`world_context`。请求和响应均配置`extra="forbid"`。对话主路径先查已注册角色，未知角色404，非法场景422；配置错误可503。

响应为`protocol_version="0.1"`、角色/会话标识、`reply_text`、表现ID、`interruptible`、`source=mock|llm|fallback`，以及`relationship_stage`、`relationship_stage_display`、`relationship_delta`、`persona_revision`、`memory_layers`。关系阶段是本轮生成前状态，实际关系变化另由delta表达。

- `session_id`只控制短期会话窗口。缺省时不保存该窗口，仍会检索/写入长期事实和印象、读取关系并尝试记录完整对话信号，不是“完全无状态”。
- 正常完成轮次默认尝试将完整`player_text/reply_text`追加到`data/runtime/dialogue_signals/<game>/<companion>.jsonl`；显著声明还可能逐字入长期档案。写失败按实际降级，不保证每轮均落盘成功。
- LLM模式会把人格、当前文本、检索记忆/印象、近期会话及适用查证结果送到配置后端；回环HTTP监听不等于全部本地。发送范围、存储和清理边界见[LLM与数据流](../guides/_03_llm_integration_guide.md)。
- 记忆reset只处理指定角色会话和长期记忆，保留人格、关系和信号日志；可能部分完成，见[v0.3调试接口](_01_npc_contract.md#legacy-agent-5-调试与记忆重置)。

订单类型中的技能字段沿用v0.1定义；整个NPC领域不要求日常/社交建议均有技能。需要技能的动作必须引用本角色获准能力，单条指令可引用几项尚未冻结；不能把类型字段直接推广成每条领域指令必有一个技能。

<a id="legacy-dialogue-当前实现与规范的边界"></a>
#### 当前实现与规范的边界

- `ParseCommandRequest`校验版本0.1、UUID请求ID和文本长度，但顶层没有`extra=forbid`；嵌套`ParseCommandContext`及订单判别联合配置了forbid。不能笼统声称所有端点都拒绝多余字段。
- 目录白名单是解析/接收的约束，UE仍须核验当前角色、技能、目标、冷却、距离、忙碌、有效期及游玩/遭遇身份。未知身份、L0能力门控在不同旧入口的检查并不完整，见[v0.3差距表](_01_npc_contract.md#legacy-agent-7-当前实现差距)。
- 音频格式是传输约定。当前上传路径把文件读为内存字节交给ASR，没有统一的大小/时长/WAV头门禁；不能把文档写了格式等同每项已由服务器强校验。
- v0.3玩家指令、世界事件、有限幂等与观测字段集中到[NPC契约](_01_npc_contract.md#legacy-agent)；UE接入步骤集中到[联调指南](../guides/_12_legacy_integration_guide.md)，不在兼容契约重复维护任务状态。
# 条目来源与受控遗忘增量

<a id="memory-management"></a>

本节是 scoped JSON 0.4 的新增管理操作；既有请求/响应字段与 legacy 路由不变。条目模型继续使用已有 `entry_id/source/game_time/real_time/tags/superseded_by`，不向旧客户端注入新的必填字段。请求和完整响应以 `data/golden/memory/` 三个样例及 `ScopedForgetRequest/ScopedForgetResponse/ScopedMemoryEntriesResponse` 为准。

| 路径 | 权限与输入 | 输出/保证 |
| --- | --- | --- |
| `GET /v1/scoped/console/memory/entries` | `console:read`；与现有 console 相同的 save/npc/instance/run/binding/epoch 查询参数 | 当前归属全部 archive/summaries/short_term 条目及完整 ID/来源标签，包括已纠错条目；不跨档、不返回被遗忘条目 |
| `POST /v1/scoped/console/memory/forget` | `memory:reset`；ScopedResetRequest 相同身份/绑定字段，加 `entry_ids`（1～50 个不同 UUID） | 原子移除所选条目，返回 `forgotten_entry_ids`、新 `memory_epoch` 与 `cleared_sessions`；其余长期条目、人格与关系保留 |

任意目标不存在于本 NPC 的当前三个层级时返回 `404 MEMORY_ENTRY_UNKNOWN`，整个批次无删除；格式、空集合/重复 ID 为 422。越权为 403，过期 instance/binding/epoch 继续适用既有 409。未知条目不透露它是否存在于其他玩家或存档。

2026-11-19 起，服务端记录条目、印象主题与对话轮次的内部关联：遗忘移除所选条目、可追溯的派生条目、关联印象及依赖这些内容的历史轮次，保留可确认无关的条目、主题和轮次。一个主题混有多条来源时整主题保守移除；旧数据无关联、关联截断或历史上下文无法归属时也保守清理。`cleared_sessions` 表示有轮次被移除的会话数（可以只清其中一部分），不是删除轮次数。完整 reset 仍清全部记忆及会话。

内部关联随 JSON/SQL 文档保存，备份和 JSON→SQL 迁移保留；不新增 UE 响应字段。会话仍只在进程内，SQL 重启恢复范围没有扩大。新 epoch 继续拦截所有旧生成、写入和未确认离线记忆，不因保留无关轮次而接受旧 binding。不会清关系、执行账本、请求确认或日志，也不是日志/备份中的个人数据擦除 API。无关联的语义近似副本仍需客户端列出全部需要移除的条目；本操作不做语义主题批量删除。见[本轮证据](../records/_10_p1_memory_quality_verification.md)。

删除与 epoch 更新共用 JSON 单文件原子写，或 SQL 同一业务事务。新 epoch 阻止生成中的旧回复在完成时提交；SQL 离线已确认 duplicate 返回原 ack 但不重写记忆，未确认旧 epoch 新事实首次确认的 memory 分项为 `skipped_reset`，关系独立确认。服务已发出的 SSE delta、客户端已见内容无法撤回；客户端接到遗忘成功也应丢弃旧 epoch 的缓存与回调。

原 request_id 与相同载荷可重放遗忘结果，但只有结果 epoch 仍为当前且 run/binding 有效时允许；下一次 reset/forget 后旧结果为 409。JSON 重放仅受进程内缓存保证，SQL 持久确认沿用既有恢复规则，不扩张 JSON 的跨重启承诺。

### `trace.*` 来源标签

新增条目的 `tags` 使用服务器写入的 `trace.key=value` 约定：game/player/save/companion/run/memory_epoch、logical request_id；世界事件再记录 event_id、原 occurred_at、来源 origin。离线事实另保留 origin_run_id/origin_memory_epoch。摘要与按内容去重保留原条目 ID/来源引用，不因生成摘要或重复提及丢掉全部关联。

`trace.origin=verbatim_player` 是玩家逐字陈述，`model_extraction` 是经词面接地校验的模型抽取，UE 来源是上报方主张。`trace.confirmation=player_text/lexically_grounded/source_report` 说明记录种类，**都不是 UE 动作成功证明**。`real_time` 是服务端记录/最近提及时间，`game_time` 和 `trace.occurred_at` 保留上报时间，不用于倒退关系计分日。NPC 生成文本在相同 logical request_id/scope 的 dialogue_signals 中独立保存，不自动升级为世界事实；执行收到/拒绝不产生治疗、命中成功记忆，执行确认继续读独立 directive/receipt 账本。

每个 trace key 保留最早一条及最近 31 条不同引用，避免重复陈述无限放大档案；SQL 确认账本/信号的完整历史依赖既有保留策略，标签不是完整审计日志。旧条目缺少 trace 标签时按未知来源引用处理，不根据内容补造旧请求 ID。
