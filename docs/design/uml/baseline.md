# UML 建模基线

> 基线日期：2026-09-10  
> 建模口径：当前实现（As-Is）优先；目标设计（To-Be）单独建图。

## 1. 仓库基线

### Unreal 客户端

- 仓库：`https://github.com/YYchainsAw/UE_AesirCombatPrototype.git`
- 本地路径：`D:/YYchainsaw/Unreal-Projects/AesirCombatPrototype`
- 分支：`feature/player-combat`
- 提交：`dead903156946ec6956342f02d587612baab1717`
- 工作区状态：建立基线前无未提交修改
- Unreal Engine Association：`5.8`
- Runtime Module：`AesirCombatPrototype`

### Python AI 服务

- 仓库：`https://github.com/YYchainsAw/aesir-ai-service.git`
- 本地路径：`C:/Users/YYchainsaw/PycharmProjects/aesir-ai-service`
- 分支：`main`
- 提交：`f548c1ad64c5d284eace084132616d171d45403f`
- 工作区状态：建立基线时无未提交修改
- 当前虚拟环境 Python：`3.11.9`
- FastAPI：`0.141.1`
- Pydantic：`2.13.5`

## 2. 文档基线及权威级别

发生冲突时，按照下列顺序判断 **当前实现**：

1. 当前提交下实际运行的 C++、Python、蓝图和行为树；
2. 自动化测试、项目配置、能力配置和 OpenAPI Schema；
3. 协议契约与 UE 接入指南；
4. 总策划书、设计预研和开发日志。

Python 服务侧的主要参考文档：

| 证据编号 | 文档 | 用途 |
| --- | --- | --- |
| DOC-GDD-001 | `docs/planning/game-design-doc-v0.1.md` | 业务目标、系统边界与阶段规划 |
| DOC-PROTO-001 | `docs/protocols/ue-protocol-contract-v0.1.md` | v0.1 命令和语音契约 |
| DOC-PROTO-002 | `docs/protocols/combat-tactical-protocol-v0.2.md` | v0.2 战斗上下文、决策、事件和回执契约 |
| DOC-UE-001 | `docs/protocols/ue-integration-guide-v0.1.md` | UE 接入步骤与验收项 |
| DOC-README-001 | `README.md` | 后端模块和端点总览 |

这些相对路径均以
`C:/Users/YYchainsaw/PycharmProjects/aesir-ai-service/` 为根目录。

## 3. 当前已确认的 UE → Python 接口

通过 Unreal C++ 源码已经确认以下调用：

| UE 调用方 | HTTP 路径 | 当前状态 |
| --- | --- | --- |
| `UCommandServiceSubsystem` | `GET /health` | C++ 已实现 |
| `UCommandServiceSubsystem` | `POST /v1/commands/parse` | C++ 已实现 |
| `UCommandServiceSubsystem` | `POST /v1/voice/command` | C++ 已实现 |
| `UCommandServiceSubsystem` | `POST /v1/tactical/resolve` | C++ 已实现 |
| `UCompanionChatSubsystem` | `POST /v1/companion/chat` | C++ 已实现 |

以下接口在 Python 服务存在，但尚不能仅凭当前 UE C++ 认定已经完成 UE 接入：

| HTTP 路径 | Python 状态 | UE 状态 |
| --- | --- | --- |
| `POST /v1/tactical/command` | 已实现 | 待蓝图/C++ 证据 |
| `POST /v1/tactical/executions` | 已实现 | 待蓝图/C++ 证据 |
| `POST /v1/combat/events` | 已实现 | 待蓝图/C++ 证据 |
| `POST /v1/speech/transcribe` | 已实现 | 待蓝图/C++ 证据 |

## 4. 已知差异和待决项

| 编号 | 现象 | 当前处理 |
| --- | --- | --- |
| GAP-001 | Python 文档默认监听 `127.0.0.1:8000`，`UCompanionChatSubsystem` 固定使用端口 `8001` | As-Is 部署图分别展示，联调前确认实际启动方式 |
| GAP-002 | `UCommandServiceSubsystem` 固定使用端口 `8011`，与 Python 文档默认端口不同 | As-Is 部署图分别展示，联调前确认实际启动方式 |
| GAP-003 | Python README 标注运行时 Python 3.12，当前项目虚拟环境为 Python 3.11.9 | 基线记录实际环境，不擅自修改运行要求 |
| GAP-004 | 后端功能范围大于当前可由 UE C++ 证明的接入范围 | 未接入部分不画入 As-Is 闭环，等待蓝图证据 |
| GAP-005 | `.uasset` 为二进制，文件名无法证明 Event Graph、节点和连线 | 使用 Unreal Editor 导出器采集 Graph/Node/Pin 证据 |

## 5. PlantUML 文件约定

- 仓库只维护 `docs/design/uml/src/*.puml` 源文件。
- SVG/PNG 的预览与导出不属于本仓库 UML 编写流程。
- `.puml` 应保持自包含，不依赖在线主题或远程 include。

## 6. 基线变更规则

- UML 源文件只描述本文件记录的提交状态。
- 任一仓库更新后，先重新导出证据并查看差异，再更新 UML。
- 设计目标必须使用 `to-be` 文件名；当前实现必须使用 `as-is` 文件名。
- 发现文档与实现冲突时，在本文件登记 `GAP-*`，不静默选择其中一方。
