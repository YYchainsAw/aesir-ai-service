# 联调复现与证据范围

> 2026-10-19按`a2dd426`整理。目标是使另一个成员能确定运行版本、输入、后端及结果；本页不声称本轮已启动服务或执行运行测试。启动见[本机指南](getting-started.md)，UE操作顺序与正式SC-011见[联调指南](../protocols/integration-alignment-v0.3.md)。

下述操作与历史样本属于本机开发基线。远程部署另按[AT-DEP验收](deployment.md#验收条件)记录HTTPS、身份/存档、数据库/同步版本、外部ASR及并发配置；本次未执行新增运行验收。

## 先固定运行实例

在服务终端记录run_server实际地址；另取health，不用本机HEAD替代运行实例：

```powershell
curl.exe http://127.0.0.1:8011/health
```

当前health响应为status=ok、service=aesir-ai-service、protocol_version=0.1和service_commit。commit是进程读取后缓存的short SHA；非Git环境为unknown。health不是所有端点的统一API版本；现行scoped JSON用[v0.4](../protocols/npc-scope-contract-v0.4-draft.md)，显式legacy开发兼容入口才按agent/step/world=0.3、tactical=0.2、对话/旧订单=0.1分别解释。

每次正式复现至少记：实际日期、两仓提交/构建、地图与资产、当前游戏/角色、后端名称、地址/端口、配置版本、输入/快照、返回状态/source/reason_codes、UE实际阶段及证据位置。密钥不写入记录，私人文本/音频先按分享范围处理。

## 后端三态分开记录

| 场景 | 触发与响应 | 如何解释 |
| --- | --- | --- |
| Mock/规则 | companion_backend=mock或解析rule | 用于本地路径核对，不能作真实LLM/ASR通过 |
| LLM | 显式配置对应llm后端；对话source=llm | 记录真实模型/配置、降级与实际延迟，仅覆盖该样本 |
| Fallback | 对话模型失败回角色候选，source=fallback；解析失败回规则，source=rule_fallback | 不混淆两个接口的来源枚举；耗时可能已包含失败等待，不能承诺必小于5毫秒 |

style_violations及其他可选观测按实际返回/日志记录。是否存在字段不单独证明表达合格；有delta而无meta的中断轮次不当完整对话。

既有记录在2026-10-08的8000实例采到LLM对话约2328.8毫秒、规则战术约19.3毫秒等HTTP样本，见[历史矩阵](../protocols/integration-alignment-v0.3.md#历史实测与适用范围)。这些日期与端口保留，不能改成当前8011重测，也不是当前P95或UE开始响应的证据。

## 按目的运行工具

| 工具 | 命令 | 结果边界 |
| --- | --- | --- |
| 终端对话 | `.\.venv\Scripts\python -m scripts.chat_console` | 可检查人格/会话；会产生正常记忆和完整文本信号记录 |
| 假UE流程 | `.\.venv\Scripts\python -m scripts.command_service.mock_ue_flow` | 先启动服务；HTTP/回执演示可写运行数据，不等于实际UE角色执行 |
| 记忆持久化演示 | `.\.venv\Scripts\python -m scripts.demo_memory_persistence` | 按脚本选定的隔离/数据目录检查，不能拿演示替真实角色删除验收 |
| 事后统计 | `.\.venv\Scripts\python -m scripts.metrics_report` | 汇总既有日志，PASS含采集/覆盖代理，不直接判定全部SC需求通过 |
| 自动测试 | [核心回归命令](remote-development.md#核心回归)，含 `tests/scoped` | 记录具体commit及实际输出；单元/API测试不等于真实后端、UE或正式性能验收 |

不在文档中预填执行人/日期或当前PASS数量。脚本参数以其实际--help和实现为准；真实LLM/ASR另需网络/模型和可用配置。本轮文档修订未执行这些操作。

## 数据去哪、怎样清理

| 数据 | 当前位置/关联 | 限制 |
| --- | --- | --- |
| 对话信号 | data/runtime/dialogue_signals/<game_id>/<companion_id>.jsonl | 正常轮次默认尝试存完整player_text/reply_text，写失败不保证保存；不是仅摘要 |
| 执行回执 | data/runtime/command_service/executions/<game_id>/<UTC日期>.jsonl，按order_id关联 | 仅追加；调用方game_id尚未绑定当前游戏，不把目录分区当入口授权 |
| 记忆/关系 | data/memory和data/relationship的游戏/角色分区 | memory/reset清目标会话及长期记忆，保留人格/关系/信号/回执；持久失败可能部分完成 |
| 世界事件 | HTTP响应和有限幂等缓存 | 无独立持久事件日志；需要复查时保存实际请求/响应，进程缓存不作永久事实账本 |
| 请求关联 | 各端点实际body及适用观测字段 | 部分端点没有UUID/统一请求头；不能假定所有响应都有同一种X-Request-Id |

不传session_id仍可访问/写入长期数据。LLM还可能发送人格、记忆、近期历史和工具结果，见[数据流说明](llm-integration.md)；本地reset不证明外部后端已删除数据。角色A reset后应核对A清理结果、B不变、人格/关系不变及失败返回，不假设全有全无。

## 正式验收与采集代理

需求验收按[SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)的UC/BR/NFR/AT，模型/追踪另行审查。metrics_report可报告是否有样本、来源/阶段覆盖、重复率等；两个角色都聊过不能证明隔离，memory_cited>0不证明记忆引用正确，覆盖三个关系阶段不证明语气区分成立。

SC-011需UE输入到NPC实际开始表现的两端时戳、至少30次文本/语音混合样本及已确定条件；生产对话record_turn_signal当前未填latency_ms，不能靠再聊一轮自动补齐。端点单次HTTP耗时、模型推理耗时、UE执行延迟分别报告，失败/超时也保留，未采集继续标未验收。

课程材料中的AI预审和图源导出同样不是人工语义接受；完整提示或同伴审查缺失时如实写缺口。跨端协议/未制作能力/保留策略未关闭前，不用一次演示把它们批量标成完成。
