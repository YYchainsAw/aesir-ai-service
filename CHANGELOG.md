# Changelog

记录里程碑；排期与完成状态见 [GitHub Issues](https://github.com/YYchainsAw/aesir-ai-service/issues)，当前差距见[未决清单](docs/planning/todo.md)，真实抓样与测试范围集中在[历史验证记录](docs/logs/verification-records.md)。本页不再复制逐文件流水账。

最新全量锚点为 **2026-10-21，846 passed + 2 skipped**（T45/#62 关系节奏调参后）。此前末次全量记录为 2026-10-20 的 843 passed + 2 skipped、2026-10-15 的 769 passed + 2 skipped——它们是当时结果，不能冒充本次文档整合在 `a2dd426` 上新跑的完整测试。早期分支/合并与计数差异按原记录保留。

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