# P1 服务端验证

基于 `51a47c0` 的本机增量，完成模式差异文档、记忆纠错边界和发布预检加固。适用范围为 Windows 本机隔离状态；真实模型使用 DeepSeek `deepseek-flash`，关闭思考。脱敏合成场景、逐请求结果、回归分组、跳过原因与源码 SHA256 见 [实测数据](data/p1-server-20261116.json)。本轮没有修改私有 `.env`。

## 2026-11-18 续验

本轮按已确认范围暂不执行服务器验收。保留上次真实 DeepSeek 三轮证据，没有重复付费请求；新增两项 SQL/Bearer 隔离回归和可复现的 M1 离线检索实验。SQL 测试使用 SQLite 与受控模型桩，不能计作真实模型、MySQL 或真实进程重启验收。

SQL 纠错测试通过真实 Bearer 路由提交候选：只作废已注入的玩家事实，隐藏事实和观察记录保持不变；相同请求不再生成、不再写状态。随后清空运行协调器、绑定和记忆缓存，关闭并重新打开同一数据库：恢复查询保留记忆、关系、epoch、generation 和版本，历史 operation 为 complete 且没有可执行 result，旧 binding 的 POST 返回 409。另以事务中断验证纠错回滚后权威状态不变。这是同进程重建运行对象及重开 SQLite 文件的验证，不能称为 HTTP 服务进程重启。

### M1 初步离线对照

实验代码 [evaluate_memory_retrieval.py](../../scripts/evaluate_memory_retrieval.py)、[人工标注合成集](../../data/evals/memory_retrieval.json)和[逐例结果](data/memory-retrieval-20261118.json)均可审阅。六条记录、八个问题包含旧偏好、家乡、共同经历、承诺、过敏、无依据问题、同义表达遗漏和关键词误召回；已 superseded 的记录两方案均排除。每例最多读取两条。

对照基线为当前重要性/时间预算检索；候选在当前 scope 的摘要、ID 和人工关键词索引中选条目，再模拟一次批量读全文。候选只用于实验，没有接入运行服务，也没有向恢复 API 增加读全文工具或游标字段。

| 八例合计 | 现行预算 | 摘要索引＋读全文候选 |
| --- | --- | --- |
| 正确相关条目 / 无关条目 / 遗漏 | 2 / 14 / 4 | 5 / 1 / 1 |
| 与标注完全一致的问题 | 0 / 8 | 6 / 8 |
| 传入记忆文本字符（候选含每轮完整索引） | 2272 | 5303 |
| 额外批量全文读取次数 | 0 | 6 |

“无关条目”表示不属于当前问题的标注，不表示这些已存事实本身是虚假内容。人工索引的候选在这组特意暴露预算遗漏的合成题上更相关，但仍漏掉“不能吃哪种坚果”的同义问法，并对“路边花生价格”误召回过敏记录；索引文本开销也更大。因此保留现行线上策略，不能据这八例宣称完成生产检索质量验证。

结果逐例记录本机选择/查询耗时；字符数不是提供方 tokens，纯内存耗时也不是额外工具的网络/模型时延。本轮没有模型选择工具、自动生成摘要、真实 token 对比或真实玩家分布测试，M1 完整验收继续保留。后续应以脱敏代表集比较回答正确率、真实 usage、工具端到端时延与错误，再决定是否上线候选。

复现命令（无上游调用）：

```powershell
$env:AESIR_COORDINATION_BACKEND='memory'
.\.venv\Scripts\python.exe -B -m scripts.evaluate_memory_retrieval --output data/runtime/p1-20261118/memory-retrieval.json
.\.venv\Scripts\python.exe -B -m pytest tests/persistence/test_memory_correction.py tests/scripts/test_memory_retrieval_eval.py -q --tb=short -p no:cacheprovider
```

本轮最终完整回归 **1667 passed、13 skipped、7 warnings，102.42 秒**，其中新增 SQL 纠错两项与检索实验两项均通过。回归结果、逐项跳过原因与提交前源码指纹见 [2026-11-18 回归摘要](data/p1-server-20261118.json)；原始 XML 在 `data/runtime/p1-20261118/core-tests.xml`。服务器/真实 MySQL/HTTPS 与 UE 仍未验；#101 的完整来源追溯、受控遗忘和 C3 跨端队列也不随本次局部实现整体关闭。

## 交付与剩余范围

| Issue | 本轮完成 | 仍未完成 |
| --- | --- | --- |
| [#121](https://github.com/YYchainsAw/aesir-ai-service/issues/121) | 在[持久化指南](../guides/_06_persistence_guide.md)补齐 JSON/development 与 SQL/Bearer 的身份、启动、存储位置、恢复、错误和重启去重差异；修正示例配置对默认启动的误导 | 真实 SQL 恢复演示按该 Issue 原范围后置；文档完成不等于目标环境验收 |
| [#101](https://github.com/YYchainsAw/aesir-ai-service/issues/101) | 限制模型纠错候选的来源、注入集合、ID 格式及唯一性；增加作用域与逻辑请求审计；真实三轮更正/回忆及重试验证 | 完整来源追溯、受控遗忘、M1 检索对照、C3 与 UE 队列整链路仍未全部交付，Issue 不能整体关闭 |
| [#57](https://github.com/YYchainsAw/aesir-ai-service/issues/57) | 复核已有时间、衰减、run/binding、旧 epoch 分项确认及稳定 ID 回归，结果见下表 | UE #21 的读档、断网队列及实际恢复证据仍待验 |
| [#99](https://github.com/YYchainsAw/aesir-ai-service/issues/99) | 发布预检在私有连接文件不可读时明确 BLOCK；配置解析失败仅输出异常类型，避免带出私有值；本机生产预检实际返回退出码 1 | 目标服务器、真实 MySQL、HTTPS、正式备份/回滚、容量和 UE 验收仍待条件齐备后执行 |

## 记忆纠错边界

模型的 `corrected_fact_ids` 只是候选。服务端仅允许更正本轮实际注入、尚未失效、来源为 `player_statement` 或 `promise` 的条目。未注入事实、观察/共同经历及其他 NPC/玩家/存档不因模型猜出 ID 获得更正权限；人格和关系规则也不在此接口的更正范围。

ID 仅接受 8 位十六进制短码或完整 UUID，兼容既有展示包装。短码匹配多个活动条目时拒绝，不再截断任意字符串或一次作废多个条目。完整 UUID 可消歧。原文、来源和时间仍保留，使用既有 superseded 标记排除旧事实，不在本轮引入物理删除或新协议字段。

对话信号增加 `memory_corrections` 的 proposed/applied/rejected 计数；scoped 信号补入当前逻辑 `request_id`，与已有 game/player/save/npc/run/epoch 关联。缓存重试不再记一遍对话和更正。此审计是文件信号，不能替代 SQL 事务账本，也不代表完成全部 M2 来源追溯。

## 真实 LLM 合成验证

本机隔离 development/json/memory 服务通过 v0.5 异步提交和状态轮询完成三轮，每轮实际一次上游生成且 `source=llm`：

| 场景 | 结果 | HTTP 提交至完成耗时 |
| --- | --- | --- |
| 记住最喜欢苹果 | 生成原始玩家事实，回复确认 | 1781 ms |
| 明确改为香蕉 | 模型提出两个原苹果记录 ID；服务均合法作废，保留新的香蕉事实 | 1750 ms |
| 再问喜欢什么 | 回答香蕉，原苹果事实保持失效 | 1469 ms |

每轮以同一 request_id/载荷重试，返回原结果且记忆快照不变；三个逻辑请求各只有一条对应纠错审计。另一个 NPC 的 archive 为空，非授权存档返回 `403 SCOPE_FORBIDDEN`。这些是合成数据，不含真实玩家内容或凭据。

共用两轮三请求验证：初次验证业务后，补审计 request_id 再复测一次，最终三请求数据见链接。上述耗时不代表生产分位延迟或容量。没有重新执行 ASR，之前 ASR→LLM 的有效证据仍见 [P0 记录](_03_p0_delivery_verification.md)。

## 回归与预检

最终核心回归 **1663 passed、13 skipped、7 warnings，pytest 摘要 96.42 秒**。相对 P0 的 1650 项通过新增 13 项通过；XML suite 时间 96.284 秒与控制台总时间口径不同。命令如下：

```powershell
$env:AESIR_COORDINATION_BACKEND='memory'
.\.venv\Scripts\python.exe -B -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q --tb=short -p no:cacheprovider --basetemp C:\aesir_pytmp\p1-core-final-20261116 --junitxml=data/runtime/p1b/core-tests-final.xml
```

| 分组（均包含在上述总数中） | 通过 | 覆盖 |
| --- | --- | --- |
| 纠错边界、scoped 更正与审计关联 | 8 + 2 + 1 | 非法短码、碰撞、隐藏/其他来源/NPC 候选、实际注入集合、同 ID 重试 |
| 关系时间规则 | 12 | 冷却、日上限、旧时间不绕过冷却 |
| 记忆主题/衰减 | 37 | 半衰期、显著性及印象权重 |
| scoped runtime | 12 | 玩家/存档隔离、CAS、重启拒绝旧绑定、显式重新绑定 |
| SQL sync（隔离 SQLite） | 31 | 稳定事实身份、重复确认、reset 分项、generation/版本冲突；1900/2100 的 occurred_at 不倒退计分日或绕过冷却 |
| 发布预检 | 7 | 配置门禁、ASR 凭据、不可读连接文件及错误信息不泄露私有值 |

13 项跳过仍为可选/平台/未提供真实 MySQL 等既有条件，逐项原因保留在实测数据；不能计作真实 MySQL 或目标服务器通过。warning 为既有 Starlette/httpx 与 422 常量弃用提示。

本机 `python -m scripts.release_preflight --mode production --json` 实际返回 1：identity、storage、database_url、coordination、legacy_routes 五项 BLOCK；LLM/ASR 配置门禁通过，HTTPS 为 WARN。该命令只读配置，不验证提供方健康、数据库连接或证书。没有为消除 BLOCK 擅自切换本机身份或数据后端。

原始本机证据位于忽略目录 `data/runtime/p1b/`：最终回归 XML、三轮请求与记忆快照、服务日志、发布预检 JSON。持久化指南已链接本记录及可审阅摘要。

## 目标环境与跨端边界

当前仍没有有效的目标项目 SSH 入口，阻塞现状及已核查范围沿用 [P0 的目标服务器记录](_04_prompt_grounding_verification.md#目标服务器仍缺连接条件)。本轮没有目标服务器结果，也没有真实 MySQL HTTP 进程重启、HTTPS、容量或 UE/GAS 执行结果。SQL/Bearer 的隔离自动化通过不能替代这些实际验收。M1 检索对照和 UE C3 队列属于独立剩余交付，不能随本轮纠错修复标记完成。
