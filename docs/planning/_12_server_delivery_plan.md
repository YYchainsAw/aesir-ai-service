# 服务端交付计划

## 服务端工作顺序

按服务依赖、交付阻塞与验收范围安排优先级；任务状态以对应 Issue 为准。

- **P0：**当前服务端交接、真实后端可用与必交能力收口。
- **P1：**可靠性、恢复和已有能力的必要验收。
- **P2：**扩展研究、较大机制和非阻断体验。
- **暂停/阻塞：**需要的条件不成立，不占当前开发主线。

| 建议顺序/优先级 | Issue | 服务端交付 | 与当前状态的差异 |
| --- | --- | --- | --- |
| 1 / P0 | [#122 阻断缺陷清单与责任](https://github.com/YYchainsAw/aesir-ai-service/issues/122) | 将 13cb182 的修复、测试范围、当前 LLM/模型/环境阻塞及责任写清；补最新遗留缺陷 | 正文主要停在 11/05，应更新证据，不把服务端测试算成 UE 通过 |
| 2 / P0 | [#119 正常与拒绝样例](https://github.com/YYchainsAw/aesir-ai-service/issues/119) | 先验证可用 LLM，再采集 chat、follow/wait、已支持攻击意图的合法/拒绝输出；保留 source、目录、请求关联与时效 | 正常“输出 directive”即可证明服务端建议，实际移动/伤害由游戏端另验。不要制造 executed |
| 3 / P0 | [#98 scoped 语音与 ASR](https://github.com/YYchainsAw/aesir-ai-service/issues/98) | 在目标服务机器配置真实 faster-whisper，完成认证上传、音频门禁、去重、空白/失败与文本兜底响应验证，并与可用 LLM 串联 | 正文仍写没有 scoped 音频/外部适配；当前已有实现和本机证据。应收口部署与真实服务端验证，不重写接口；不强制商业 ASR |
| 贯穿上述 / P0 汇总 | [#116 服务基线交接](https://github.com/YYchainsAw/aesir-ai-service/issues/116) | 固定交接 SHA、非敏感配置、接口/身份/存储说明、样例、启动/重启/回退及服务端证据包 | 父任务汇总 #119/#121/#122/#123，不重复计算一轮开发；先确认维护者分工和交接目标 |
| 4 / P1 | [#121 JSON 与 SQL/Bearer 差异](https://github.com/YYchainsAw/aesir-ai-service/issues/121) | 整理实际差异表、权限与错误、数据路径、可用 recovery/sync API，复用现有指南与导览 | 多数材料已经存在，缺的是验收映射和当前基线整理，不必再写一套平行契约 |
| 5 / P1 | [#123 SQL/Bearer 真实恢复](https://github.com/YYchainsAw/aesir-ai-service/issues/123) | 在隔离库验证认证/授权、重启后历史查询与不重复副作用；保留当前版本证据 | 区分同实例轮询与跨实例历史恢复，按现行 recovery/绑定契约演示，不能假定旧绑定可在重启后原样使用。缺环境时标 blocked，不用 mock 替代 |
| 6 / P1，先做纠错/来源 | [#101 记忆来源与纠错](https://github.com/YYchainsAw/aesir-ai-service/issues/101) | 先补真实 LLM 纠错、来源和越权边界证据；索引/全文检索对照后置 | 已有实现不能全部重开发；不得扩大成向量数据库先行或通用 cursor 先行 |
| 7 / P1，限定服务端 | [#57 时间、读档、衰减](https://github.com/YYchainsAw/aesir-ai-service/issues/57) | 验证受理时间、冷却、衰减、save/generation、epoch 和旧事实确认语义 | UE 存档/队列属于客户端依赖；保留跨端验收待对接的状态，不因此让服务端工作一直模糊未完成 |
| 8 / P2；关键诊断可单独提早 | [#100 事件治理/条件/阶段](https://github.com/YYchainsAw/aesir-ai-service/issues/100) | 补需要的来源/阶段观测；未来条件目录与版本化协议单独设计 | 当前文本闭环之后再扩，不为了网页展示临时发明 started/hit/completed 或条件登记字段 |
| P1 部署准备；公网范围 P2 | [#99 HTTPS、数据切换、容量](https://github.com/YYchainsAw/aesir-ai-service/issues/99) | 受控服务实例、私有配置、真实依赖、备份恢复与基本发布证据先做；公网/容量按是否启用安排 | 如果网页仅本机演示，不需先完成公开域名和公众容量；真正远程多人使用则不能跳过认证/授权/HTTPS |
| P2 汇总维护 | [#103 20 项交接跟踪](https://github.com/YYchainsAw/aesir-ai-service/issues/103) | 更新已有服务能力与剩余依赖映射 | 属父跟踪，不应作为“20 项同时重做”的单个大任务；其中无 scoped 语音的旧描述需纠正 |
| P2，先核账 | [#112 情感桶种子](https://github.com/YYchainsAw/aesir-ai-service/issues/112) | 对照已关闭 [#113](https://github.com/YYchainsAw/aesir-ai-service/issues/113) 的证据，确认还有哪些未覆盖验收项 | #113 已关闭并有三阶段结果评论；不能仅凭 #122 的“重复”判断自动关闭 #112，也无需直接重跑整套付费样例 |
| P2，数据条件驱动 | [#54 对话 RL 导演层](https://github.com/YYchainsAw/aesir-ai-service/issues/54) | 继续离线信号质量分析，需要时整理门槛 | 正文仍写待批准，但评论已经批准立项评估并交付切片 A；不等于批准上线在线学习 |
| P2，明确后置 | [#56 VAD/TTS/流式/打断](https://github.com/YYchainsAw/aesir-ai-service/issues/56) | 保留设计与后续范围 | 不应成为当前文字和按键 ASR 首版的前置；正文中“scoped 无语音”已过时 |
| 暂停/材料阻塞 | [#96 Boss 正式模型](https://github.com/YYchainsAw/aesir-ai-service/issues/96) | 如有既有材料，可继续做身份与兼容清点；新训练不启动 | 新候选训练暂停。模型缺失意味着交付仍阻塞，不等于任务完成 |

直接可执行的服务端顺序是：**#122 更新阻塞与责任 → #119 真实文本样例 → #98 真实服务端语音 → #121/#123 可靠恢复 → #101/#57 必要质量验证**。#116 贯穿汇总；#99 按本地演示或远程发布分段推进。
