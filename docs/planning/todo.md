# 未决事项与跨仓依赖

2026-10-19 根据 `a2dd426` 与现存证据整理。排期和完成状态由 [GitHub Issues](https://github.com/YYchainsAw/aesir-ai-service/issues) 维护；本页只记录尚未解决的业务口径、实现差距和跨仓依赖，不重复完成勾选。需求基线见 [SDD v1.1](aesir-agent-sdd-v1.1.md)，已完成事项与历史测试见[验证记录](../logs/verification-records.md)。本次未查询远端 Issue 状态，以下引用沿用历史编号。

| 编号 | 尚需解决的内容 | 处理边界 |
| --- | --- | --- |
| EXT-01 | 真实玩家输入→解析→UE 接收→实际启动/命中/完成→回执闭环；Alice/Bruno 技能声明与 UE 可执行能力逐项对照 | 服务端返回 200、接收回执或临时心跳通道均不代表技能已完成；按实际能力拒绝越界，不擅自冻结技能数量 |
| EXT-02 / DEP5 | Boss PPO模型仍在研发；当前仅有模型快照的身份门禁、Windows开发验证包和逐局评估基础设施。正式选模/候选确认及重新构建复验见[DEP5-05 / #96](https://github.com/YYchainsAw/aesir-ai-service/issues/96)；UE预期身份/进程管理、KI-01/KI-06、同条件BT/PPO实战也待完成 | schema4/sim005/reward003 seed1仅为本轮验证基线，不代表研发定稿；独立持出结果与900局选模分开；见[第五步计划](step-05-boss-local-release-plan.md)、[发行指南](../guides/boss-local-release.md)及实际证据 |
| EXT-03 / OUT-05 | 对话RL导演层是否立项（#54 / T39） | 仍待批准；现有信号可分析，不能据此启用在线学习或自演化人格 |
| EXT-07 | 已采纳外部ASR转接；供应商适配、音频门禁、文本兜底和真人时延待验，VAD/流式转写/TTS/播放打断后置（#56 / T41） | 见BR-DEP-05、V1～V4及AT-EVO-03/04；mock/本机Whisper不代替正式外部ASR，供应商/声音/保留与播出门槛启用前记录 |
| EXT-08 | 读档、快进、跨存档及服务重启恢复（#57 / T42）；持久同步与离线队列继续后续实现 | 已批准的同档长期状态保留、v0.4显式绑定/相对时效/重置epoch已有服务端子集，见[第二步计划](step-02-identity-scope-plan.md)与[v0.4契约](../protocols/npc-scope-contract-v0.4-draft.md)；不以此替代#57全部时间/衰减范围或BR-DEP-03/04/06的数据库同步目标 |
| FIX-02 | UE 敌人血条 MaxHealth=0 防护 | 跨仓检查与 PIE 验证；不以 Python 文档判已修复 |
| FIX-03 | UE Alice 跟随目标的 PlayerController / Pawn 位置语义 | 在当前 UE 工程复测，按实际目标修正 |
| FIX-06 | UE 输入 Context 重叠是否导致误触发 | 在当前关卡与输入资产复测 |
| FIX-07 后续 / T35 [#44](https://github.com/YYchainsAw/aesir-ai-service/issues/44) | PIE 试玩后的熔断/节流参数调优及生效源核对 | 既有任务完成了默认值登记，未完成真实试玩调参；NPC LLM 默认5次/60秒与Boss连续3错切BT分别处理 |
| EXT-09 / FIX-09 后续 / T32 [#41](https://github.com/YYchainsAw/aesir-ai-service/issues/41) | 指标代理与正式 SC 结论分离，补正式采样和证据 | 脚本 PASS 只可能证明当前代理；记忆正确率、语气区别、角色隔离、故障不中断均需对应验收材料。SC-001~013 验收埋点补齐（#53 / T38）已于 2026-10-20 完成，6 项 N/A 升为脚本可判定，实测 SC-005 FAIL 暴露自主行为多样性不足 |
| FIX-04 采集 / T33 [#42](https://github.com/YYchainsAw/aesir-ai-service/issues/42) | SC-011 的 UE 输入至 NPC 首次实际表现采样，区分规则/LLM、文本/语音 | 既有 p95≤300ms/≥30次为已记录口径，运行验收仍待；生产对话没有传 `latency_ms`，不能等待新聊天就宣告采样完整，见[联调对齐表](../protocols/integration-alignment-v0.3.md) |
| API-GAP（legacy静态发现） | 旧回执game_id及extra/version/UUID校验差异仍属legacy兼容；v0.4已统一严格作用域与已发布指令关联 | 新旧入口分开核对；UE接入和生产身份另验，不把旧schema差距概括为scoped仍无保护 |
| MODEL-GAP（第三步后余项） | scoped已有最小反馈账本、序号去重/终态保护及原请求关联查询；完整started/hit/completed、持久历史决策与REQ-06仍待闭合 | 见[闭环增量契约](../protocols/npc-loop-contract-v0.4.md)与[服务端验证](../logs/verification-records.md#loop-20261022)；accepted仅收到、executed仅UE自报，不能由JSONL或状态查询推断UE真实闭环 |
| DATA-GAP（本轮静态发现） | 默认对话日志保留完整输入/回复，与NFR只摘要目标不一致；记忆清理范围和部分失败状态需明确 | 先确认保留/清除策略及目标范围；不宣称关闭或摘要化已生效，关系档案不因清记忆自动清除 |
| DEP-01 | SQL/Bearer服务端及迁移/恢复工具已有受控证据；正式数据切换、OS隔离与HTTPS发布仍待 | DEP-REQ-01/02/06；AT-DEP-01/02/03/11/12；固定开发身份不替代正式账号或生产多worker |
| DEP-02 | SQL持久身份、确认版本、事实/回执归档与epoch分项已实现；UE缓存/本地队列和完整恢复/冲突流程待接入 | DEP-REQ-03/07；AT-DEP-04/05/06/08；不得重放过期命令或复活已清记忆 |
| DB-GAP / DEP4后续 | 高增长账本拆表/索引、长期清理、大小写标识策略及正式数据切换仍需按容量与发布要求设计 | 需求追踪、ER/PDM、8表44列字典和保留DDL已补齐；dev到期列漂移已备份后修复，三库审计通过，运行时/离线共享结构门禁，见[数据库设计](../design/database/README.md)及[本轮证据](../logs/verification-records.md#schema-gate-20261022)；不把受控验证等同正式容量/UE通过 |
| DEP-03 | 外部ASR、模型可信发布/下载回滚、生产守护及容量采样 | DEP-REQ-04/05/06/08；AT-DEP-07/09/10；只记录真实运行证据 |
| EVO-01 | 请求生命周期、旧代取消、逻辑命令幂等与UE真实反馈；关联认证作用域和事务结果 | D1/D2/D4、G3/G4、C1/C2；先对齐协议/样例；AT-EVO-01/02/07/09，原EXT-01/MODEL-GAP不因此关闭 |
| EVO-02 | 上下文来源、事件合并/过期、分阶段追踪及按键→外部ASR→文本最小链路 | D3、G1/G2、C4、V1；AT-EVO-03/05/10和AT-DEP-07；沿用纯心跳规则及无主动推送 |
| EVO-03 | 记忆来源/纠错权限、持久确认和离线补拉；扩展现有epoch屏障到同步恢复 | M2/M3/M4、C3；依赖EVO-01；AT-EVO-06来源部分、08/09及AT-DEP-04～06/12 |
| EVO-04 | 后置VAD/TTS有序播放/打断与索引按需读对照 | V2/V3/V4、M1；已采纳待实施，供应商/参数和播出门槛先记录；AT-EVO-04/06/10，不阻塞当前游戏执行闭环 |

原 CODE-01～05/07 已有实现与历史回归；CODE-06 的“双重场景推导”经核查不存在，CODE-08 的关系冷却漂移已修复，策略启动时固化属明确边界（T20 / [#33](https://github.com/YYchainsAw/aesir-ai-service/issues/33)、T34 / [#43](https://github.com/YYchainsAw/aesir-ai-service/issues/43)）。不把它们继续列为当前缺陷。EXT-04/05/06/09 与 FIX-01/04/05/08/09 的已完成服务工作归入验证记录；其涉及 UE 实际表现或正式 SC 的余项按上表验收。

2026-10-20新增（均已由GitHub建账，此处仅留指针）：FIX-12/style_guard元语言词表口径（[#55](https://github.com/YYchainsAw/aesir-ai-service/issues/55)/T40，待26轮真实对话回归）；Boss第三种子重训（[#58](https://github.com/YYchainsAw/aesir-ai-service/issues/58)/T43，旁路按评测选优）；M2旧账核对（#17/#18/#29/#30，逐项核对关闭或补证据）。S5外部人格包守卫（#39/T30）已于2026-10-20完成，见CHANGELOG与验证记录。

历史SDD的单机、本地文件及无账号/DB/公网限定保留为旧基线。2026-10-21用户已采纳Boss本地、远程NPC、多个独立单机玩家的身份/存档隔离、缓存同步、外部ASR和模型分发；完整DEP规则见[部署指南](../guides/deployment.md)，15项位置与[六步开发方案](local-boss-cloud-companion-roadmap.md)保持对应。v0.4作用域子集已合入main；第四步分支已有SQL/Bearer与事实/回执同步服务端证据，正式数据切换、UE缓存/队列及完整恢复仍待后续；多人联机战斗、通用账号产品、任意跨设备存档合并、人格自演化和Boss并入NPC仍不在范围。日常状态只在GitHub Issues维护。

同日采纳的五方面20项机制及用例/FR/DEP映射见[交互演进计划](npc-interaction-evolution.md)。EVO批次是依赖划分；复用v0.4已有可信开发身份、绑定/epoch和有界内存幂等，取消/TTS/跨重启事务等完整目标和AT-EVO未由本轮运行验收。图源与PNG已通过MCP和Desktop同步，整组Word回填/排版结果由UE建模记录维护。

2026-10-22第三步服务端增量在 `feature/npc-execution-loop` 通过适用核心回归，工作包见[DEP3里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/7)。同会话FIFO、取消屏障、并发/预算、最小反馈账本及只读查询已有受控证据；EXT-01、MODEL-GAP、EVO-01/02的跨端余项和第四步生产目标仍保留，UE连接继续后置。具体待验见[交接指南](../guides/scoped-development.md#loop-usage)。

2026-10-22第四步服务端在 `feature/npc-persistence-access` 已通过1404 passed、1 skipped适用核心回归，含5项真实MySQL测试；另完成独立SQL HTTP进程重启、源JSON不改导入与私有备份空库恢复。见[DEP4里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/8)、[契约](../protocols/npc-persistence-contract-v0.4.md)和[验证记录](../logs/verification-records.md#persist-20261022)。EVO-01/03与DEP完整生产/UE目标不因服务端受控通过而关闭；恢复较旧快照的RPO/后续reset收敛、本地队列与发布门禁继续保留。
