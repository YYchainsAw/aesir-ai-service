# NPC持久化与恢复增量契约v0.4

> 2026-10-22，`persistence-contract-v1`。随[第四步计划](../planning/step-04-persistence-access-plan.md)实现。它补充[v0.4作用域契约](npc-scope-contract-v0.4-draft.md)与[第三步闭环增量](npc-loop-contract-v0.4.md)，不改变原chat/agent/事件信封或五种回执结果。严格字段以 `app/schemas/recovery.py`、`app/schemas/sync.py` 及golden为准；运行支持以验证记录为准。

## 1. 存储与认证模式

默认 `scope_storage_backend=json`，旧开发使用方式保留。显式SQL模式通过站点根外0600连接文件或SecretStr配置连接MySQL/PyMySQL，schema必须先由迁移账号初始化并通过版本/列型校验；业务请求不自动建表。SQLite只在 `scope_sqlite_test_mode=true` 时可作为配置后端用于隔离测试，没有MySQL故障回退。

`scope_identity_backend=bearer` 使用 `Authorization: Bearer <credential>`，数据库验证哈希、玩家活跃状态、过期/撤销、游戏、权限和存档授权；客户端不能自报身份。凭据由受限运维CLI签发/撤销，没有公网注册或发token接口。明文仅写指定私有新文件，不入库或日志，供应商key不下发。开发principal的固定身份不等于生产认证。

| 权限 | 可用入口 |
| --- | --- |
| `npc:use` | 归属内context/run/encounter、chat/agent/事件/回执、取消和状态、权威恢复及真实事实/历史回执归档 |
| `console:read` | scoped console调试查询；也可读取文档/OpenAPI |
| `memory:reset` | 指定NPC的记忆重置；不自动授予console读取或业务权限 |
| `docs:read` | 文档/OpenAPI；不自动授予业务或其他管理权限 |

Bearer模式始终封锁legacy，不接受开发兼容开关旁路；文档需要管理读取。`/health`仍为必要存活信息。普通npc:use可读取自有权威记忆/关系快照供UE恢复缓存；console权限约束调试入口，不能笼统解释为玩家无法读自己的缓存。长请求在上游/提交边界重新检查撤销与存档授权；已经进入提交后的撤销不回滚已有事实。

## 2. SQL原子性与逻辑身份

物理表、逻辑实体与字段说明见[数据库设计](../design/database/README.md)；本契约只维护接口和提交语义，不将通用documents中的每种记录视为独立物理表。

SQL文档用namespace和完整逻辑键的唯一哈希保存原key、scope、payload及CAS版本；NPC确认版本按完整game/player/save/npc递增。请求/事件journal保存原逻辑key、指纹、owner instance、状态、确认版本及结果。哈希不是玩家认证；原scope/key仍核对。

请求claim为独立短事务。LLM期间无长事务/行锁；最终事务一起提交记忆、关系、epoch、事件/指令/回执与请求结果。处理中的重试等待原owner，载荷或binding/epoch改动冲突；未开始准入失败可放开占位，已开始但提交不明保留UNKNOWN。逻辑身份不自动TTL删除，也不因换HTTP ID恢复未知的原事实执行资格。数据库事务回滚时会话历史不追加；提交后诊断失败不撤回数据库事实。

service_instance与run绑定仍是进程生命周期，重启需重新发现/显式bind，旧业务请求不能直接回放。旧journal owner的complete结果仅可读历史确认；遗留running保守unknown，不自动重新抢占。当前仍单worker，不以数据库存在宣称已支持多worker的队列、绑定和取消一致性。

已接入的业务准入、控制和同步入口按game/player累计请求额度；不覆盖全部HTTP传输，控制/同步重试可能计次，业务缓存回放不再重新准入。每次上游真正尝试前独立预留日调用额度，缓存不扣上游额度，取消或业务rollback不退还预留；这不是货币费用硬预算。规则心跳不调用LLM。认证、额度及SQL故障都不能退回匿名或共享JSON状态。

## 3. 权威状态与历史确认

| 入口 | 查询/响应边界 |
| --- | --- |
| GET `/v1/scoped/recovery/state` | `save_id/companion_id`；返回完整自有scope、当前service_instance、state_version、save_generation、memory_epoch、MemorySnapshot和关系状态 |
| GET `/v1/scoped/recovery/operations/{request_id}` | 另带原run_id和operation；返回原请求状态、原实例、confirmed_version及原因，不返回旧响应或可执行payload |
| GET `/v1/scoped/recovery/directives/{directive_id}` | 另带原run_id；返回原请求/实例/epoch和最后自报反馈，不返回技能payload或刷新有效期 |
| GET `/v1/scoped/sync/state` | 返回自有scope、save_generation、epoch、state_version及权威关系，用于版本冲突后拉取；不返回动作或原对话 |

这些入口核对当前可信存档授权，不要求旧service_instance/binding仍有效。不存在记录返回明确404。恢复请求状态可能是complete/failed/unknown/cancelled；complete仅服务请求提交完成，executed仍只代表UE自报，不推断命中/动画完成。

save_generation按game/player/save独立持久登记；memory_epoch只表示NPC清记忆世代。当前不提供任意分支读档/跨设备合并，不能靠自行生成generation覆盖原档。原run/encounter须有该存档世代的持久控制历史。

## 4. 离线真实事实确认

`POST /v1/scoped/sync/facts`接收同版request_id、save_id、companion_id、save_generation、expected_state_version和facts（运行默认最多50条，可配置1～100，schema硬上限100）。每条仅含 `origin_run_id/origin_encounter_id/origin_memory_epoch/source=ue/event`；event复用原ScopedWorldEvent（稳定UUID、sequence、event_type、occurred_at、details），单条序列化不超过16KiB。战斗事实必须有原encounter。只接受该游戏已声明事件；不接受聊天、音频、旧心跳、命令、技能建议或整个本地关系分数。

同一完整NPC/原run/原encounter/event_id是共同持久身份，实时/world或/combat与离线通道共享确认。指纹核原事件内容，不因重连/新epoch/新批次变新事实；同ID改内容冲突。批次request_id另绑定完整载荷；冲突拉状态后使用新批次ID，原fact ID保留。批内先完整校验，再同事务应用全部新事实、状态版本及分项确认。已有事实只返回原确认，不再次应用；全已知重试可读取原确认而不要求旧expected版本仍为当前。

| 分项 | 规则 |
| --- | --- |
| 关系 | 仅现有关系规则计分，使用服务受理UTC维护冷却/日上限；UE occurred_at作为来源记录，不能倒退服务器计分日 |
| 记忆 | 原epoch为当前且有合法活动上下文时，只写现有共同经历模板；非经历事件not_applicable；无活动上下文明确not_applied_missing_context |
| 旧epoch | 记忆skipped_reset，不恢复已清内容；关系独立按原事实确认，已确认的关系不重复计分 |
| 响应 | event_id、duplicate、relationship_status/delta、memory_status和原confirmed_version；外层返回当前epoch/generation/state_version，不返回动作 |

客户端收到分项确认后才移出已确认事实；遇STATE_VERSION_CONFLICT先拉权威状态，再重试仍合法且未确认事实。服务端不提供本地队列实现，UE仍需配置容量/保留期限/退避/失败状态，满额不静默宣称成功，退出不等待云端。新鲜世界状态走原实时入口，不借离线通道补执行历史动作。

## 5. 历史回执归档

`POST /v1/scoped/recovery/receipts`专用于已发布原指令的历史事实归档。信封携带原run、原memory_epoch、save_generation及预期state_version，receipts复用严格原回执模型。允许原绑定失效或热关联窗口已过，但必须匹配数据库中的原指令/请求、能力、角色、遭遇与原epoch；未知指令不凭空认领。

与实时回执共用身份去重、序号冲突和终态演算，并与批次确认/版本同事务提交。归档不产生动作、不改变记忆/关系或撤销已确认事实；旧epoch回执可归档原事实，但不能恢复旧记忆。仅归档响应可按稳定批次ID跨重启取回原确认，普通业务仍不得回放旧实例动作。`stored=0`不必表示`duplicate=true`：终态后新的accepted身份可被忽略但已登记去重；同终态不同sequence仍为新身份。重试归档回放原安全确认，可能保留原service_instance，仅供历史关联。完整started/hit/completed仍未扩展现有枚举。

## 6. 错误与迁移

| HTTP / 原因 | 含义与处理 |
| --- | --- |
| 401 IDENTITY_REQUIRED | 缺失、错误、到期、撤销或玩家停用；重新获得合法凭据，无匿名回退 |
| 403 SCOPE_FORBIDDEN / PERMISSION_DENIED | 当前存档或入口权限不足，不使用其他玩家UUID绕过 |
| 409 STATE_VERSION_CONFLICT | 拉权威状态，新批次保持原事实身份；不上传整个分数覆盖 |
| 409 SAVE_GENERATION_STALE / ORIGIN_RUN_UNKNOWN / ORIGIN_ENCOUNTER_UNKNOWN | 存档世代或原来源控制历史不符，不冒认当前局 |
| 409 REQUEST_ID_CONFLICT / EVENT_ID_CONFLICT | 已有逻辑身份被改内容，保留原事实核对 |
| 429 REQUEST_QUOTA_EXCEEDED / UPSTREAM_QUOTA_EXCEEDED | 对应额度不足；不因换session/NPC逃逸同玩家额度 |
| 503 STATE_UNAVAILABLE / REQUEST_OUTCOME_UNKNOWN | 状态不可用或提交确认不明；后者保留原关联核对，禁止自动换ID重做 |

旧instance/binding/epoch、回执sequence/终态等继续沿用原契约。只导入完整scoped JSON的已知归属；legacy文件不会自动归入玩家。恢复默认撤销所有恢复凭据，防较旧快照复活后续已撤销token；需核对授权后重新签发。业务数据只回到备份恢复点，不自动保留之后的reset/撤销，正式切换需另行收敛。导入/备份/恢复和切换操作见[运维与开发指南](../guides/persistent-development.md)，不以本页字段目标代替实测或UE接入。
