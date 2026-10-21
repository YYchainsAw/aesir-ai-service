# Aesir AI Service

AesirWarden 的 Python 配套服务。NPC 服务负责对话、记忆、关系、语音转写、行为建议和回执采集；Boss RL 在独立进程中训练和推理。UE 始终负责世界状态、技能合法性、实际执行和结果结算。

2026-10-21已采纳正式目标：Boss冻结推理随游戏在本地运行，NPC通过远程HTTPS服务提供能力，补玩家/存档隔离、权威存储与缓存同步、外部ASR转接和模型版本发布。当前仍是单worker开发实现；v0.4已有作用域与生命周期子集，正式账号、数据库事务/同步和外部ASR另行实施。新增部署要求和验收见[部署指南](docs/guides/deployment.md)，不表示现代码可直接公网开放。

## 开发环境启动 NPC 服务

需要 Python 3.12+。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m scripts.run_server --reload
```

默认地址为 `http://127.0.0.1:8011`。打开 `/health` 检查运行提交，打开 `/docs` 查询当前接口。`scripts.run_server` 读取 `AESIR_SERVICE_HOST` / `AESIR_SERVICE_PORT`；直接运行未指定端口的 Uvicorn 会使用其自己的默认端口。修改 `.env` 或策略后重启服务。

新版JSON入口默认要求可信身份，旧协议默认关闭。单机/环回开发的固定身份、旧协议兼容开关及调用顺序见[v0.4开发与交接](docs/guides/scoped-development.md)；不以客户端自报player_id代替身份。

规则和 mock 模式不需要云端模型；启用 LLM 时会向配置后端发送文本及生成所需上下文。真实 ASR 需要可选依赖。安装、后端配置、数据流和复现步骤见下面的指南，不能由“服务在本机运行”推断没有外部调用。

## 从哪里看

| 我现在要做什么 | 入口 |
| --- | --- |
| 安装、启动、切换游戏实例或排查配置 | [启动指南](docs/guides/getting-started.md) |
| 判断每项 AI 能力在本地还是服务器、核对原计划 | [15 项部署分工对照](docs/planning/ai-capability-placement.md) |
| 远程开发、Boss 本地与队友云端的推进顺序 | [六步开发方案](docs/planning/local-boss-cloud-companion-roadmap.md) · [远程开发指南](docs/guides/remote-development.md) |
| 审查第二步身份、作用域与有效期设计 | [第二步实施计划](docs/planning/step-02-identity-scope-plan.md) · [v0.4契约草案](docs/protocols/npc-scope-contract-v0.4-draft.md)（分支实现及服务端回归通过，UE待验） |
| 正式部署、玩家隔离、缓存同步、ASR及模型分发 | [部署指南](docs/guides/deployment.md) |
| 查运行版本、mock／LLM／fallback及样例 | [联调复现](docs/guides/repro.md) |
| 配置LLM、了解数据外发和保留范围 | [LLM与数据流](docs/guides/llm-integration.md) |
| 从UE选择正确端点、对齐ID和验收 | [两端接入对齐](docs/protocols/integration-alignment-v0.3.md) |
| 查接口和人格包字段 | [文档索引](docs/README.md)的契约入口 |
| 查当前需求、规则、异常和对象职责 | [NPC需求主文](docs/planning/aesir-agent-sdd-v1.1.md) |
| 查看课程模型与draw.io图源 | [UML索引](docs/design/uml/README.md) · [课程索引](docs/planning/course-requirements-index.md) |
| 继续开发或核对已知实现差距 | [未决事项与跨仓依赖](docs/planning/todo.md) |
| 实施已采纳的对话/语音/Agent/记忆/云端演进 | [交互演进计划](docs/planning/npc-interaction-evolution.md)，含UC映射、批次与新增验收 |
| 训练或运行Boss PPO | [Boss RL说明](rl/README.md) |
| 查真实联调和历史里程碑 | [验证记录](docs/logs/verification-records.md) · [CHANGELOG](CHANGELOG.md) |

## 服务边界与端口

| 服务 | 默认端口 | 职责 |
| --- | --- | --- |
| `app.main:app`，由 `scripts.run_server` 启动 | 8011 | NPC对话/指令/快照/事件/调试与回执 |
| `rl.boss.inference_app`，由 `scripts/rl/boss/serve.py` 启动 | 8012 | schema v4、26维观测、9动作的冻结Boss策略推理 |

`app` 不导入 `rl`，NPC服务可在未安装Gymnasium、SB3或Torch时运行。Boss HTTP推理已存在；UE运行接入、故障回退修复和正式BT/PPO对照分别验收。模型不随Git克隆分发，获取和身份核对见RL说明。

新版scoped JSON使用v0.4，旧协议v0.1、v0.2、v0.3仅在显式legacy开发模式按端点并存；`/health`的版本字段不代表所有端点都使用同一版本。当前主入口`action`只有`none`和`directive`。服务返回建议不表示UE已经启动或完成动作，回执当前只追加记录。

## 检查改动

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py -q
```

上述为无需 ML/RL 依赖的核心回归；完整 RL 环境/推理测试需要另装对应可选依赖，Linux 命令与跳过边界见[远程开发指南](docs/guides/remote-development.md)。测试数应标注实际提交和环境；历史结果见验证记录。本次文档和模型整理不代表重新运行了服务、UE、ASR、LLM或研究实验。指标脚本的采集/覆盖结果也不能替代正式需求验收。

日常任务只维护一个状态来源，文档保留规则、依赖与验收定义。修改接口字段时同步schema、契约与golden样例；修改业务规则时同步需求、图和追踪，未决定的技能数量或跨端阶段协议继续列为未决。
