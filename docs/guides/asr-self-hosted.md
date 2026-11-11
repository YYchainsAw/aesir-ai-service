# 答辩版自部署语音识别

2026-11-11 确认：本轮“真实外部 ASR”允许采用服务器自部署开源模型，通过 HTTP 向 UE 提供真实转写；不强制购买第三方语音接口。文本、指令、真实语音仍全部必交。

首选复用现有 faster-whisper 与 `small` 权重，先在已有机器上以 CPU/int8 验证；不新增 GPU 服务器。此方案无需第三方 ASR API Key，仍有现有机器的算力、存储与部署成本。实际延迟应记录音频长度、设备、模型和是否已加载，不能用一次样例宣称达到 p95 指标。

参考：[faster-whisper 官方仓库](https://github.com/SYSTRAN/faster-whisper)。

## 本机配置

在私有 `.env` 中设置：

```dotenv
AESIR_ASR_BACKEND=faster_whisper
AESIR_ASR_MODEL=small
AESIR_ASR_DEVICE=cpu
AESIR_ASR_COMPUTE_TYPE=int8
AESIR_ASR_LANGUAGE=zh
AESIR_ASR_MAX_AUDIO_BYTES=2097152
AESIR_ASR_MAX_AUDIO_SECONDS=30
```

`AESIR_ASR_MODEL` 也可填写完整本地模型目录，从而避免首次运行联网下载。本机已配置为现有缓存快照目录；该绝对路径不适用于另一台服务器。远程部署时应在目标机器预置同一模型，并记录模型来源及快照版本。

语音可选依赖见 `requirements-ml.txt`；核心 API 不要求加载语音模型。本地单进程 JSON 开发配置还需 `AESIR_COORDINATION_BACKEND=memory`。生产身份、SQL、Redis 和 HTTPS 按发布方案单独配置，不能将开发配置直接当作生产发布。

## 先验证真实转写

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.asr_smoke --audio "你的录音.wav"
```

脚本拒绝用 mock 作为真实验收，输出所用 backend、转写文字和处理耗时。首次加载模型的耗时包含在内。测试音频仅在内存中交给识别器，脚本不额外保存音频或转写文件。

本次使用 [SenseVoiceSmall 官方中文样例](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/tree/main/example)，将 MP3 转为 16 kHz、单声道、16-bit PCM WAV 后验证。它用于证明真实模型与 HTTP 转写链路，不代表 UE 麦克风录音已验收。

## UE 接入

1. 先获取 scoped context 并显式 bind，使用当前 save、run、binding 和 epoch。
2. 向 `POST /v1/scoped/companion/chat/voice` 上传 multipart 表单；音频字段为 `audio`，其余字段见 [UE 适配说明](ue-service-adaptation.md)。
3. 当前语音入口是 **v0.4 同步**，响应同时包含 `transcribed_text` 与 NPC 回复。超时预算必须覆盖 ASR 和后续生成，不沿用旧端点的 3～5 秒预算。
4. 相同逻辑请求重试复用 request_id 和原音频。服务端用音频 SHA-256 参与幂等校验；换音频必须换 request_id。
5. `ASR_EMPTY` 提示未听清；`ASR_UNAVAILABLE` 提供文本输入；过期绑定先重新获取上下文。不要自动重放旧局录音。

服务端先检查绑定、epoch 和请求去重，再执行 ASR。同 ID 成功或确定失败的重放不会再次识别。同一 ID 更换音频返回冲突。

上传字节数默认上限为 2 MiB，时长默认上限为 30 秒。faster-whisper 和豆包适配均在推理前校验完整的 16 kHz、单声道、16-bit PCM WAV；其他编码需由客户端先转换，避免用文件扩展名冒充格式。

## 保留的商业接口备选

`AESIR_ASR_BACKEND=volcengine` 可选择豆包录音文件极速版；只有启用该后端才需要语音 API Key 和 `volc.bigasr.auc_turbo` 权限。它不会复用 LLM/Coding Plan Key，也不会在失败后静默返回 mock 转写。

配置 `AESIR_ASR_VOLC_API_KEY_FILE` 可从私有纯文本文件读取 Key，优先于 `AESIR_ASR_VOLC_API_KEY`。缺少凭据时发布预检阻止通过。本轮未对商业后端做真实调用验收。

官方协议：[豆包录音文件极速版识别 HTTP](https://docs.volcengine.com/docs/doubao-voice/large-model-recording-file-lite-recognition-api?lang=zh)。

## 本次验证边界

本机真实模型转写和 scoped HTTP 上传已验证；下游 NPC 回复使用 mock 隔离测试。真实 LLM 当前返回 `InvalidSubscription`，需要恢复可用凭据后补整条链路。服务器部署、真实 UE 录音上传、断网切文本以及 Windows 游戏包仍分别待验。
