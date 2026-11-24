# 联调准备、刷新修复、阶段观测与日志治理

后续：同日官方验证已完成，引擎实际更新到 5.8.4，构建和 7 项队友原生测试通过；[最新验证](_13_ue_native_verification.md)。以下引擎缺项与等待状态保留为修复前记录。

2026-11-24，按用户要求刷新 UE 仓库并推进独立服务端改进。UE 原 `E:\AesirWarden` 存在本地提交与未提交修改，因此只 fetch，没有 pull/merge、重置、清理或覆盖。通过既有本机代理 fetch 成功，`origin/main` 仍为 `af5510f7c1a5244b0714893483a9475cab236bdb`；已有隔离源码副本 `.workbuddy/ue` 就是该版本。原工程的 uproject、DefaultEngine.ini、CommandServiceSubsystem.cpp 等改动保留。

本轮只读复核确认引擎的 CoreUObject UHT 生成文件仍不完整，也未找到 Intermediate 开发链接库。Epic Launcher 已安装，但安装登记文件为空；用户确认 Launcher 库能识别 UE 5.8.3，正在运行官方“验证”。桌面/浏览器连接三次恢复后仍报 `Computer Use native pipe is unavailable`，未自动操作安装、认证、删除或重装引擎。验证完成前不编译，避免与官方校验同时写文件。UE 编译、原生测试与完整地图/GAS/回执仍待验证结束后继续，不记录为通过。

## 同轮后续：独立源码与安装清单校验

用户随后要求由助手独立验证。未检测到 Epic Launcher/BuildPatchTool/编辑器活动进程后，对最新隔离副本执行真实构建，仍 Exit 6：SharedPCH 在 `PrimaryAssetId.h:16` 缺 `PrimaryAssetId.generated.h`。构建日志位于 `data/runtime/ue24/build-latest.log`；未生成最新 DLL，未运行原生/地图测试。

- 原 `E:\AesirWarden` HEAD 是 `06f2415`，相对最新远端多 1 个提交、落后 44 个提交；Source/Config/uproject 与远端有 70 个文件差异。未覆盖原修改或把原目录改称最新。
- 隔离副本 HEAD 为 `af5510f`，131 个被跟踪的 Source/Config 文件与该提交没有 Git 差异，uproject 也未修改。
- 从 Epic 安装条目的安全字段确认版本为 `5.8.3-58210709+++UE5+Release-5.8-Windows`、路径为 `D:\UE_5.8`。官方 BuildPatchTool `ExtractMetaData` 只读解析本机 manifest 后，按清单对必需、无可选标签的 `Engine/Intermediate/Build/Win64/` 文件检查存在性和大小：11722 个文件，只有 4 个大小相符、11718 个缺失，缺失内容合计 2296098396 字节。不是全引擎 SHA 校验或下载量估计；其余平台和目录未由这个数字覆盖。[结果与关键文件预期哈希](data/ue-environment-20261124.json)。
- `PrimaryAssetId.generated.h` 及 `UnrealEditor-CoreUObject.lib` 均为官方清单中的基本文件，不是项目源码、可选调试符号或未制作的游戏资产。
- 本机官方工具的 InstallManifest 模式支持文件重建，但须有 manifest 对应的 CloudDirs/分块来源；当前本地 Pending 没有可用分块。没有猜测下载地址、提取登录凭据、删除引擎或执行可能安装所有平台的大体积命令。

剩余前置：通过 Launcher 的 5.8.3 下拉菜单“验证”补回文件，或提供相同版本/CL 的完整安装包/备份本机路径。桌面连接不可用时不能代操作 Launcher；来源齐备后可以继续命令行核对、构建与项目修复。此核查独立完成，但不等于引擎已经修复或 UE 完整闭环完成。

## 已交付的服务端修改

- 调试台 loading 状态移到 main 外，连续渲染不再删掉状态节点；同角色进行中的刷新合并，角色切换后的旧响应不能覆盖新角色，失败后可重新刷新。三个 Node 原生测试直接执行页面脚本，覆盖 DOM 替换、请求乱序、合并和失败恢复。真实浏览器因连接故障未运行，不能把 DOM 替身当成浏览器/UE 实测。
- scoped 请求的诊断链增加 `memory_retrieval` 阶段、候选条目/印象数、提供方 usage 白名单。流式客户端记录模型首个内容片段耗时和流结束/中断耗时；首内容是原始模型内容，不等于首次可见回复、音频或 UE 表现。同步完整模型调用沿用已有 upstream 尝试起止耗时。未采集的 UE 阶段仍未知；不增加不存在的执行枚举或把 accepted 当完成。
- 对话信号默认 `AESIR_DIALOGUE_SIGNAL_TEXT_MODE=metadata`，保留来源、scope/请求关联、质量统计和原因，移除输入、回复、注入主题原文及风格违规命中原文/消息。metadata 仍含关联标识，不是匿名化。原文人工评估需在独立采集实例显式选择 full；种子脚本自动选择 seed+full，退出恢复环境。私有 `.env` 未改，若此前显式设置 full 则仍按 full 工作。
- 轮转阈值 `AESIR_DIALOGUE_SIGNAL_MAX_BYTES` 默认 10 MiB。追加前超限则将旧文件改名为带 UTC/随机 ID 的 archive，继续写活动文件；一行本身可能超阈值，不截断 JSON。轮转锁限单进程，不能据此宣称多 worker 文件轮转已验证。
- 清理工具默认 dry-run，只处理所给根目录下严格匹配的 `companion.*.archive-时间-随机ID.jsonl`，按文件最后修改时间筛选；跳过符号链接、活动文件及其他账本。应用清理需显式 `--apply`。没有自动删除、重写或脱敏历史原文，也不操作记忆、SQL、执行确认、请求 journal 或备份。

metadata 记录不能充作可人工核对的对话文本：自然数据审计新增可用原文数量；风格报告单列原文缺失数，以可核对原文轮数而非总行数判断文本回归门槛，不把缺失原文当“无漏网”。保留旧数据兼容字段和训练未批准边界。

## 运维示例

```powershell
$env:AESIR_DIALOGUE_SIGNAL_TEXT_MODE='metadata'
$env:AESIR_DIALOGUE_SIGNAL_MAX_BYTES='10485760'
# 先检查归档数量与字节，不打印原文、不删除文件。
.\.venv\Scripts\python.exe -B -m scripts.prune_dialogue_signals --root data/runtime/dialogue_signals --older-than-days 30
# 核对保留策略、目标目录及所需备份后，操作者可另行添加 --apply。
```

本机实际仅运行 dry-run：候选 0、删除 0。历史活动文件即使很旧也不会由此工具直接删除；需明确原文保留策略后另行安排归档治理。30 天仅为 CLI 默认参数，不是已批准的项目数据保留政策。

## 验证与边界

核心回归 **1754 passed、13 skipped、7 warnings，110.77 秒**；随后补充风格审查原文覆盖率门槛的针对性回归 **13 passed**。调试台脚本 **3 passed**。覆盖日志文本/主题/违规片段去除、完整归档保留、dry-run 与受控测试归档清理、请求关联、模型 usage 白名单与首内容单次观测。测试中的删除仅针对隔离临时归档，现有运行数据未清理。原始 XML：`data/runtime/r24/core-tests.xml`、`audit-tests.xml`。

未调用真实模型或目标服务器，未开始 Boss 训练；未关闭 #100/#101/#103 等跨端父 Issue。本轮不是 UE 官方校验完成、最新工程构建或端到端通过证明。
