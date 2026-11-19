# UE 最小闭环测试记录

2026-11-19，用户指定 `E:\AesirWarden` 并授权从其 GitHub 仓库拉取最新版本测试。**本次结果为阻塞，未通过最小完整闭环。** 后端预检成功不能替代 UE 实际执行、GAS 和回执验收。版本、源码/日志哈希及测试覆盖见[结构化记录](data/ue-minimal-loop-20261119.json)。

## 固定版本与工作区保护

服务为 `4489c47094f4675d7a6def0277063631447acec1`。远端 UE `origin/main` 已 fetch 到 `af5510f7c1a5244b0714893483a9475cab236bdb`；原本机 main 为 `06f24159300140c7289758e50838cbc213d0ca7c`，与最新远端相比分别 ahead 1/behind 44。没有直接 pull/merge 原分支，避免覆盖用户未提交的 uproject、DefaultEngine.ini 和 CommandServiceSubsystem.cpp。

在服务工作区忽略目录 `.workbuddy/ue` 建立 detached、稀疏 worktree，仅检出 Source/Config/Docs 及根文件，跟踪内容无修改。没有下载 Content LFS 或复制第三方资产；这是编译/原生协议测试副本，不能直接视为完整可玩工程。原 UE 工作区的本地提交、源码和地图/蓝图未被替换，正常运行生成的 Saved/缓存与测试日志按原边界保留。

旧 DLL 曾被启动作入口检查，随后因版本过旧停止；没有把旧构建或窗口出现记作最新版本测试通过。本次没有服务器部署、Boss 训练或伪造执行回执。

## 编译结果：引擎开发文件不完整

本机引擎是 `D:\UE_5.8`，5.8.3，CL 58210709。以已安装工具编译隔离 AesirWardenEditor：

| 阶段 | 结果 |
| --- | --- |
| 标准 Build.bat，限制 4 个并行动作 | Exit 6，缺 Engine/Intermediate/Build/BuildRules/UE5Rules.dll |
| 单独 ForceRulesCompile | 同一规则程序集缺失，Exit 6 |
| 依本机 UBT 实现组合 SkipRulesCompile/ForceRulesCompile | 规则缓存已生成，UHT/工具链检查后进入 C++；SharedPCH 编译在 `PrimaryAssetId.h:16` 报 fatal C1083，缺 `PrimaryAssetId.generated.h`，Exit 6 |

仅重建派生规则缓存，没有删除缓存、改引擎源码或修改 InstalledBuild.txt。递归核查 Engine/Intermediate 未找到该生成头文件，隔离项目没有产出最新 DLL。因此不能启动最新工程原生测试，不能把“未执行”记作 pass/skip 成功。

原始日志在本机 `data/runtime/ue19/build-latest.log`、`build-latest-force-rules.log`、`build-rules-recovery.log`；包含故障位置，不作为公网服务或模型证据。机器记录保存原始日志 SHA256。

复现所用最后一条编译命令（仅隔离副本）：

```powershell
& 'D:\UE_5.8\Engine\Build\BatchFiles\Build.bat' AesirWardenEditor Win64 Development '-Project=F:\python\aesir-ai-service\.workbuddy\ue\AesirWarden.uproject' -WaitMutex -NoHotReloadFromIDE -NoUBA -MaxParallelActions=4 -SkipRulesCompile -ForceRulesCompile
```

## 最新 UE 的实际接入范围

远端源码比原工作区新，已有 scoped 0.4、绑定/epoch、回调失效及探索控制。这纠正了从旧 DLL/旧工作区得出的“只有 legacy”结论；是否实际可运行仍须编译后取证。

| 最小闭环环节 | 本次判定 |
| --- | --- |
| UE 聊天→本机服务 | 最新原生 HTTP 测试存在；因构建阻塞未运行，未取得最新 UI 回复证据 |
| follow/wait 路由与重试 | 最新 HTTP contract 测试覆盖角色隔离/重复 directive，未执行 |
| wait 实际停止 | 最新 transient-world fixture 会断言 CharacterMovement 停止、旧回调无效等；未执行 |
| follow 实际导航 | 最新控制器调用 MoveToActor；现有无导航 fixture 只验证失败不会假报 following，不能证明真实地图移动成功 |
| burst/GAS | 最新 `HandleAgentDirective` 仍限制 domain=exploration 且 action=follow/wait；没有本次聊天入口到 burst/GAS 的接线，不可计为支持 |
| 真实执行回执→查询确认 | 最新队友运行链未发现 tactical/executions 回报接线；没有制造 executed 记录来凑闭环 |

源码发现 7 项 `Aesir.Companion.*` 原生测试，实际执行数 **0**。包括 4 项 ScopedProtocol、Lifecycle.CallbacksAndSessionIsolation、ExplorationExecution、HttpContract.ExplorationRouting。它们不等于全部闭环测试，尤其没有真实 follow 地图导航和 burst/回执成功证据。

## 专用后端预检与清理

启动专用回环 `127.0.0.1:8011` rule/mock + development/JSON 服务，授权固定合成 contract 存档，关闭 legacy。`GET /health` 与合成存档 `GET /v1/scoped/context` 均为 200，health 报服务提交 4489c47，context 协议 0.4。这个 Python-only 预检只证明 UE 原生 HTTP 测试的服务依赖已准备好，**不是 UE 客户端执行通过**，也不是真实 LLM/Bearer/MySQL 验收。

本轮启动的旧 UE 测试进程及两个阶段的专用服务进程均已停止。没有留下运行中的 UE 游戏窗口或测试监听进程；隔离 worktree/构建日志保留供后续复现。未提交、合并或推送原 UE 仓库，未改用户现有资产。

## 下一步

1. 从完整、相同版本的 UE 5.8.3 开发安装恢复缺失的引擎生成文件，再编译隔离副本。仅有可运行旧 DLL/编辑器不代表开发 SDK 完整；本次没有擅自安装/重装引擎。
2. 编译成功后，设置 `AESIR_NPC_CONTRACT_URL=http://127.0.0.1:8011`，使原生 HTTP 测试真正启用；不设置时该测试会仅记录 skipped 提示而返回成功，不能把这种返回当作已做 HTTP 验收。
3. 运行全部 Aesir.Companion 自动化并核对测试数量、执行结果与后端关联 ID；先确认纯协议/HTTP/停止状态，再在资源齐全的地图验证真实 follow。
4. 对齐并实现 burst 的真实世界快照、能力/目标合法性、GAS 激活和实际执行回执，再验证取消、重复和旧 epoch 不重复执行。不得通过虚构 MP/技能 ready 或伪造 executed 来替代。

上述引擎修复、地图运行和 burst/回执仍是继续测试的必要条件。本次不会因此关闭 UE #20/#21/#22/#24、服务 #101/#103 或任何正式部署任务。
