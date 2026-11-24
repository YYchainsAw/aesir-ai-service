# P1：检索、关联遗忘与对话数据治理

2026-11-19，在 `4489c47` 基础上交付用户指定的三项本机 P1。服务器验收、UE 实机闭环和 Boss 训练不在本轮完成范围；#101 的跨端父项、#54 的真实数据/训练门槛仍不能关闭。私有 `.env` 未修改，没有新增依赖或付费模型选取步骤。

## 检索与真实开销

对话同步/SSE 共用的准备流程传入本轮原文，按本地词面与有限主题别名排序；重要性、时间用于同分排序，已纠错条目仍不参与。明确匹配只注入相关候选，无匹配的普通寒暄不填满预算。弱匹配或无匹配的个人记忆问题保留原预算回退，避免把隐含指代的旧记忆直接丢掉；价格/年份问题不走这个回退。检索不调用模型，不新增向量库；模型选 ID 仍只保留为独立实验入口。

[冻结题集](../../data/evals/memory_relevance.json)扩为 13 条记录（12 条活动、1 条已纠错）、40 题：32 道显式/同义/中英文/否定/承诺/经历/未知问题/实体陷阱题，8 道隐含指代挑战题。属于人工合成开发与挑战集，不是独立真实玩家分布。预算设为当前运行配置的 **12 条**；[脚本](../../scripts/evaluate_memory_relevance.py)默认只离线检索，`--execute` 才付费。两策略使用相同问答提示词、同一模型和 temperature=0，按冻结 answerable/词项标注计分，不是自然角色体验盲评。

| 最终 40 题合计 | 旧重要性预算 | 本地排序＋保守回退 |
| --- | ---: | ---: |
| 回答符合严格标注 | 39/40 | 39/40 |
| 相关条目召回率 | 100% | 100% |
| 无关条目数 | 451 | 125 |
| 精确选中目标集合 | 0/40 | 29/40 |
| 提供方 input tokens | 12,585 | 6,355 |
| 其中 cache hit / miss | 0 / 12,585 | 1,408 / 4,947 |
| output tokens | 541 | 525 |
| 回答耗时中位数 | 801.5 ms | 805 ms |
| 本地检索中位数 | 0.0795 ms | 0.3749 ms |
| 成功模型请求 / 错误 | 40 / 0 | 40 / 0 |

输入减少 **49.50%**，回答中位耗时增加约 **0.44%**，本地排序没有增加模型往返。这里输入只含实验问答，不含完整人格提示词；没有证明整条产品链路节省同一比例。cache 情况受顺序与已有请求影响，实际货币费用须结合当时账单和费率，不能把字符数当 token、把本轮时延当生产 P95/P99，也不把保守回退选到多个候选说成精确检索。

标注复核纠正了一道题：家乡在港口**不能证明**小时候住在港口。旧策略拒答该题，本地组本轮答“港口小镇”，因此保留为无依据推断失败样本；本地组也正确纠正了旧策略拒答的水果改口题。修正前曾输出本地 40/40，该数字撤回。保存原始答案后通过 `--rescore` 离线重评分，没有为修正标注再调模型。[最终逐题与 usage](data/p1-memory-relevance-live-20261119.json)包含这一失败，准确率相同不代表所有逐题行为相同。

开发阶段还做过 1 条预算、严格词面过滤的实验：40 题中隐含指代出现漏召回，不能用它代替 12 条实际配置的验收；加入保守回退后才进行上表最终 80 次全成功请求。早期实验有 6 次上游/熔断错误，随后仅补测那 3 题的两组请求；这些失败保留在忽略目录，不混进最终成功时延。两阶段共观察到 160 次成功模型响应，失败请求是否计费不能由本机错误断言。

## 关联遗忘

- 记忆条目沿用服务端 trace 标签；主题记录内部条目/请求引用，轮次记录产生/注入条目、来源请求及历史依赖。回复印象直接保留依赖，即使会话窗口关闭也不丢关联。
- 遗忘先计算依赖闭包，再原子移除所选及可追溯派生条目、关联主题、依赖轮次，轮换 epoch。可确认无关的早期轮次、其他 run、主题和条目保留。窗口滚动后保留有界依赖闭包；截断或无法归属则标记并保守清理。
- 一个主题含多来源时整主题清理；不是逐提及重算权重。旧数据无关联不猜来源，仍保守清理。不同 ID 的无关联语义副本需要显式选中，不承诺语义擦除。
- JSON/SQL 使用原记忆文档的私有 `_memory_links`，恢复响应与 UE golden 不增加字段；JSON→SQL 导入保留关联。SQL 会话裁剪仅在提交后执行，失败回滚保留 epoch、数据与历史。会话仍不持久化。
- 完整 reset、旧生成提交拒绝、旧 epoch 的离线未确认事实跳过、已确认事实重放不重新落记忆等既有屏障保留。关系、人格、执行/请求账本、日志和备份不属于本次遗忘范围。

`cleared_sessions` 现在计有轮次被裁剪的会话数，包括部分裁剪；字段形状不变。见[契约](../protocols/_01_npc_contract.md#memory-management)。回归覆盖 JSON 重载、SQL 重开/回滚、跨 run 保留、重复事实、多轮依赖、窗口溢出、关闭历史、越权与未展示条目的纠错拒绝。

## 来源分区与质量审计

来源仅由服务端环境配置决定，不接受客户端自报标签：

```powershell
# 在独立的本机采集/测试服务进程中设置；沿用其原有认证、存储配置。
$env:AESIR_DIALOGUE_DATA_ORIGIN='seed'  # natural / fault / evaluation / unknown
$env:AESIR_DIALOGUE_DATA_RUN_ID='p1'   # 短标签，字母数字/下划线/连字符，内部可有点
```

natural/seed/fault/evaluation 分别写入原作用域目录下的来源/运行标签子目录；unknown 保留旧路径。重启进程前固定来源，勿在同一在线实例混跑自然用户与测试。`scripts.emotion_regression` 的专用进程自动覆盖为 seed，并在退出/异常后恢复环境；不会因为 `.env` 写着 natural 把种子当自然数据。故障测试显式设 fault，回归已验证部分 SSE 超时产生 `llm_interrupted`、`turn_complete=false`，不写入对话记忆。

日志新增完整轮次、来源权限、采集标签及降级原因：style_guard、upstream_timeout/auth/rate_limit/http、invalid_response、未细分上游错误、mock_backend。保留复读、负反馈、事实接地拒绝与风格拦截。无依据叙述/完成执行声称只产生**待审候选**，不把规则未命中说成事实正确；执行声称需对照实际回执，日志未自动完成回执核验。旧记录缺少完成/质量标记会单列未核验数。

[聚合审计](../../scripts/rl/dialogue_data_quality.py)按来源分组，仅显式 natural、服务端来源标记完整、scope/request 身份齐全、完整 llm 轮次可进入自然样本计数，按逻辑请求去重，排除已知种子。原有 `count_gate_met` 只是历史数量兼容项，新的自然门槛看 `natural_count_gate_met`。所有计数都不自动批准训练或验证 off-policy 因果收益。

本机历史数据仍是 457 条、376 条已知种子、排除种子后 60 条 llm/12 条非零反馈；457 条旧来源全部 unknown，可核验自然样本 **0**。[聚合输出](data/p1-dialogue-quality-20261119.json)不含私人原文。没有改写旧记录为 natural，没有启动训练；#54 保持开放。

复现：

```powershell
$env:AESIR_COORDINATION_BACKEND='memory'
.\.venv\Scripts\python.exe -B -m scripts.evaluate_memory_relevance --output data/runtime/p1/offline.json
# 有费用：40 题 × 2 次回答，显式执行才调用当前私有 Provider。
.\.venv\Scripts\python.exe -B -m scripts.evaluate_memory_relevance --execute --output data/runtime/p1/live.json
.\.venv\Scripts\python.exe -B -m scripts.rl.dialogue_data_quality --output data/runtime/p1/quality.json
```

完整核心回归 **1733 passed、13 skipped、7 warnings，107.75 秒**；较前一轮 1707 项通过增加 26 项。之后仅收紧运行标签的点目录/尾点校验，并追加 3 个无效标签用例，补充针对性回归 **25 passed**。跳过/警告、完整回归时与最终源码的指纹及结果哈希见[机器记录](data/p1-verification-20261119.json)，原始 XML 保留于忽略目录 `data/runtime/p1/core-tests-final.xml`、`final-validation.xml`。警告为既有 TestClient/HTTP 422 弃用提示。本轮不代替 UE、目标服务器、真实 MySQL/HTTPS 或自然交互盲评验收。
