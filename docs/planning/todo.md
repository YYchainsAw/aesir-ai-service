# 未决事项与跨仓依赖

2026-10-19 根据 `a2dd426` 与现存证据整理。排期和完成状态由 [GitHub Issues](https://github.com/YYchainsAw/aesir-ai-service/issues) 维护；本页只记录尚未解决的业务口径、实现差距和跨仓依赖，不重复完成勾选。需求基线见 [SDD v1.1](aesir-agent-sdd-v1.1.md)，已完成事项与历史测试见[验证记录](../logs/verification-records.md)。本次未查询远端 Issue 状态，以下引用沿用历史编号。

| 编号 | 尚需解决的内容 | 处理边界 |
| --- | --- | --- |
| EXT-01 | 真实玩家输入→解析→UE 接收→实际启动/命中/完成→回执闭环；Alice/Bruno 技能声明与 UE 可执行能力逐项对照 | 服务端返回 200、接收回执或临时心跳通道均不代表技能已完成；按实际能力拒绝越界，不擅自冻结技能数量 |
| EXT-02 | Boss 冻结候选部署身份校验、无重训独立 PPO 评估入口、逐局输出、UE 同条件 BT 对照与故障回退复测 | 当前候选为 schema4/sim005/reward003 seed1；900 局属于选模；旧队友“2/3达标”不能作 Boss 上线依据，见 [RL 说明](../../rl/README.md) |
| EXT-03 / OUT-05 | 对话 RL 导演层是否立项 | 仍待批准；现有信号可分析，不能据此启用在线学习或自演化人格 |
| EXT-07 | 流式 ASR / VAD 是否纳入范围，空音频、过短或噪声的反馈话术，以及真人 WAV 的质量和时延评估 | 无真人录音样本时只记录 Mock/桩测试；不宣称真实 ASR 质量达标 |
| EXT-08 | 读档、快进、跨存档、服务重启的时间与状态恢复口径 | 需明确哪些状态重置/保留、异常后的保证，不能仅由当前文件布局推断业务规则 |
| FIX-02 | UE 敌人血条 MaxHealth=0 防护 | 跨仓检查与 PIE 验证；不以 Python 文档判已修复 |
| FIX-03 | UE Alice 跟随目标的 PlayerController / Pawn 位置语义 | 在当前 UE 工程复测，按实际目标修正 |
| FIX-06 | UE 输入 Context 重叠是否导致误触发 | 在当前关卡与输入资产复测 |
| FIX-07 后续 / T35 [#44](https://github.com/YYchainsAw/aesir-ai-service/issues/44) | PIE 试玩后的熔断/节流参数调优及生效源核对 | 既有任务完成了默认值登记，未完成真实试玩调参；NPC LLM 默认5次/60秒与Boss连续3错切BT分别处理 |
| S5 / T30 [#39](https://github.com/YYchainsAw/aesir-ai-service/issues/39) | 外部人格包 lint、配额、注入检测、checksum与人工审核 | 当前只接我方资产；第三方接入前补齐，不能把已有归属校验写成全部资产守卫完成 |
| EXT-09 / FIX-09 后续 / T32 [#41](https://github.com/YYchainsAw/aesir-ai-service/issues/41) | 指标代理与正式 SC 结论分离，补正式采样和证据 | 脚本 PASS 只可能证明当前代理；记忆正确率、语气区别、角色隔离、故障不中断均需对应验收材料 |
| FIX-04 采集 / T33 [#42](https://github.com/YYchainsAw/aesir-ai-service/issues/42) | SC-011 的 UE 输入至 NPC 首次实际表现采样，区分规则/LLM、文本/语音 | 既有 p95≤300ms/≥30次为已记录口径，运行验收仍待；生产对话没有传 `latency_ms`，不能等待新聊天就宣告采样完整，见[联调对齐表](../protocols/integration-alignment-v0.3.md) |
| API-GAP（本轮静态发现） | 回执game_id由请求自选、未绑定当前实例；extra、version、UUID约束在各请求模型间不统一 | 按实际模型列明差异，需明确拒绝/兼容规则后修正与复测；不把规范文字写成校验已经存在 |
| MODEL-GAP（本轮静态发现） | 回执仅追加，无完成状态机、乱序合并和跨版directive_id/order_id完整关联；REQ-06指定历史决策查询尚未闭合 | 收到/accepted不等于执行完成；需记录实际阶段、身份与查询边界，不能由JSONL文件存在推断闭环 |
| DATA-GAP（本轮静态发现） | 默认对话日志保留完整输入/回复，与NFR只摘要目标不一致；记忆清理范围和部分失败状态需明确 | 先确认保留/清除策略及目标范围；不宣称关闭或摘要化已生效，关系档案不因清记忆自动清除 |

原 CODE-01～05/07 已有实现与历史回归；CODE-06 的“双重场景推导”经核查不存在，CODE-08 的关系冷却漂移已修复，策略启动时固化属明确边界（T20 / [#33](https://github.com/YYchainsAw/aesir-ai-service/issues/33)、T34 / [#43](https://github.com/YYchainsAw/aesir-ai-service/issues/43)）。不把它们继续列为当前缺陷。EXT-04/05/06/09 与 FIX-01/04/05/08/09 的已完成服务工作归入验证记录；其涉及 UE 实际表现或正式 SC 的余项按上表验收。

其他范围界限沿用 SDD：单机、本地文件、UE 唯一世界权威、工具只读、不做多用户/账号同步、人格自演化、DB/MQ/公网部署，不将 Boss RL 并入 NPC `app` 服务。新增业务口径先写 REQ/BR/AT；不把课程建模修正或文档整理当作额外功能批准。
