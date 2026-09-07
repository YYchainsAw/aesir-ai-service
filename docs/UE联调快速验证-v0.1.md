# UE 联调快速验证清单（契约 v0.1）

> 目标：UE 侧用最短路径把 v0.1 语音链路跑通。完整规范见
> `UE5_模型服务联调技术规范_v0.1.md`，本文只做分步操作清单。
> 更新日期：2026-09-07

## 0. 前置

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

- mock 阶段**不需要**装 faster-whisper，不需要 .env。
- 全程只依赖本机，无外网调用。

## 1. 第一步：纯文本（先不碰音频）

`POST /v1/commands/parse`，验证 JSON 契约、`request_id` 回显、5 条指令的
`TacticalOrder` 结构。请求体模板直接抄 `docs/启动说明.md` §5.2。

验收：5 条指令各返回正确 `intent`；未识别文本返回 `recognized:false` +
`order:null`（UE 安全忽略路径）。

## 2. 第二步：mock 语音（打通上传链路）

`.env` 或环境变量（也可不设，mock 为默认）：

```powershell
$env:AESIR_ASR_MOCK_TEXT = "艾莉，撤退并优先保命"
```

UE 上传任意 WAV（16kHz/单声道/16bit，内容不重要）到：

- 组合端点：`POST /v1/voice/command`（multipart `file` + 可选 `request_id`）
  → 一次返回 `ParseCommandResponse`。
- 两步式：`POST /v1/speech/transcribe`（multipart `audio` + 可选 `request_id`）
  → `{request_id, text, language}`，再拿 `text` 调 `/v1/commands/parse`。

验收：multipart 编码正确、`request_id` 回显、错误分支（422/502）有 HUD 提示。
建议 UE 侧 Audio Capture + WAV 编码在本步一并调通（内容随意，格式必须对）。

## 3. 第三步：切换真实 ASR

```powershell
.\.venv\Scripts\python -m pip install -r requirements-ml.txt
$env:HF_ENDPOINT = "https://hf-mirror.com"      # 首次下载模型
$env:AESIR_ASR_BACKEND = "faster_whisper"
```

用真人录音（「艾莉，撤退并优先保命」等）替换 mock 文本验证。转写质量调优见
`scripts/asr_eval.py`（样本放 `data/asr_samples/`，文件名即期望文本）。

验收：一句指令端到端 < 3s（`small` 模型本机约 0.5s）；识别错句时确认走
`recognized:false` 而非报错。

## 4. 逐项测试清单

按阶段（P2 文本 → P3 战斗闭环 → P4 语音）的 21 条验收测试项见
`UE侧接入测试清单-v0.1.md`，含每项的验证内容与勾选栏。

## 4. 错误处理对照（UE 必须实现）

| 情况 | 服务返回 | UE 行为 |
| --- | --- | --- |
| 未识别（空转写/未知文本） | 200, `recognized:false` | 显示 message，不执行 |
| request_id 非法 | 422 | 客户端 bug，修 UE |
| ASR/LLM 故障 | 502/503 | 本地降级提示 |
| 超时（建议 3s） | — | UE 本地取消，维持原 AI |
