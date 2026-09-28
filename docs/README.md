# 项目文档索引

按「读者 / 用途」分层的文档导航。快速上手见[根目录 README](../README.md)，里程碑见 [CHANGELOG](../CHANGELOG.md)。

## planning — 策划与愿景

| 文档 | 说明 | 读者 |
| --- | --- | --- |
| [game-design-doc-v0.1.md](planning/game-design-doc-v0.1.md) | AI 队友系统总策划书：愿景、范围、分阶段计划、答辩指标 | 答辩 / 决策 |
| [aesir-agent-sdd-v1.0.md](planning/aesir-agent-sdd-v1.0.md) | **需求规格说明书 v1.0（SDD 整合版）**：项目章程（7 条核心原则）+ 8 个用户故事 + 45 条功能需求 + 实施计划 + 任务分解 T001~T088 + 质量校验清单。系统定位由「语音→战术命令」升级为「NPC 人格与行为代理」 | 全员 / 答辩 |
| [aesir-agent-sdd-v1.1.md](planning/aesir-agent-sdd-v1.1.md) | **需求规格说明书 v1.1（课程 Spec 结构修订版）**：按第 3/4 课规范重写需求部分——H0 人工基线（IN/OUT/角色/REQ/BR/NFR/AT/来源/待确认）+ 用例模型（7 个 UC 图与描述）+ 对象模型（候选/CRC/分析类图/追踪矩阵）+ 代码-文档差异登记（SDD-GAP）。v1.0 原样保留，章程/计划/任务沿用 v1.0 | 全员 / 答辩 / 课程提交 |
| [todo.md](planning/todo.md) | **待完成 / 待优化清单**（2026-09-28 重建）：拓展方向 EXT-01～09（UE 订单闭环、Boss RL 接入、对话 RL 评估、v0.3 契约、Bruno 人格、调试台 UI 等）＋工程改进 FIX-01～08，含优先级与 Spec 审批纪律 | 全员 |

## protocols — 协议契约（对外，UE 侧必读）

| 文档 | 说明 | 读者 |
| --- | --- | --- |
| [ue-protocol-contract-v0.1.md](protocols/ue-protocol-contract-v0.1.md) | **契约 v0.1**：API + `TacticalOrder` 类型定义 + Golden JSON + 能力目录白名单 | UE / Python |
| [ue-integration-guide-v0.1.md](protocols/ue-integration-guide-v0.1.md) | UE 侧接入指南：分步操作 + 21 条验收清单 | UE |
| [combat-tactical-protocol-v0.2.md](protocols/combat-tactical-protocol-v0.2.md) | 战斗事件与上下文感知战术协议 **v0.2（正式版）** | UE / Python |

## guides — 操作指南

| 文档 | 说明 | 读者 |
| --- | --- | --- |
| [getting-started.md](guides/getting-started.md) | 环境、安装、启动、测试、接口示例 | 开发者 |
| [llm-integration.md](guides/llm-integration.md) | LLM 联调、密钥安全、熔断配置 | 开发者 |

## design — 设计预研

| 文档 | 说明 | 读者 |
| --- | --- | --- |
| [Boss RL](../rl/README.md) | 当前 Boss RL 契约、训练与评估入口 | 开发 / 答辩 |
| [uml/README.md](design/uml/README.md) | UE × Python 当前实现 UML、建模基线与证据追踪 | 开发 / 设计 / 答辩 |
| [架构图表集](design/diagrams/Aesir-Agent-架构图表集-v1.0.md) | SDD v1.0 配套 Mermaid 图表（流程图 / 时序图 / 类图 / 状态图 / 部署图 / ER 图） | 开发 / 设计 / 答辩 |

## logs — 开发记录归档

逐日开发记录已压缩进 [CHANGELOG](../CHANGELOG.md)，此处保留原始流水账供回溯：

| 归档 | 主题 |
| --- | --- |
| [2026-09-24.md](logs/2026-09-24.md) | 文档体系检查、结构整合与长期记忆规则建立 |
