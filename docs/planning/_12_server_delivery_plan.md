# 服务端交付计划

## 服务端工作顺序

按服务依赖、交付阻塞与验收范围安排优先级；任务状态以对应 Issue 为准。

**2026-11-18 P0 本机首版收口：** #119 的普通攻击假执行声称已改为确定性拒绝，真实人格诱导与九条正常/拒绝及重放样例通过；#116 的固定版本/启动/重启/回退材料集中到[交接指南](../guides/_13_service_handoff_guide.md)。核心 1680 passed/13 skipped；[本次证据](../records/_07_p0_closure_verification.md)覆盖本机首版交付，服务器 #98/#123/#99 和 UE 仍分别待验。接下来推进 #101，再处理 #103/#100；旧排序与旧缺陷状态作为历史保留。

**2026-11-18 当前执行顺序以 [Issue 核查与责任清单](../records/_06_issue_audit_verification.md) 为准。** #121 文档可收口，#112 已核实重复 #113，#122 清单已更新；#119 新实测发现普通攻击落闲聊且回复暗示执行，仍排首位。当前服务端基线 `1f1e53a` 为 1667 passed/13 skipped。服务器验收按用户要求暂缓，不能再按下方历史顺序自动优先部署；#96 新训练继续暂停。

2026-11-16 通过 GitHub CLI 核对正文、标签及近期评论，创建新任务前共有 15 个 open Issue；随后按用户要求为缓存与事实约束分别建立 P0 #128/#129。下表的其余任务仍是执行建议，没有批量修改其标签或负责人。源码基线 `develop-dyh@13f97d1`；新改动最终核心 1650 passed、13 skipped，本机 LLM/ASR 的前次证据见 [P0 核查记录](../records/_03_p0_delivery_verification.md)。

用户最新三项的进展：#128 缓存布局和长度优化已实现，三请求输入量减少 31.2%，有历史两条命中从 12.0% 到 92.5%（少量样本，非生产保证）；#129 路线与自身状态声称约束已实现，新增 18 项回归，最终完整核心 1650 passed/13 skipped。服务器连接已复查，`baota-server` 无法解析，仍待有效入口。详细数据与语义边界见[本轮记录](../records/_04_prompt_grounding_verification.md)。

- **P0：**当前服务端交接、真实后端可用与必交能力收口。
- **P1：**可靠性、恢复和已有能力的必要验收。
- **P2：**扩展研究、较大机制和非阻断体验。
- **暂停/阻塞：**需要的条件不成立，不占当前开发主线。

| 建议顺序/优先级 | Issue | 服务端交付 | 当前依据与完成条件 |
| --- | --- | --- | --- |
| P0，本轮已实现 | [#128 缓存布局与输入成本](https://github.com/YYchainsAw/aesir-ai-service/issues/128) | 固定内容前置、动态上下文后置，每类保留两条示例，全部 14 类仍覆盖 | 回归及三组真实成对样例通过；实测输入减少 31.2%，保持生产缓存限制说明 |
| P0，本轮已实现 | [#129 无依据路线与自身状态叙述](https://github.com/YYchainsAw/aesir-ai-service/issues/129) | 新增来源规则、确定性拦截、安全重试与流式旧查证清理 | 18 项新增回归及真实样例通过；一般语义蕴含和更广泛质量继续由 #122 等跟踪 |
| 3 / P0，本轮指定 | [#123 SQL/Bearer 真实恢复](https://github.com/YYchainsAw/aesir-ai-service/issues/123) | 找回目标连接，在隔离环境验证正式身份、401/403、异步结果持久化、重启后历史查询与不重复副作用 | 远端目前为 priority:later；因用户本轮明确指定提升执行优先级。原 Issue 不阻塞 11/25 文档交接的口径保留，真实运行验收单独完成 |
| 3 同批 / P0 | [#98 scoped 语音与 ASR](https://github.com/YYchainsAw/aesir-ai-service/issues/98) | 目标服务器真实 faster-whisper→LLM、正式身份上传、门禁、去重和故障切文本 | 本机整链路已有证据；不再重写接口，不强制商业 ASR；UE 麦克风/切换 UI 另验 |
| 4 / P0，补齐样例 | [#119 正常与拒绝样例](https://github.com/YYchainsAw/aesir-ai-service/issues/119) | 保留已验 chat/wait/follow/burst，补正文指定的出戏诱导、战斗中 follow 拒绝、攻击无目标/冷却拒绝 | 当前已有的缺目标拒绝是 follow，尚未覆盖所有 attack 拒绝；basic_attack 按实际目录判断，不发明支持 |
| 贯穿 / P0，收口 | [#122 阻断缺陷与责任](https://github.com/YYchainsAw/aesir-ai-service/issues/122) | 汇总本轮最新 SHA、测试、认证已恢复和质量/环境剩余项 | 正文仍停在 11/05 的 1576 项；当前 1650 passed/13 skipped 与源码、正式环境分开写 |
| 贯穿 / P0，父任务 | [#116 服务交接](https://github.com/YYchainsAw/aesir-ai-service/issues/116) | 汇总固定基线、非敏感配置、接口包、样例与恢复/回退证据 | 当前负责人 loooooooooogp，目标 11/25 是原计划而非新增工时承诺；不重复计算子项工作 |
| 目标验证前整理 / P1 | [#121 JSON/SQL 差异文档](https://github.com/YYchainsAw/aesir-ai-service/issues/121) | 在 #123 前整理运行模式、权限、错误、数据路径、recovery/sync 映射，验证后补实测 | 复用指南，不另造平行契约；文档和真实恢复完成状态分开 |
| 5 / P1 | [#101 记忆来源与纠错](https://github.com/YYchainsAw/aesir-ai-service/issues/101) | 补真实 LLM corrected_fact_ids、来源和越权回归 | corrected_fact_ids 已有修复，先验证，不重做数据库/向量检索 |
| 6 / P1 | [#57 时间、读档、衰减](https://github.com/YYchainsAw/aesir-ai-service/issues/57) | 验证时间、冷却、save/generation、epoch 与旧事实确认 | 服务端证据与 AesirWarden#21 的 UE 队列/读档依赖分开 |
| P1 受控部署；P2 公网容量 | [#99 HTTPS、数据切换与容量](https://github.com/YYchainsAw/aesir-ai-service/issues/99) | 先做隔离实例、私有配置、备份/恢复与回退；实际公开服务前完成 HTTPS/权限/容量 | 不为本机演示先做公众容量，也不能把远程正式访问当本机演示绕过认证 |
| P2 | [#100 事件/条件/阶段](https://github.com/YYchainsAw/aesir-ai-service/issues/100) | 必要诊断可提前；未来条件登记与阶段协议后置 | 不为展示临时增加 started/hit/completed |
| P2，核账优先 | [#112 情感桶种子](https://github.com/YYchainsAw/aesir-ai-service/issues/112) | 对照已 closed 的 #113 列出剩余验收或重复范围 | #113 的 11/05 评论记录三阶段已完成；不自动关闭 #112，也不重跑整套付费样例 |
| P2，父跟踪 | [#103 20 项交接](https://github.com/YYchainsAw/aesir-ai-service/issues/103) | 更新能力与两仓依赖映射 | 不当作 20 项同时重做的研发任务 |
| P2，数据依赖 | [#54 对话 RL 导演层](https://github.com/YYchainsAw/aesir-ai-service/issues/54) | 保留离线信号评估与数据门槛 | 评论已批准评估并交付切片 A，后续依赖数据；不是待批准，也不是已批准上线在线学习 |
| P2，后置体验 | [#56 VAD/TTS/打断](https://github.com/YYchainsAw/aesir-ai-service/issues/56) | 后续语音体验增强 | 不阻塞按键 ASR 与文本首版 |
| 暂停/材料阻塞 | [#96 Boss 模型](https://github.com/YYchainsAw/aesir-ai-service/issues/96) | 保留既有模型清点与可信产物接收；新训练继续暂停 | 远端虽标 priority:p0，但当前用户暂停决定优先；ZIP/manifest/selection 缺失，不能宣称正式模型完成 |

原执行顺序为目标服务器 → #119 → #101/#57；已由上方 11-18 核查调整为 **#119 → #116 收口 → #101 → #103/#100**。#57 保留 UE 依赖；#98/#123/#99 服务器部分暂缓，#54 等数据门槛满足后再推进，#56 仍后置。
