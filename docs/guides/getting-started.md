# 本机启动与检查

> 2026-10-19按`a2dd426`校对；当前默认NPC端口8011。本页集中启动、依赖与常见操作，字段见[当前契约](../protocols/npc-contract-v0.3.md)，需求见[SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)。

## 第一次准备

当前开发环境为Windows、Python3.12。以下在仓库根目录用PowerShell执行，无需先激活虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m pip install -r requirements.txt
```

开发测试另外安装requirements-dev.txt；需要真实本机语音才安装requirements-ml.txt。版本以这些清单为准，不在本页重复维护依赖版本表。

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
# 按需：真实语音识别
.\.venv\Scripts\python -m pip install -r requirements-ml.txt
```

如果要激活环境，可用`.\.venv\Scripts\Activate.ps1`；受当前进程执行策略限制时可不激活，继续使用上述解释器绝对入口。默认rule解析、mock对话和mock语音不要求LLM密钥；mock语音文本默认空，演示需显式设置AESIR_ASR_MOCK_TEXT。

## 启动与检查地址

```powershell
.\.venv\Scripts\python -m scripts.run_server --reload
curl.exe http://127.0.0.1:8011/health
```

run_server读取AESIR_SERVICE_HOST/AESIR_SERVICE_PORT，默认127.0.0.1:8011；指定其他端口时调用方也同步改地址：

```powershell
.\.venv\Scripts\python -m scripts.run_server --port 8002 --reload
curl.exe http://127.0.0.1:8002/health
```

`--reload`用于开发代码重载，不保证修改.env自动生效。config在导入时加载.env，get_settings重读进程环境；修改.env后重启服务。策略YAML/人格注册表等另有缓存或加载生命周期，不宣传全系统热更新。

`/health`返回status、service、protocol_version和service_commit；当前health版本为0.1，端点仍分别用0.1/0.2/0.3。commit识别运行实例，非Git分发可为unknown。UE两个NPC Subsystem使用同一个8011地址；Boss RL另起8012实例，见[RL入口](../../rl/README.md)。

根目录`start.bat`可作为启动包装；终端对话用`start.bat chat`或以下脚本。端口冲突先确认占用，不要只改一端后把404/拒连误判为协议错误。

## 按游戏启动独立实例

进程默认AESIR_GAME_ID=aesir，加载该游戏能力档案及注册人格。第二游戏在另一个进程与端口启动：

```powershell
$env:AESIR_GAME_ID = 'demo-vn'
.\.venv\Scripts\python -m scripts.run_server --port 8002
```

回到Aesir实例前使用独立终端或恢复AESIR_GAME_ID=aesir。人格包格式见[schema](../protocols/persona-pack-schema-v0.2.md)。一进程一游戏是部署约束，不代表旧parse/voice、v0.2战术和回执已全面实现逐角色/当前游戏绑定；实际差距见[NPC契约](../protocols/npc-contract-v0.3.md#7-当前实现差距)。

## 先走哪条调用

| 目的 | 命令或入口 |
| --- | --- |
| 检查人格、关系、记忆 | `.\.venv\Scripts\python -m scripts.chat_console`；或注册角色的console/state、console/memory |
| 文本闲聊 | companion/chat；语音闲聊为companion/chat/voice，不能误用voice/command |
| 战斗命令/旧订单 | tactical/command或commands/parse；显式提供当前角色、目标和能力目录 |
| 非战斗文本/心跳 | agent/step带text/不传text；action为none或directive |
| 事实事件与反馈 | world/events；UE实际结果到tactical/executions，202不表示完成 |
| 按顺序接UE | [联调指南](../protocols/integration-alignment-v0.3.md) |
| 切换真实LLM/ASR | [LLM和数据流](llm-integration.md)；本机ASR配置见下节 |

一个最小文本对话示例（PowerShell用结构化JSON，不在单引号内转义双引号）：

```powershell
$chatBody = @{text='你好，艾莉'; companion_id='companion.alice'; game_state='conversation'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8011/v1/companion/chat' -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($chatBody))
```

这是会产生正常记忆/信号副作用的请求。不传session_id只是不维护短期窗口，仍可读取/写入长期数据；默认信号尝试存完整输入和回复，显著声明可能逐字入档案。reset仅清目标会话和长期记忆，保留人格/关系及信号日志；持久失败可能会话已清，不承诺回滚。

## 语音和外部后端

ASR默认mock；真实识别用AESIR_ASR_BACKEND=faster_whisper，另按本机能力配置AESIR_ASR_MODEL/DEVICE/COMPUTE_TYPE/LANGUAGE。首次下载模型可能联网，运行需已有模型和依赖，不能把mock通过当真实语音已验收。

传输约定16kHz/单声道/16-bit PCM WAV。命令上传字段为file、context_json；闲聊与纯转写字段为audio。当前没有统一大小/时长/WAV头门禁，失败按实际响应处理，保留文本入口。不要在教程或测试记录中放密钥、私人对话和未脱敏音频。

## 检查与结果记录

```powershell
# 安装开发依赖后按改动运行适用测试；先阅读测试及conftest的隔离约定
.\.venv\Scripts\python -m pytest
# 需先起服务：演示会调用API并可能写正常运行数据
.\.venv\Scripts\python -m scripts.command_service.mock_ue_flow
```

本页本轮未执行上述命令。历史669通过/2跳过等数字属于当时提交，不承诺当前总数；真实ASR、LLM、UE执行、Windows包和正式P95均需各自记录。metrics_report的覆盖代理不自动等于需求验收通过，详见[复现与验收](repro.md)。

常见问题：401/模型不可用检查配置并重启；缺faster-whisper仅安装所需语音依赖；端口不通核对run_server实际打印地址与UE配置；PowerShell别名curl导致参数错误时使用curl.exe或Invoke-RestMethod。完整字段不要在本页另建一套，回到对应契约查。
