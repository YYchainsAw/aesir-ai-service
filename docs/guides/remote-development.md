# 服务器远程开发指南

本指南对应[六步开发方案](../planning/local-boss-cloud-companion-roadmap.md)的第一步。Python 开发工作区为 `/www/wwwroot/aesir-ai-service`；本地 Boss 发行与队友公网正式发布分别在第五、六步验收。

## 环境与依赖

- 系统 `/usr/bin/python3` 保持原样，不作为本项目解释器。
- 项目解释器：`/www/wwwroot/aesir-ai-service/.venv/bin/python`，本次固定为 Python 3.12.15；根目录 `.python-version` 是服务器工作区本地设置，未纳入本次文档提交。重建命令显式指定版本。
- 本机使用已安装的 `/root/.local/bin/uv` 管理独立 Python；不依赖 shell 的激活状态。
- `requirements.txt` 为 NPC 核心运行依赖，`requirements-dev.txt` 增加现有测试依赖。
- 服务器工作区的 `requirements-dev-linux-py312.lock` 固定本轮 Linux/Python 3.12 核心开发依赖及传递依赖的版本和分发文件哈希。本次只提交文档，该锁文件仍留在服务器工作区；首次克隆须先从 `requirements-dev.txt` 安装，再按下节命令生成锁。它不覆盖 Windows、本地 Boss、真实 ASR 或 RL 训练。
- `requirements-ml.txt` 与 `requirements-rl.txt` 仍是可选用途清单；第一步不把语音模型或训练运行库装进核心开发环境。Boss 最小发行依赖在第五步按真实导入清单单独确定。

在干净环境重建（已有 `.venv` 时先确认用途，不直接覆盖）：

```bash
cd /www/wwwroot/aesir-ai-service
/root/.local/bin/uv python install 3.12.15 --no-bin
/root/.local/bin/uv venv --python 3.12.15 --seed .venv
if test -f requirements-dev-linux-py312.lock; then
    /root/.local/bin/uv pip install --python .venv/bin/python --require-hashes -r requirements-dev-linux-py312.lock
else
    /root/.local/bin/uv pip install --python .venv/bin/python -r requirements-dev.txt
fi
/root/.local/bin/uv pip install --python .venv/bin/python --no-deps -e .
.venv/bin/python --version
.venv/bin/python -m pip check
```

首次克隆或明确更新依赖时生成锁文件，并复跑核心测试。无既有锁文件的首次解析只固定清单中的直接依赖，不能据此保证传递依赖与本轮记录完全相同：

```bash
/root/.local/bin/uv pip compile requirements-dev.txt --python .venv/bin/python --generate-hashes --output-file requirements-dev-linux-py312.lock
```

## PyCharm 远程解释器

在远程项目选择现有解释器 `/www/wwwroot/aesir-ai-service/.venv/bin/python`，工作目录设置为 `/www/wwwroot/aesir-ai-service`。IDE SDK 登记、磁盘上存在解释器、IDE 实际执行成功分别核对；仅连接 SSH 或打开项目不表示依赖已安装。

开发运行配置使用模块 `scripts.run_server`，参数为 `--host 127.0.0.1 --port 18011 --reload`。终端可直接运行下述同一命令。`.idea` 为机器配置，不进入 Git。

## 开发配置与启动

本轮 `.env` 为不入 Git 的规则/mock 开发配置，文件权限限制为当前用户；密钥不在文档或日志展示。监听 `127.0.0.1:18011`，与后续正式实例隔离。记忆、关系、回执和信号写入 `data/runtime/remote-dev/` 下各自目录，不与正式实例共用。

重建开发配置时，在不存在 `.env` 的工作区新建下列内容；已有配置只合并需要的项，保留原有密钥。创建后执行 `chmod 600 .env`。

```dotenv
AESIR_SERVICE_HOST=127.0.0.1
AESIR_SERVICE_PORT=18011
AESIR_GAME_ID=aesir
AESIR_PARSER_BACKEND=rule
AESIR_COMPANION_BACKEND=mock
AESIR_ASR_BACKEND=mock
AESIR_INTENT_BACKEND=rule
AESIR_TACTICAL_POLICY=rule
AESIR_MEMORY_ROOT=data/runtime/remote-dev/memory
AESIR_RELATIONSHIP_ROOT=data/runtime/remote-dev/relationship
AESIR_RECEIPTS_DIR=data/runtime/remote-dev/executions
AESIR_DIALOGUE_SIGNALS_DIR=data/runtime/remote-dev/dialogue-signals
AESIR_AGENT_STEPS_DIR=data/runtime/remote-dev/agent-steps
AESIR_EVENT_SIGNALS_DIR=data/runtime/remote-dev/event-signals
```

```bash
cd /www/wwwroot/aesir-ai-service
.venv/bin/python -m scripts.run_server --host 127.0.0.1 --port 18011 --reload
```

停止前台开发实例使用 Ctrl+C。命令用于按需开发，不是生产进程守护。开发默认后端为 parser/intent `rule`、companion/ASR `mock`；这只能验证规则与模拟链路，不证明真实 LLM 或语音质量。

本轮已在后台启动同样的开发实例，父进程 PID 写在 `data/runtime/remote-dev/service.pid`，日志在 `data/runtime/remote-dev/service.log`。重新运行前先确认该端口的实例；需要停止时，先用 `ps -p <PID> -o pid,args` 核对它仍是本项目开发进程，再以 `kill -INT <PID>` 停止。此进程无开机自启，不属于正式发布。

在服务器另一个终端检查：

```bash
curl --fail-with-body http://127.0.0.1:18011/health
curl --fail-with-body http://127.0.0.1:18011/openapi.json
curl --fail-with-body -H 'Content-Type: application/json' -d '{"text":"hello","companion_id":"companion.alice","game_state":"exploration","session_id":"remote-dev-smoke"}' http://127.0.0.1:18011/v1/companion/chat
```

`/health.service_commit` 是代码提交，不包含未提交改动；`/health.protocol_version` 不代表所有接口都使用相同版本。当前 `/v1/agent/step` 仍按其自己的 v0.3 契约检查。

## 从 Windows UE 访问开发服务

使用 SSH 转发访问仅回环监听的开发接口。保留下面命令所在终端；本地 8011 已被占用时先确认占用程序，不覆盖其他实例。

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8011:127.0.0.1:18011 baota-server
```

随后 Windows 的 `http://127.0.0.1:8011/health` 转发到服务器开发实例。UE 当前 NPC 默认地址也是 `127.0.0.1:8011`；Boss 本地 `127.0.0.1:8012` 保持独立用途。验证 Windows HTTP 转发不等于已在 UE 中完成实际行为验收。

正式 HTTPS、公网认证、用户隔离、守护进程和发布回滚按方案后续步骤实现。本轮不将无入站认证的开发 API 暴露公网。

## 核心回归

无需额外 ML/RL 依赖的现有回归入口：

```bash
cd /www/wwwroot/aesir-ai-service
.venv/bin/python -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py -q
```

该范围包括 API、服务、Schema、脚本及纯 Python Boss 契约。`tests/rl/boss/test_inference.py` 顶层导入 NumPy；环境/推理测试需要相应 RL 依赖，因此不以无可选依赖时直接全量 pytest 作为核心环境验收。真实 faster-whisper 测试可能因缺可选依赖跳过，必须在结果中说明。不要把跳过、未执行或 Mock 通过写成真实模型通过。

## 本轮验证记录

2026-10-21，在 Ubuntu 22.04 x86_64 上，基于代码提交 `e4e20f7` 加服务器工作区改动验证。随后按用户要求单独提交文档；环境配置、锁文件和下述测试修正未纳入文档提交。本环境不登记为正式上线。

| 检查 | 实际结果与范围 |
| --- | --- |
| 项目环境 | uv 0.13.1、CPython 3.12.15、独立 `.venv`；系统 Python 3.10.12 保留 |
| 核心安装 | 锁文件 30 个核心/开发分发包及项目 editable 安装；FastAPI 0.141.1、Uvicorn 0.52.4、pytest 9.1.1；`pip check` 与锁文件审计通过 |
| 核心回归 | 上述核心命令：839 passed、1 skipped、7 warnings，pytest 报告 22.37 秒；跳过为缺少可选 faster-whisper 的模块收集，RL 环境/推理测试不在本次范围 |
| 首轮发现与修正 | 原用例在创建阻塞文件后调用 `load()`，Linux 提前触发 `NotADirectoryError`；将阻塞操作移到空存储加载之后，继续检查真实写入抛 `MemoryStoreError`。只改 `tests/services/test_memory_degradation.py` 的准备顺序，未改业务存储逻辑；随后核心回归通过。测试修正保留在服务器工作区，未纳入文档提交；未经此修正的基线在 Linux 仍可能触发该已知失败 |
| 依赖提示 | 7 条为 Starlette 的 httpx TestClient、旧 422 常量弃用提示；本轮没有为消除提示而调整项目既有直接依赖 |
| 服务与健康检查 | 仅监听 `127.0.0.1:18011`；`GET /health` 为 200、status=ok、commit=e4e20f7；`GET /openapi.json` 为 200，含 18 个路径 |
| Mock 对话 | `POST /v1/companion/chat` 为 200、source=mock，返回非空回复 |
| 规则指令 | `POST /v1/agent/step` 为 200，文本检查篝火生成 exploration/inspect 指令、source=rule，目标和请求 ID 匹配；这不是 UE 已执行的证据 |
| 配置隔离 | `.env` 权限 0600；`.env`、`.venv`、开发运行数据经 `git check-ignore` 确认为忽略项；未配置外部 LLM 密钥、未安装 ML/RL 可选包 |
| PyCharm | 远端 SDK 登记与项目模块文件已出现本项目 `.venv`，SDK 版本为 3.12.15；Codex 的 IDE MCP 当前未连通，未在 IDE 内实际点击运行/调试验收 |
| Windows/UE | 自动审批拒绝了创建 Windows 本地后台 SSH 转发进程，未提供具体原因；本轮未建立该转发，也未执行 UE 实际联调。上节保留了可在终端运行的命令 |

原始验证文件只保留在忽略目录 `data/runtime/remote-dev/verification/`：`core-pytest.log`、`core-pytest.xml`、`core-pytest-result.json`、`http-smoke.json`。锁文件 SHA-256：`c997515318669c786ca8b1351f41300a2c00a34024480f27918c9c2fce7b2d33`。

第一步的服务器环境、核心回归与本机 HTTP 检查已落实。IDE 内运行和通过 SSH 转发的 UE 实际请求仍待验；上述结果不代表真实 LLM/ASR、Boss Windows 发行、身份隔离、数据库或公网生产部署已经完成。
