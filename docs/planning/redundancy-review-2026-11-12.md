# 代码冗余与文档清理报告

日期：2026-11-12。基线：`develop-dyh@3e4bcf1`，包含本地尚未提交的接手导览。

> 后续实施更新：本页第 1～7 节保留最初审查依据。R1～R6 已在本地实施；R7 已抽离提示词、调试页及旧路由业务，剩余大模块尚需按业务边界继续拆分。当前结果、测试与未解决缺陷以[结构整改与后续行动](structure-followup-2026-11-12.md)为准，不再把下文“未重构”当作最新工作区状态。

## 1. 结论：哪里复杂，哪里确实重复

项目存在可收敛的重复，但**不能把 legacy、SQL/JSON、mock/真实后端或训练/推理直接删成一套**。本次最值得处理的是：Boss 三套适配逻辑、scoped 对旧路由的业务依赖，以及同步/流式对话重复编排。小工具也有三组确定的函数复制。

本轮交付：完成静态结构审查和证据整理，删除三份被现行文档替代的过时文档，修正保留文档中的直接相关错误和引用。**未删除或重构业务代码，未训练新模型。**

## 2. 检查范围与方法

检查 `app/`、`rl/`、`scripts/`、`tests/` 的 Python 文件；对生产/工具函数做 AST 结构比较，再人工辨别语义；追踪 scoped 对旧路由的调用、Boss 加载路径、文档内部链接和交接包导出清单。

本机目录统计（含空行和注释；scripts 包括本地辅助脚本，不等于 Git 发布体积）：

| 目录 | Python 文件 | 行数 | 理解 |
| --- | ---: | ---: | --- |
| app | 135 | 17,859 | NPC 服务、协议、状态与业务 |
| rl | 11 | 1,440 | Boss 训练环境与推理等 |
| scripts | 34 | 4,896 | 启动、评估、诊断、迁移与运维 |
| tests | 110 | 19,770 | 测试代码，不能当成业务冗余 |

严格 AST 比较忽略函数名称和首段文档字符串，筛选原始跨度至少 8 行的函数。命中四组，其中一组是 Protocol 方法的 `...` 声明，人工排除；其余三组为下述 R4～R6。**这不是全项目重复率，也不能证明其他代码都没有冗余或没有死代码。**动态导入、装饰器、脚本入口及外部 UE 调用都可能让“搜索不到引用”产生误判。

初始扫描有 67 份本机 Markdown，包含被忽略的历史日志和临时规划；本次没有批量删除这些个人记录。文档删除后的首次清点保存在 `data/runtime/redundancy-review-20261112/post-audit.json`；`inventory.json` 已在后续整改时刷新，不再表示最初快照。

## 3. 确认的冗余与结构问题

### R1：Boss 训练、离线评估和 HTTP 推理维护三份策略适配

**建议优先级：高；性质：逻辑重叠，已出现规则漂移。**

- [训练 PPOBossPolicy](../../scripts/rl/boss/train.py:72)：构造掩码、确定性预测、转动作枚举。
- [离线 FrozenBossPolicy](../../scripts/rl/boss/eval_frozen.py:26)：重复适配，另行检查维度和动作数量。
- [HTTP BossPolicyRuntime](../../rl/boss/inference.py:75)：再次适配，另加锁、暂时无动作、manifest/实际空间与 SHA 检查。

问题不只是多写几行。HTTP 已经对同一内存快照做 SHA 和加载，离线评估仍是先摘要路径再重新打开；HTTP 验证 manifest、空间类型/范围/起始动作，离线检查没有同等要求。修改一处后容易忘记其他入口，校验结果难以比较。

**建议：**提取不导入训练入口的共享预测适配与产物验证模块；保留训练对象适配、HTTP 互斥和暂时无动作语义等各入口差异。训练不必强制套冻结 SHA，离线评估也不能通过导入 train.py 复用。验收覆盖三入口动作掩码一致、校验快照一致、失败无就绪及 CPU 加载行为。

### R2：新版 scoped 仍调用旧路由，路由层兼任业务层

**建议优先级：高；性质：职责耦合，不是两套完整独立实现。**

[scoped.py](../../app/api/v1/scoped.py:276) 调旧 `agent_step`；同文件还依赖 agent 的私有映射、world 的 `report_world_event` 以及 console 查询函数。与此同时 [agent.py](../../app/api/v1/agent.py:305) 包含角色校验、调度分发、指令组装和埋点，不是薄 HTTP 包装。

因此，“默认关闭 legacy HTTP”不等于“legacy 文件无用”。直接删除旧路由模块会破坏新版调用。两个入口的 DTO 转换、异常翻译和作用域包装也使调用链变长，接手者很难看出真正业务入口。

**建议：**先把 agent/world/console 的可复用业务操作移至 service 层，让新旧路由都依赖 service，再讨论旧 HTTP 的下线。迁移时保留能力门禁、作用域上下文、取消/时效提交屏障和一次性埋点。验收至少覆盖 `tests/api`、`tests/scoped` 与相关持久化测试。

### R3：同步和流式对话重复组装上下文、写入参数

**建议优先级：中；性质：重复编排，具有漂移风险。**

[dialogue_service.py](../../app/services/companion/dialogue_service.py:31) 的普通回复与流式入口分别读取角色、历史、记忆、印象和关系，再分别处理生成/降级及提交。同文件的 `_record_turn` 调用也分散。

可见差异：普通路径显式传 `relationship_stage`、`memory_cited` 并接收 `relationship_delta`；流式提交调用没有传这两项，也没有采用相同的 delta 赋值方式。这里记录的是调用结构差异，**本次未据此宣告所有流式结果均错误**，仍需按输出及埋点行为复现。

**建议：**抽取共同的“对话输入上下文”和“提交结果”过程；保留 SSE 在发出部分文本后中断、不应提交完整记忆的特殊语义。不要简单把流式改成先等普通回复结束再输出，这会丢失真正流式体验。

### R4：两份离线报告复制同一个 JSONL 读取器

**建议优先级：中；性质：确定复制。**

[dialogue_signal_report.py:28](../../scripts/rl/dialogue_signal_report.py:28) 与 [style_regression_report.py:41](../../scripts/style_regression_report.py:41) 的 `_iter_records` AST 一致。路径扫描、空行/坏行和读文件异常策略需要维护两次，两份目前都使用 `*/*.jsonl`。

**建议：**提取无业务依赖的报告读取器，明确是否递归、坏行是否计数、是否拒绝非对象记录。两份报告保留各自聚合逻辑。先核对 scoped 多层目录实际结构，避免只抽函数却保留错误扫描假设。

### R5：两份端到端脚本复制 HTTP 包装

**建议优先级：低；性质：确定复制。**

[c_llm_e2e.py:24](../../scripts/c_llm_e2e.py:24) 与 [negative_examples_e2e.py:24](../../scripts/negative_examples_e2e.py:24) 的 `http()` AST 一致。JSON 编码、请求头、超时及错误解码相同。

**建议：**放入 scripts 内部小型公共模块，保留两份测试场景；检查其他请求脚本时不要强制所有工具使用同一有副作用的客户端。真实 LLM 脚本会产生调用成本，重构验证优先用替身，本轮未执行它们。

### R6：两种解析器复制文本正规化

**建议优先级：低；性质：确定复制，但体积很小。**

[parsers/rule.py:40](../../app/services/parsers/rule.py:40) 与 [tactical/intent_parser.py:24](../../app/services/tactical/intent_parser.py:24) 的 `_normalize` AST 一致：去首尾、转小写和少量标点/空格替换。

**建议：**若后续统一解析行为，可提取单个小函数；不为约 8 行复制建立大型抽象框架。两种解析器的输出协议、意图和能力约束不同，不建议因此合并整套解析器。

### R7：少数大文件增加理解成本，但行数不等于冗余

**建议优先级：中；性质：职责集中。**

| 文件 | 行数 | 可按什么边界拆分 |
| --- | ---: | --- |
| `app/services/companion/llm_dialogue_service.py` | 775 | 提示词组装、查证工具流程、输出解析、流式提取 |
| `app/api/v1/agent.py` | 693 | HTTP 包装、业务分发、指令构造、可观测性 |
| `app/api/v1/scoped.py` | 685 | 控制绑定、文本/语音、事件回执、只读恢复 |
| `app/services/tactical/event_policy.py` | 628 | 事实去重、战斗/生活规则与反应组装 |

例如 [system prompt 组装](../../app/services/companion/llm_dialogue_service.py:540) 包含较长规则和历史说明。可把长提示词与事故复盘分开维护，但提示词本身影响模型行为，不能当普通注释删掉。拆分先保持公开调用签名和行为，避免“少了文件但多了隐藏依赖”。

## 4. 这些看似重复，本次明确保留

| 部分 | 保留原因 |
| --- | --- |
| legacy 路由及 v0.1/v0.2/v0.3 契约 | 已注册且部分被 scoped 内部复用；旧客户端兼容仍有用途 |
| JSON/内存与 SQL 的幂等、指令账本 | 不同生命周期和事务保证，不是可直接互删的副本 |
| memory / Redis / shadow 调度器 | 本地开发、外置协调与对比验证用途不同；memory 不是已废弃实现 |
| mock / fallback / 真实模型后端 | 模拟、故障降级与真实调用语义不同 |
| Boss 与 NPC 两个服务 | 部署位置、依赖和故障边界不同，合并反而增加耦合 |
| `__init__.py`、小型 schema、异常和门禁模块 | 包组织、严格字段和跨模块契约本身有用途，不能按文件小判冗余 |
| tests、迁移/备份/恢复工具 | 测试和显式运维入口可能不被业务 import；无静态引用不能判死代码 |
| 数据库设计、SDD、UML、旧版本验证记录 | 保留设计及验收追溯；日期旧不代表内容失效 |
| 刚新增的新人导览 | 面向接手者的导航，不替代现行字段契约 |

本轮没有获得足够证据将任何生产 Python 模块判定为可安全直接删除的死代码。

## 5. 本次实际删除的过时文档

三份都受 Git 管理，可从清理前的 `3e4bcf1` 回查，不是仅凭日期删除。

| 已删除路径 | 具体失效依据 | 当前替代入口 |
| --- | --- | --- |
| `docs/guides/yearend-handoff-2026-11.md` | LLM 使用已不匹配显式配置别名的 AESIR_LLM_*；将 memory 写成调度默认；数据路径忽略 scoped 层级；引用不存在的 memory 文档；与新交接说明重复 | [新人导览](../guides/project-onboarding-2026-11.md)、[UE适配](../guides/ue-service-adaptation.md)、[持久化指南](../guides/persistent-development.md)、[发布模板](../../deploy/README.md) |
| `docs/guides/yearend-v05-contract-examples.md` | req-001 与省略 UUID 不能直接满足当前严格 schema；把预算写成服务端默认值待调；对状态查询/重启回放过度简化，与现行契约及适配说明并行维护 | [异步契约](../protocols/npc-async-loop-v0.5-draft.md)、[真实字段请求模板](../examples/ue-scoped.http)、[UE适配](../guides/ue-service-adaptation.md) |
| `docs/planning/stage0-cde-followup.md` | 将已实现的 shadow/Redis/journal/异步继续列为未来计划；拟将 memory 移到测试目录，与当前本地开发路径冲突；不再适合做当前路线入口 | [六步方案](local-boss-cloud-companion-roadmap.md)、[异步契约](../protocols/npc-async-loop-v0.5-draft.md)、[历史验证](../logs/verification-records.md) |

被删年度交接页记录的 `yearend-2026-11-baseline` / `e50fbc1`、1574 passed / 11 skipped 是其历史主张，本次未重验，不挪作当前成绩。原始文本仍可通过 Git 历史查看，例如 `git show 3e4bcf1:docs/guides/yearend-handoff-2026-11.md`。对应的 `scripts/v05_async_e2e.py` 验证脚本保留。

同时做了以下文档修正：

- 移除异步契约对已删阶段计划的链接，改指当前适配与路线；修正其两处 timing.py 相对路径，标题标明“服务端已实现”。
- 修正 getting-started 的“外部 ASR 尚无适配”“没有 WAV/大小/时长门禁”等过时描述，并为本机 JSON 启动补显式 memory 调度配置。
- 更新 README 的 ASR 状态，保留真实 UE/生产待验边界；在文档索引挂接本报告，保留上轮尚未提交的接手导览与入口。

没有删除 `docs/logs/`、本机忽略的测试报告、模型、记忆或私人配置。扫描发现的既有历史日志断链、跨仓绝对布局引用另列为剩余维护项，没有拿“找不到另一仓目录”当作删除文档的理由。

## 6. 建议的后续收敛顺序

1. **先统一 Boss 共享适配与加载验证。**已有可复现差异，先获得行为一致的收益；维持新训练暂停。
2. **再把 agent/world/console 业务从旧 HTTP 路由中抽出。**这一步后才能评估 legacy 下线，不能倒序删文件。
3. **统一对话上下文和提交参数。**分别保留同步/SSE 的中断语义，核对关系及埋点一致性。
4. **最后合并三组小型工具函数。**成本小，但对整体复杂度的收益也小。

以上代码变更仅为建议，本次没有实施。优先通过分层减少理解成本，而不是追求删除最多文件或最少代码行。

## 7. 本轮验证与限制

本轮已完成以下核对：

- 被删文件名仅在本报告的删除清单/历史回查示例中出现；保留文档及代码没有继续使用这些旧链接或打包路径。
- 本轮新增/修改的 Markdown（两个索引、启动指南、接手导览、异步契约及本报告，共六份）未发现失效的本地文件链接。检查不验证公网 URL、标题锚点或外部 UE 仓库状态。
- `python -m scripts.export_ue_handoff --output-dir data/runtime/redundancy-review-20261112/ue-handoff` 成功，确认导出清单未依赖被删文档；这是离线源码导出，不是服务运行验收。
- `git diff --check` 通过；`git diff --name-only -- '*.py'` 无输出，受 Git 管理的 Python 业务代码未改动。

没有为文档删除重复运行完整业务回归，也未调用真实 LLM/ASR、训练、生产数据库或 UE。已有历史日志/跨仓链接问题未在本轮全部修复，不能将上述定向链接检查解释为整个 docs 已无断链。

本报告是静态审查与文档维护结果，不是整仓安全审计、动态覆盖率证明或正式发布验收；没有承诺所有潜在冗余已发现。
