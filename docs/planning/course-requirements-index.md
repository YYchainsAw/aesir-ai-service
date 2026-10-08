# 课程需求分析与建模资料索引

> 整理日期：2026-10-08 · AI main 基线：`1678dd6` · 需求目标材料，非运行验收报告。

## 分工与系统边界

dyh 负责 Python NPC 服务的对话、人格、记忆/关系、行为与协议；yjx / YYchainsAw 负责 UE 游戏、同伴执行及接入，以及本仓库的 Boss RL。职责依据为 [总策划 v0.2](game-design-doc-v0.2.md)与 AesirWarden 当前开发路线，不由本次整理另行分配成员工作。

整组项目名称为 **AesirWarden**；Aesir Agent 是 NPC 子系统名称。NPC Spec 的系统边界仍为 Python 服务，UE 在边界外，Boss RL 保持独立。旧总策划/实现图中的 Aesir Combat Prototype 是历史项目名，不应直接用作当前整组工程名。

## 本仓库提交材料

| 文件 | PNG 预览 | 作用 |
| --- | --- | --- |
| [aesir-agent-sdd-v1.1.md](aesir-agent-sdd-v1.1.md) | 正文嵌图 | NPC 服务需求、7 个用例描述、对象筛选/CRC/分析类图、多重性与追踪 |
| [11-npc-agent-use-cases-to-be.puml](../design/uml/src/11-npc-agent-use-cases-to-be.puml) | [PNG](../design/uml/png/11-npc-agent-use-cases-to-be.png) | UML-11，用例图，一图一文件 |
| [12-npc-agent-analysis-classes-to-be.puml](../design/uml/src/12-npc-agent-analysis-classes-to-be.puml) | [PNG](../design/uml/png/12-npc-agent-analysis-classes-to-be.png) | UML-12，分析类图，一图一文件 |
| [13-npc-agent-object-example-to-be.puml](../design/uml/src/13-npc-agent-object-example-to-be.puml) | [PNG](../design/uml/png/13-npc-agent-object-example-to-be.png) | UML-13，对象正例，一图一文件 |
| [rl/README.md](../../rl/README.md) | — | 独立 Boss RL 训练与冻结推理入口；不并入 NPC Spec 的服务边界 |

本仓库沿用小写短横线文件名；图源沿用两位编号与 `to-be` 后缀。权威图源位于 `src/`，PNG 按用户安排位于 `png/`；共 13 份模型的索引见 [UML README](../design/uml/README.md)。旧 UML-01～10 保留，不覆盖旧证据和基线。

## UE 游戏资料位置

UE 仓库的 SRS 目录已由用户删除，不恢复提交稿、素材副本或刷新脚本。现存游戏流程和战斗说明位于 `Docs/02_Design_Doc/GDD/`，开发范围见 `Docs/05_Development_Guide/06_DevelopmentRoadmap.md`；游戏与整组图源保留在 `Docs/Assets/UML/`，沿用数字前缀和 PascalCase。NPC 图源只在本仓库维护。

UE 仓库入口：[YYchainsAw/AesirWarden](https://github.com/YYchainsAw/AesirWarden)。以本地两仓现存材料为准，不假设未发布路径已在 GitHub 存在。课程 ZIP 已按用户确认删除，不保存或自动生成课程压缩包。

## 实现事实与待核对项

- NPC 默认服务端口为 `8000`，可通过 `AESIR_SERVICE_PORT` 设置；当前 AesirWarden 同伴客户端默认 `8011`，联调前必须统一。Boss 推理保持独立 `8012`。
- 解析/建议被接受、能力启动、命中和完成是不同事实。当前 UE 同伴战斗与回执闭环仍待验收。
- 当前 memory/reset 不清关系档案；失败可能已清会话但未清长期记忆。Spec 的重置后置和关系生命周期假设保留差异记录。
- 原分析图的能力关联多重性仍需按移动/社交等非施法指令复核；对象图为示例，不是本次测得快照。
- Spec v1.1 排除对话 RL 导演层和 Boss RL；N2/N3 为独立扩展，不成为 M1/M2 前置。

## 图源检查与提交

每个脚本自包含、仅一个 `@startuml`/`@enduml`；PNG 按用户最新调整位于 `png/`，与 `src/` 中原脚本同名。NPC 材料为三份图与脚本及 NPC Spec v1.1；UE 保留 `02_GameUseCases`、`03_GameConceptModel`、`01_ProjectUseCases` 图与脚本。本索引只指向现存资料，不在 UE 生成 NPC 副本或课程 ZIP。运行测试状态不由文档渲染提升。
