# Changelog

记录里程碑；排期与完成状态见 [GitHub Issues](https://github.com/YYchainsAw/aesir-ai-service/issues)，当前差距见[未决清单](docs/planning/todo.md)，真实抓样与测试范围集中在[历史验证记录](docs/logs/verification-records.md)。本页不再复制逐文件流水账。

历史完整环境锚点为 **2026-10-21，848 passed + 2 skipped**（T49/#66 SC-009 历史/本次拆分后）。此前末次全量记录为 2026-10-20 的 843 passed + 2 skipped、2026-10-15 的 769 passed + 2 skipped——它们是当时结果，不能冒充本次文档整合在 `a2dd426` 上新跑的完整测试。早期分支/合并与计数差异按原记录保留。

## 2026-10-23 — DEP5 Boss本地发行与冻结持出评估

新增固定候选及材料SHA门禁、有限观察/mask输出检查、CPU回环推理、Windows原生onedir EXE构建/校验/自测和冻结PPO逐局评估。原候选未重训/替换；实际Windows EXE17项检查通过，Windows Boss测试139 passed、1 skipped，服务器核心1553 passed、1 skipped（含5项真实MySQL）。持出1800条记录中PPO/模拟器Rule胜率0.815556/0.567778，原始结果与选模分开。发行ZIP、SHA、清单及许可已保管；UE身份/进程管理、KI-01/KI-06、实战及真实断网回退仍待验。见[第五步计划](docs/planning/step-05-boss-local-release-plan.md)、[发行指南](docs/guides/boss-local-release.md)与[本轮证据](docs/logs/verification-records.md#boss-release-20261023)。

## 2026-10-22 — DEP4结构门禁与开发库整改

已合入的第四步后续补齐SQL启动/首次接入结构检查，运行时与离线审计共享metadata规则；只有空库能初始化DDL，已有错误库只读拒绝，损坏凭据到期数据拒绝认证。dev的expires_at可空偏差在私有备份后受检修复，8表业务数据不变，三个项目库结构审计通过。适用核心1463 passed、1 skipped（含5项真实MySQL），独立实际进程验证错误结构拒绝启动及恢复后健康/认证门禁；PDM源与预览同步。范围及后续UE/生产边界见[计划](docs/planning/step-04-persistence-access-plan.md)与[证据](docs/logs/verification-records.md#schema-gate-20261022)。

## 2026-10-22 — DEP4数据库设计与SQL审计补齐

新增需求映射、两页ER/单页PDM、8表44列字典、保留初始DDL及带阻断检查的v1漂移修复SQL；2份draw.io源由本地MCP保存，Desktop导出3张含XML的PNG并上传。新增结构/工件审计及15项回归，脚本组50 passed；真实隔离MySQL验证初始DDL和修复正反场景。test/restore结构一致，dev到期列可空偏差如实保留待修，未改既有库或业务schema。本次为实现后补齐设计，详见[数据库索引](docs/design/database/README.md)与[证据](docs/logs/verification-records.md#database-design-20261022)。

## 2026-10-22 — DEP4 SQL持久化、访问控制与恢复（服务端分支实现）

`feature/npc-persistence-access`新增独立MySQL事务与确认版本、正式Bearer/存档授权和管理分权、持久请求/事件去重、SQL执行反馈、只读历史确认及离线真实事实/历史回执归档；记忆重置按分项确认，恢复默认停用所有旧凭据。提供默认dry-run的归属JSON迁移、私有备份与空目标恢复工具。新增132项测试、10个完整golden；适用核心1404 passed、1 skipped，含5项真实MySQL专项，另完成8.4.13真实HTTP进程重启与备份恢复。未升级旧5.7、未改开发.env、未切正式数据、未修改/连接UE或调用真实模型；生产/跨端余项保留。见[计划](docs/planning/step-04-persistence-access-plan.md)、[开发指南](docs/guides/persistent-development.md)与[实测记录](docs/logs/verification-records.md#persist-20261022)。

## 2026-10-22 — DEP3 队友请求与执行反馈（服务端分支实现）

`feature/npc-execution-loop`新增同会话文本FIFO、请求取消/状态查询、有限生成并发与上游剩余预算、元数据追踪，以及有界执行反馈账本和只读查询。提交后失败保留UNKNOWN；回执不确定追加封锁对应NPC/run，避免污染损坏尾部。修复跟随目标和战术能力关联，未支持条件明确无动作。新增243项scoped测试、10个完整golden，适用核心回归1272 passed、1 skipped；无新增依赖。未修改/连接UE、未调用真实LLM/ASR或安装RL依赖，第三步整体与生产目标仍待验。见[计划](docs/planning/step-03-execution-loop-plan.md)、[契约](docs/protocols/npc-loop-contract-v0.4.md)与[实测记录](docs/logs/verification-records.md#loop-20261022)。

## 2026-10-21 — DEP2 NPC归属、生命周期与有效期（分支实现）

按已批准的第二步计划，在 `feature/npc-scope-v04` 新增v0.4同版JSON边界、可信开发身份、玩家/存档/NPC状态分区、显式run/encounter CAS、记忆epoch重置屏障、单调预算、有限窗口single-flight与回执关联；旧协议须显式开启开发兼容模式。新增190项scoped测试和21个完整golden，适用核心回归1029 passed+1 skipped。未安装可选ML/RL、未调用真实LLM、未修改或连接UE。命令、证据与未验范围见[验证记录](docs/logs/verification-records.md#scope-20261021)，配置与接入见[开发指南](docs/guides/scoped-development.md)。

## 2026-10-21 — T49 SC-009 历史/本次拆分（#66）

SC-009 此前把全部历史 rejected/expired/cancelled 回执都算成「越界下发」FAIL，但 2026-10-19 联调日的 4 条拒绝是 UE 拒绝未制作能力的真实反馈，不是测试缺陷。本轮：collect_receipts 按 received_at 日期拆分今日/历史非执行回执；SC-009 verdict 今日零越界仅历史有记录 → PASS（note 注明历史性质），今日有越界 → FAIL。实测 SC-009 从 FAIL(4) 变为 PASS(0 今日 / 4 历史)。测试 847→848。

## 2026-10-21 — T48 对话信号→关系事件映射守卫（#65）

实测「直接调关系规则层用 warm_sentiment 返回 unknown_event」的根因：对话层有一层映射 `_DIALOGUE_RELATIONSHIP_EVENTS`（warm/deep/cold/hurtful → dialogue_warm_exchange 等），但映射表无守卫——如果有人给 LLM schema 加新信号却忘了更新映射，信号会被静默吞掉（返回 no_signal，delta=0）。审查结论：当前映射完整（4/4 事件在 policy 中存在，none 故意不映射）。新增守卫测试 `test_signal_to_event_mapping_is_complete`，防止未来新增信号时漏映射。测试 846→847。

## 2026-10-21 — T47 契约版本速查表（#64，纯文档）

实测踩坑汇总：UE 侧若用同一结构体复用各端点，必踩 422。在 integration-alignment-v0.3.md 新增「端点×版本×必填字段速查表」：agent/step 与 world/events 是 v0.3、tactical/command 仍是 v0.2、executions 每条回执 v0.2；列出各端点必填字段与常见 422 踩坑（scene 无 night、combat_context 缺 mode/encounter_id/boss/ability_states）。长期目标 tactical/command 升 v0.3 统一信封，涉及 UE 侧结构体改造，不在本轮范围。

## 2026-10-21 — T46 lore 知识库补世界观（#63）

实测问「我们现在所在的地方叫什么名字」→ TOOL_NO_RESULT，艾莉只能打太极。按 lore 纪律「只收设计文档已确立的事实，不编造」，从 combat-tactical-protocol-v0.2 和 persona.yaml 提取 4 条可追溯条目：Boss 暴怒状态（state.enraged）、Boss 被击败（boss_defeated 事件）、艾莉性格与动机（persona.background）、战斗事件类型清单（6 种 event_type）。地名/阵营/艾莉出身背景等设计文档未确立的内容刻意留空——保持「无据可查时明确不确定」的 SC-008 验收路径。lore revision 002→003。测试 846 持平。

## 2026-10-21 — T45 关系值上升节奏调参（#62）

实测 12 轮正向对话只 scored 1 次（+1），关系值 26→27 几乎不动。两处瓶颈叠加：对话冷却 300s 过严（连聊 10 分钟被拦 5 次）+ LLM prompt 明确「when in doubt choose none」宁漏勿滥。本轮：(1) 对话冷却 300s→120s（事实事件冷却 60s 不变）；(2) LLM prompt 放宽 warm 判定——「今天很开心」「谢谢你」「有你在真好」等友好表达应稳定给 warm，deep/cold/hurtful 保持严格（delta 更大）。日上限 15/天不变。预期：30 分钟有效对话内关系值从 neutral 推到 friendly（50 分）。测试 846 持平（仅 config + prompt 文案调整 + 测试断言同步）。

## 2026-10-21 — T44 自主行为目录扩充（#61）

实测 SC-005 FAIL 根因不是 YAML 注册行为数（已有 11 类），而是 `generate_candidates` 仅在特殊条件下产出候选：follow/express 已注册但从不产出，探索域默认退化为 observe 兜底。本轮补两条默认自主生成规则——(1) companion 未在 following 状态时产出 follow 候选（follow 优先级 20→30，确保探索域默认自主胜出）；(2) 雨/雪/雾/风暴天气产出 express 候选。冒烟实测行为类型数从 1 类（仅 observe）升至 6 类（follow/express/inspect/observe/rest/wait），真实游戏时间积累后还会触发 self_talk/pickup/alert_player。测试 843→846。

## 2026-10-20 — T38 SC 验收埋点补齐（#53）

SC-004/005/006/007/008/013 六项 N/A 升为脚本可判定，纯观测层埋点、业务语义零改动：`agent_steps` 落盘（agent/step 主汇合点，一份 JSONL 同时喂自主行为类型分布、相邻重复率与 reason_codes 覆盖率）、`event_signals` 落盘（同事件非首条必须 duplicate=True）、关系层 `apply_relationship_event_ex` 三元组透传四种 delta=0 拦截原因、查证结果 `lore_lookup` 与接地丢弃数落盘。SC-002 保持 N/A（receipts 加战况字段属 UE 契约变更，不硬凑）。实测 SC-013/006/007 PASS，SC-005 FAIL 真实暴露自主行为仅 inspect 一类、多样性不足。测试 812→843。

## 2026-10-20 — T30 S5 外部人格包守卫（#39 / N3 闭环）

归属校验扩展为外部不可信资产守卫：sha256 内容哈希（manifest 唯一解析删 checksum 字段破循环）、配额+注入 lint（词表外置 policy yaml）、人工审核记录落盘、加载时强校验失败 503 不静默跳过。自有人格包 origin 缺省 self 豁免，alice/bruno/demo-vn 零改动。测试 770→812。

## 2026-10-19 — 文档整合与模型重构

统一 SDD v1.1 需求入口、开发和联调说明、未决事项及 UML 阅读入口，合并10篇旧日志的有效证据。旧需求稿、逐日流水和重复进度不再并行维护。区分需求目标、已实现行为、历史样本与正式验收；修正旧队友RL被当成当前Boss结果、指标代理被当成SC通过等表述。

本轮仅文档与模型工作；没有运行服务、测试、训练或UE验收，也没有修改业务实现。当前视图与审查边界见 [UML 入口](docs/design/uml/README.md)。

## 2026-10-19 — FIX-10 端口对齐与临时UE心跳

`46feea3` 将NPC默认端口由8000改8011；Boss服务继续8012。历史记录health_commands 12 passed及health200。`1ac8751` 整理E盘临时UE工程心跳记录（agent/step200×28），只支持当时心跳连通；玩家UI、技能执行和D盘正式工程验收另行核对，见[原环境与结论边界](docs/logs/verification-records.md#ue-20261019)。

## 2026-10-15 — 指标、联调复现和表达修正

- T32/#41：指标采集增加SC命名的判定输出；T33/#42：SC-011采样口径定稿。脚本代理PASS不能替代记忆正确性、角色隔离或UE实际响应验收。
- T21/#34、T22/#35：health增加service_commit；整理既有26轮样本（25LLM+1fallback），不混称UE实测。
- T35/#44、T36/#45：登记默认参数、补style-policy-002样例；未宣称PIE调优完成。
- T37 / `b30f4cc`：Bruno展示文案、缺省角色路由、degraded观测及可选埋点修正。全量历史762→769 passed，2 skipped沿用原锚点；生产调用未传latency_ms，不把字段存在写成正式SC-011采集完成。

样例、命令范围与代理限制见[验证记录](docs/logs/verification-records.md#metrics-boundary)。

## 2026-10-12～13 — 指标漏采、状态边界与Bruno

T19/#32修复game目录漏采、旧布局兼容、物理重复行和损坏行统计；T20/#33、T34/#43将关系冷却改为独立时间戳，核查场景推导分叉不成立。历史全量755→756 passed、2 skipped。T31/#40扩充Bruno人格与能力声明，增加角色路由测试；10-13原日志另记756 passed（起点754），未强行合并计数，UE技能制作仍另验。

## 2026-10-08 — 人格包、游戏档案和能力门控

S2/#36（`b7ac0e5`）迁移8文件人格包；S3/#37（`5f9727e`）提供game档案和demo-vn；S4/#38完成L0/L3链路及事件声明门控。历史730→736→745 passed、2 skipped。S5第三方资产守卫仍为后续边界。

T18/#31集中v0.3契约、跨仓版本/端口和能力对照；记录服务HTTP样例与错误拒绝，不代表UE完成治疗/护盾等技能。课程图源与资料索引曾在当日整理；当前图源与格式统一从 [UML入口](docs/design/uml/README.md) 查找。

## 2026-09-28～30 — 协议加固与游戏隔离

批量回执、调试台UI、关系阶段中文名落地；CODE-01～05/07修复白名单校验、不可信输入封装、指令有效期、映射兜底及显式异常。S0/S1完成游戏命名空间、人格路由与lore/信号/回执隔离，`15cfc55`提交S1。FIX-01建立读取Settings的可配置启动入口，当时默认8000。

不同检查快照原记678+2、711+2、709、712、714+2、726+2；详细范围见[历史检查表](docs/logs/verification-records.md#regression)。09-30的一进程一游戏、能力子集校验、S5后置和Bruno迁移裁决继续保留在[决策记录](docs/logs/verification-records.md#decisions)。

## 2026-09-14～24 — NPC人格与行为代理

| 日期 | 里程碑 | 原记录测试锚点 |
| --- | --- | --- |
| 09-24 | 多角色隔离、表达一致性校验、共享LLM熔断；诚实规则与收尾反复读修正 | 633、643、659、669 passed；其中643/659/669记2 skipped |
| 09-22 | 情绪惯性、关系阶段边界、能力事实接地、印象噪声；对话信号驱动关系 | 611→618→628 passed，2 skipped |
| 09-21 | 统一战斗/非战斗决策回归、解释链、首轮幻视修复、四层记忆接线 | 575→583→605 passed，2 skipped |
| 09-17 | 只读查证、近期/衰减记忆、对话信号、语音陪伴接口及幻觉/复读修正 | 462→473→485→491 passed，2 skipped；真实ASR质量未验 |
| 09-16 | 合并Boss分支、死代码清理、主题/显著记忆、事实与世界事件幂等 | 354、367、375、388、408 passed，2 skipped；不同分支计数不据此倒填 |
| 09-15 | 自主行为目录、仲裁/禁打断/节流与SSE | 355、362 passed，3 skipped |
| 09-14 | 四层记忆相关基础、终端调试、人格语料、关系数值/阶段/防刷 | 286、311 passed，3 skipped |

## 2026-09-10 — 初期LLM与旧队友RL实验

战术LLM意图解析、人格few-shot/多样回退、短期session记忆相继落地，历史236→242→250 passed、3 skipped。旧队友实验记3种子×100万步、2/3达标，优化眩晕窗口爆裂；这是17维/7队友动作的旧模拟实验，不能引用为当前schema4/26维/9动作Boss候选的上线结论，见[RL历史](docs/logs/verification-records.md#rl-history)。

## 2026-09-02～09 — 服务基础与战术闭环脚手架

FastAPI、health、陪伴对话、五类战术解析、Mock/Whisper接口、上下文决策、执行回执、战斗事件幂等、YAML策略和golden/mock客户端逐步建立。历史锚点：09-02 23、09-03 42、09-07 197、09-08 208、09-09 224 passed；09-07～09-09原记3个冒烟跳过。Mock客户端/ASR桩与模拟器检查不自动升级为UE或真人录音验收。