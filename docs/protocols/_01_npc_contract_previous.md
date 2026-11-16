# NPC 服务协议上一版

归档版本：scoped v0.4。用于查阅异步提交增量之前的作用域、闭环与持久化约定；当前接入使用 [_01_npc_contract.md](_01_npc_contract.md)。后续协议升级时替换本文件，只保留最近一个上一版归档。


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

> 2026-10-22，`loop-contract-v1`，随[第三步计划](../planning/_04_execution_loop_plan.md)开发。基线 `main@e96151b`；新增支持以分支回归记录为准。本页是[v0.4作用域契约](_01_npc_contract_previous.md#scope)的增量，不改变既有chat/agent请求或既有回执枚举；字段以`app/schemas/loop.py`及对应golden为准。

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

> 2026-10-22，`persistence-contract-v1`。随[第四步计划](../planning/_05_persistence_plan.md)实现。它补充[v0.4作用域契约](_01_npc_contract_previous.md#scope)与[第三步闭环增量](_01_npc_contract_previous.md#loop)，不改变原chat/agent/事件信封或五种回执结果。严格字段以 `app/schemas/recovery.py`、`app/schemas/sync.py` 及golden为准；运行支持以验证记录为准。

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
