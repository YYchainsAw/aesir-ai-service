# AIRI学习点与两仓交接基线

2026-10-23，`airi-alignment-v1`。原始输入为2026-10-21的`airi-learning-checklist.md`，研究固定在[AIRI `6876b0d`](https://github.com/moeru-ai/airi/tree/6876b0dcd94006f1092a2e0bd869ebdcddc7d50c)。20项已于同日纳入[交互演进计划](npc-interaction-evolution.md)，不是本次才提出的新方向。本文维护实现证据、两仓版本与下一步交接，不复制字段规范或另建完成看板；20项执行入口为父任务[#103](https://github.com/YYchainsAw/aesir-ai-service/issues/103)，日常状态以其关联Issue为准。

## 本次核对的固定版本

| 对象 | 基线与意义 |
| --- | --- |
| Python已合并主线 | [`main@b641b2f`](https://github.com/YYchainsAw/aesir-ai-service/tree/b641b2f)：DEP2身份/有效期、DEP3服务端请求/反馈闭环、DEP4 SQL/Bearer/恢复与结构门禁均已在主线。服务端受控证据见[验证记录](../logs/verification-records.md)，本次文档核对不重记历史测试通过 |
| 本次文本修复候选 | `a0869b8106196956416d7626c46ae1cbd3b3606b`：本轮分支的角色文本入口修复及回归，尚未合入main；后续联调须使用包含该修复的实际提交，协议审计点仍保留`b641b2f`，不混写已合并状态 |
| UE已合并主线 | [`main@ea43abc`](https://github.com/YYchainsAw/AesirWarden/tree/ea43abc)：部署/演进目标已登记，`CompanionChatSubsystem.cpp`仍发送`protocol_version=0.3`至`/v1/agent/step`并按0.3验响应；不能直接连接Bearer严格入口 |
| Boss未合并交付线 | [PR #95，`f1dff27`](https://github.com/YYchainsAw/aesir-ai-service/pull/95)：本地运行/发行/评估基础设施分支，不能记成main能力或正式模型完成。最终模型仍由[#96](https://github.com/YYchainsAw/aesir-ai-service/issues/96)研发；旧队友第三种子任务[#58](https://github.com/YYchainsAw/aesir-ai-service/issues/58)不能替代当前Boss研究验收 |

这组提交是本次比较点。下一次联调在记录中写入实际Python提交、UE提交及游戏构建；若合并本次修复或PR #95，分别升级对应基线。不要按本地旧分支或一份“未来目标”文档推断远端main尚未实现SQL/取消，也不要反过来按服务端pytest宣称UE已经执行。

## 20项实际应用情况

所有项均已规划采纳；“服务端子集”表示已见对应源码、契约和原有受控验证，保留右列尚未闭合的目标。完整AT-EVO与UE检查仍按原定义取证。

| 项 | 当前应用与证据入口 | 尚缺什么及交付线 |
| --- | --- | --- |
| D1 每轮身份与终态 | **服务端子集**：完整NPC/run/session内的逻辑`request_id`、内部HTTP/上游尝试UUID、队列/运行/终态及查询已实现；见[闭环契约](../protocols/npc-loop-contract-v0.4.md)、`app/scoped/requests.py`、`app/scoped/trace.py` | UE轮次/UI与回调关联、生成/播放/实际动作分别终结仍待；不存在可直接追加到strict请求的通用`turn_id`字段 |
| D2 排队、替代与取消 | **服务端子集**：chat/agent文本同会话FIFO、显式取消、旧binding/epoch/encounter写入屏障；见[第三步交接](../guides/scoped-development.md#loop-usage) | UE需主动取消并本地作废旧回调；同步供应商调用不能保证被强杀；读档/重试后释放旧响应的跨端场景待验 |
| D3 来源与有效期上下文 | **已有基础+部分增量**：人格、结构化世界快照、历史和分层记忆分开构造；v0.4核对快照年龄/绑定；见[LLM数据流](../guides/llm-integration.md)及作用域契约 | 尚无统一的来源注册/退出清理实现；事件有界合并与来源寿命的全部场景不能由现有拼接证明。连同G2由[#100](https://github.com/YYchainsAw/aesir-ai-service/issues/100)取证 |
| D4 工具、重试与提交 | **服务端子集**：白名单查证、轮次限制、剩余预算约束、取消/超时后禁后续尝试及最终提交屏障；SQL最终事务提交；见[闭环](../protocols/npc-loop-contract-v0.4.md)及[持久化契约](../protocols/npc-persistence-contract-v0.4.md) | scoped SSE尚未实现；legacy流的delta/meta/error不等于具备scoped事务/取消保证。首输出后断流、半回复显示与关系不重复的跨端验收仍待 |
| V1 采集与转写生命周期 | **规划采纳，旧基础存在**：上传音频、ASRBackend及mock/faster-whisper为基础；[演进计划](npc-interaction-evolution.md)已选按键→外部ASR→最终文本 | 正式外部ASR适配、scoped音频入口、UE采集/取消/错误及真人时延由[#98](https://github.com/YYchainsAw/aesir-ai-service/issues/98)交付；[#56](https://github.com/YYchainsAw/aesir-ai-service/issues/56)的VAD/TTS/打断后置扩展不代替首期适配 |
| V2 本地VAD与回声 | **后置采纳**：职责在UE本地，参数需真实采样 | 未实现完整VAD/句首预留/静音结束/回声闭环；不阻塞文本闭环 |
| V3 并发合成、顺序播放 | **后置采纳**：首版只合成确认的全文，未来句级确认另定 | 未实现TTS片段协议/合成队列/UE播放；原清单的`segment_id/sequence`是设计示例，不是现行音频字段 |
| V4 按回复打断 | **后置采纳**：生成、合成、播放分别取消与实际已播边界已写目标 | D2的请求取消没有实现音频打断；迟到音频不复活、设备切换和字幕兜底均待完整语音实现后验 |
| G1 本地反应与高层建议 | **架构已沿用**：UE/GAS掌握世界与执行，NPC云端只给建议，纯心跳规则运行；Boss独立本地HTTP | 断网时UE已实现行为及Boss/BT不中断需实机证明；PR #95及#96分别验基础设施与模型 |
| G2 事件合并/筛选/过期 | **服务端子集**：现有候选仲裁/节流、快照时效、事件稳定身份去重；见`app/services/agency/`及[作用域契约](../protocols/npc-scope-contract-v0.4-draft.md) | UE事件队列容量/合并/淘汰及高频受击不触发无谓LLM尚未整体验；余项由[#100](https://github.com/YYchainsAw/aesir-ai-service/issues/100)跟踪，不因此新增主动推送 |
| G3 UE本地条件判断 | **部分基础**：受支持即时动作/目标/条件校验与TTL已有服务端处理；未满足/未知条件返回无动作/澄清 | **条件登记/等待/本地触发尚无契约和实现**；仅当前快照已满足的已知眩晕条件可给即时建议。不得宣称“Boss破防后雷击”登记后断网仍可执行；设计余项见[#100](https://github.com/YYchainsAw/aesir-ai-service/issues/100) |
| G4 命令身份与回执 | **服务端子集**：稳定directive、同逻辑请求回放、原指令关联、sequence冲突和终态防倒退、SQL持久账本；见[闭环契约](../protocols/npc-loop-contract-v0.4.md) | UE需按directive去重并报告实际Action/GAS结果；现枚举没有started/hit/completed，`accepted`仅收到、`executed`仅UE自报执行 |
| M1 索引按需读对照 | **后置采纳**：保留现有分层/预算检索 | 索引/按需读与准确率/token/时延对照由[#101](https://github.com/YYchainsAw/aesir-ai-service/issues/101)跟踪；不预设向量库为前置 |
| M2 事实/主张/输出分离 | **服务端子集**：记忆已有来源类型；SQL真实事实确认保存原event、run/encounter/epoch、`source=ue`与分项确认；回执关联原指令；见[持久化契约](../protocols/npc-persistence-contract-v0.4.md) | 全部聊天事实的消息级证据/确认状态尚不完整；NPC自述不能当UE执行事实，最终语义与实际世界需跨端验证 |
| M3 更新/纠错/受控遗忘 | **已有基础+规划增量**：事实接地/去重、规则关系、授权reset已有实现 | 稳定条目级纠错/更新/遗忘及模型候选修改权限尚未完整设计实施；全量reset不等于条目forget |
| M4 独立重置屏障 | **服务端子集**：持久`memory_epoch`与提交重核；未确认的旧epoch新事实首次同步时记忆`skipped_reset`、关系独立确认；已确认重复事实返回原ack且不复写记忆/关系。见[重置规则](../protocols/npc-scope-contract-v0.4-draft.md#4-记忆重置与晚到写入)和持久化契约 | UE缓存/队列清理、重启后旧积压不复活仍待；任意分支读档/跨设备合并不在当前实现。旧备份恢复后的后续reset收敛属于发布门禁 |
| C1 认证主体作用域 | **服务端子集**：开发固定principal与SQL Bearer/玩家活跃/存档授权/权限分离均已在main；完整game/player/save/npc分区 | UE凭据接入与切玩家/档隔离待做；CLI签发能力不等于正式账号门户或HTTPS发布已上线 |
| C2 持久幂等/事务确认 | **SQL服务端子集**：claim、指纹冲突、最终状态/结果原子提交、确认版本及跨重启只读恢复；实际MySQL/重启证据在[验证记录](../logs/verification-records.md#persist-20261022) | JSON/内存开发后端无跨重启事务；旧实例普通业务仍拒绝，不能“重放旧响应→再执行”；UE实际动作去重及正式切换待验 |
| C3 离线队列/同步 | **服务端子集**：`sync/state`、`sync/facts`、恢复快照/历史确认/回执归档、版本冲突与epoch分项均已实现 | **UE持久队列未实现，通用游标事件feed未提供**；当前是权威快照+版本+按ID确认，不得发明`cursor`参数。队列容量/保留/退避/分项移除与重连收敛待做 |
| C4 接口与阶段追踪 | **服务端子集**：LLM/ASR抽象、熔断、统一原因、请求/尝试关联与queue/processing/total记录，规则路径不调用LLM | 外部ASR及TTS阶段、真实LLM首字、UE接收/启动/完成及SC-011端到端采样未闭合；无测量时返回未知，不由单点HTTP耗时推断 |

因此方向已应用到规划及DEP2～4代码。下一步应把已有服务端子集接入UE、补真实验收，再按缺口扩展；不能把20项全标“尚未开发”，也不能把它们全标“完成”。AIRI的edit-wins删除语义不直接复用，继续使用M4的独立记忆屏障。

## 交接使用的唯一协议入口

v0.4是JSON信封版本，URL前缀为`/v1/scoped`，不是`/v0.4`。完整字段、错误、状态和限制引用[作用域契约](../protocols/npc-scope-contract-v0.4-draft.md)、[闭环增量](../protocols/npc-loop-contract-v0.4.md)、[持久化增量](../protocols/npc-persistence-contract-v0.4.md)；以`app/schemas/scoped.py`、`loop.py`、`recovery.py`、`sync.py`和对应golden复核，不在本文另写平行字段表。

| 目的 | 现行路由 |
| --- | --- |
| 存活、发现归属/实例/当前版本 | `GET /health`；`GET /v1/scoped/context` |
| 显式游玩和遭遇控制 | `POST /v1/scoped/runs/bind`、`POST /v1/scoped/runs/end`、`POST /v1/scoped/encounters/control` |
| 文本建议、纯对话 | `POST /v1/scoped/agent/step`、`POST /v1/scoped/companion/chat` |
| 当前世界事件、当前回执 | `POST /v1/scoped/world/events`（`/v1/scoped/combat/events`为同模型别名）、`POST /v1/scoped/tactical/executions` |
| 取消、请求与指令状态 | `POST /v1/scoped/requests/cancel`、`GET /v1/scoped/requests/{target_request_id}`、`GET /v1/scoped/directives/{directive_id}` |
| SQL权威恢复及原确认 | `GET /v1/scoped/recovery/state`、`GET /v1/scoped/recovery/operations/{request_id}`、`GET /v1/scoped/recovery/directives/{directive_id}` |
| SQL同步及历史回执 | `GET /v1/scoped/sync/state`、`POST /v1/scoped/sync/facts`、`POST /v1/scoped/recovery/receipts` |
| 授权管理调试/清理 | `GET /v1/scoped/console/state`、`GET /v1/scoped/console/memory`、`POST /v1/scoped/console/memory/reset` |

当前没有scoped SSE/语音/TTS入口；严格模式不能降到legacy SSE/语音。UE旧`/v1/agent/step`与0.3响应解码只用于显式legacy开发兼容；Bearer模式始终封锁legacy，修改URL而不迁移身份信封和响应验证不能完成接入。

开发联调可使用服务端预登记的`AESIR_SCOPE_IDENTITY_BACKEND=development`、玩家UUID及授权save列表，单worker、环回监听/SSH转发；客户端不能用header/body覆盖principal。SQL验收采用`AESIR_SCOPE_STORAGE_BACKEND=sql`、`AESIR_SCOPE_IDENTITY_BACKEND=bearer`，由受限CLI签发/撤销凭据，UE携带`Authorization: Bearer <credential>`；普通`npc:use`不自动拥有console/reset权限。凭据不写issue或测试证据，生产切换、HTTPS/OS隔离仍单独验。操作只跟随[持久化指南](../guides/persistent-development.md)。

context先获取`service_instance_id`、控制revision与`memory_epoch`，再CAS显式bind取得`run_binding_id`；战斗显式begin/end遭遇。服务重启需重新context/bind，旧绑定不能恢复待执行建议。`memory_epoch`是NPC清记忆世代，`save_generation`是SQL存档世代，两者不互换；当前客户端不得自行生成世代覆盖旧档。重试保留原request_id、语义载荷、快照与首次发送单调时间，只依契约增加age；有效期从首次发送起算，缓存不续期。

## 最小联调步骤与证据

1. 固定两仓实际提交与配置，先验`data/golden/scoped/`、`loop/`、`recovery/`和`sync/`。golden中的UUID是样例关联，实际联调先从context/bind取得真实实例/绑定/epoch，再保持整链一致；不把孤立静态JSON当成当前可用请求。
2. 先用规则/mock跑Alice的聊天、跟随、等待及已有战术能力：`agent/step → directive → UE当前世界/GAS复核 → 实际动作 → tactical/executions → directives查询`。Bruno唤醒词/路由隔离可先用协议桩或已有资产验证，不将新增Bruno资产设为首轮前置。拒绝/无动作也是合法结果，证据需说明触发条件；不先实现新条件等待或扩大技能目录。
3. 相同request_id重试、重复directive、重复/乱序回执、目标死亡、时效耗尽各跑一次；记录实际GAS启动次数，确认一次逻辑请求不重复启动，终态不倒退。`receipt.order_id`关联原`directive_id`，同一原request_id及scope/遭遇沿用。
4. 生成中显式取消/替代、换run、结束遭遇、reset后再释放旧响应；UE本地先作废旧回调，服务端相应屏障拒绝迟到提交。取消未生效需如实记录，不能宣称已撤销此前完成的世界事实。
5. SQL/Bearer下跑两玩家同NPC/同名档隔离、权限/撤销、提交后回包前断开、进程重启。重新发现/绑定后只读历史确认，未知提交保留原关联核对；恢复响应不驱动Action/GAS。
6. UE队列实现后再跑离线真实事实/历史回执归档、确认丢失与重传、版本冲突拉取。未确认旧epoch新事实首次确认时记忆为`skipped_reset`，关系独立确认；已确认重复事实只回原ack（可能仍是`recorded/processed`），不重新写入或恢复记忆/关系。服务器持久确认后才按分项移除。断网不补传旧聊天/音频/心跳/建议，不重放旧动作。

| 必须保存的最小证据 | 判定用途 |
| --- | --- |
| 两仓提交、UE构建/场景、协议、存储/身份模式、非敏感配置与实际供应商 | 防止用旧分支、mock或开发身份代表目标发行配置 |
| 单个正例的request_id、directive_id、scope、run/encounter、instance/binding、epoch、快照及首次发送时钟 | 串起输入、建议、当前世界复核与原回执；不保存Bearer或供应商key |
| UE录屏/日志中的实际Action/GAS启动/拒绝与次数，服务端原关联及回执序号/终态 | HTTP 200/202、accepted和executed自报不能独立证明命中/完整完成 |
| 取消/旧代/重复/过期/断网/重启负例及重现步骤 | 分开服务端保护、UE回调保护、UE执行去重和本地兜底的责任 |
| SQL事实与回执分项确认、确认版本、重传/冲突/旧epoch结果，队列前后计数 | 分开首次确认旧epoch事实的`skipped_reset`与重复事实的原ack回放；证明真正持久后移除、重复不双计、已清记忆不复活 |
| 客户端输入至首次实际表现的起止、规则/LLM与文本/语音分组、样本和原始数据 | SC-011及AT-EVO/DEP端到端结论；阶段未采样明确未知 |

服务端既有回归范围沿用[验证记录](../logs/verification-records.md#schema-gate-20261022)；新修复的命令、环境与结果由本次修复记录单列。本次没有运行UE、模型训练、真人ASR或正式发布；上述步骤是待执行验收清单。

## 工作包与关闭条件

当前先交接文本，再恢复，再语音/发布；Boss基础设施与模型继续独立并行。下表记录工作包与关闭边界，后续只更新Issue进度，不复制完成复选框。

| 工作包 | Issue与完成边界 |
| --- | --- |
| 文本最小闭环与v0.4迁移 | Python [#97](https://github.com/YYchainsAw/aesir-ai-service/issues/97)修复角色文本入口，遗留LLM SSE缺陷由[#102](https://github.com/YYchainsAw/aesir-ai-service/issues/102)单独跟踪；UE [#24](https://github.com/YYchainsAw/AesirWarden/issues/24)负责公共v0.4/认证/绑定/epoch接入，[#19](https://github.com/YYchainsAw/AesirWarden/issues/19)负责聊天/探索，[#20](https://github.com/YYchainsAw/AesirWarden/issues/20)负责当前世界复核、动作去重与真实回执。满足上文步骤1～4后才关闭相应子项；公共协议接入不能代替实际动作验收 |
| SQL恢复与UE队列 | UE [#21](https://github.com/YYchainsAw/AesirWarden/issues/21)负责缓存/持久队列/分项确认/版本冲突/重置与恢复；原Python [#57](https://github.com/YYchainsAw/aesir-ai-service/issues/57)保留时间/读档业务范围。DEP4服务端已完成子集复用，不能按“数据库未来开发”重排 |
| 跨端总体验收 | UE [#22](https://github.com/YYchainsAw/AesirWarden/issues/22)汇总公共接入及聊天/执行/恢复的实际证据；Python父任务[#103](https://github.com/YYchainsAw/aesir-ai-service/issues/103)维护20项余项与工作包关联。单个服务端测试、#24关闭或文档对齐均不能直接关闭总体验收 |
| 外部ASR首期 | [#98](https://github.com/YYchainsAw/aesir-ai-service/issues/98)负责按键→外部ASR→scoped最终文本；[#56](https://github.com/YYchainsAw/aesir-ai-service/issues/56)负责V2～V4后置扩展。真实语音总预算另测，不能直接套SC-011的300ms文本表现口径 |
| 第六步正式发布 | [#99](https://github.com/YYchainsAw/aesir-ai-service/issues/99)：独立发布/HTTPS/OS隔离、固定提交、备份/RPO/reset与撤销收敛、容量/真实时延及回滚验收；不被DEP4受控MySQL通过替代 |
| 后续演进缺口 | [#100](https://github.com/YYchainsAw/aesir-ai-service/issues/100)负责D3/G2/G3/C4上下文/事件/条件/阶段追踪余项；[#101](https://github.com/YYchainsAw/aesir-ai-service/issues/101)负责M1/M2/M3/C3来源/条目纠错/检索与真正cursor的设计余项。现有恢复API继续用于当前UE接入，文本首版不捆绑全部20项 |
| Boss | [PR #95](https://github.com/YYchainsAw/aesir-ai-service/pull/95)基础设施审查与[#96](https://github.com/YYchainsAw/aesir-ai-service/issues/96)正式模型研发分开；[#58](https://github.com/YYchainsAw/aesir-ai-service/issues/58)核对旧队友实验适用性后处理 |

原AT-EVO-01～10、AT-DEP及UE的NPC-EVO/DEP-UE定义继续有效。服务端子项关闭、UE接入关闭和正式发布通过分别取证，不因对齐文档或Issue建立而互相替代。
