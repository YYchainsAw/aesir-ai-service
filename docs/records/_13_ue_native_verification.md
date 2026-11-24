# UE 构建与队友原生验证

2026-11-24，用户报告 Epic Launcher 官方“验证”完成。实际引擎已从原 5.8.3 更新为 **5.8.4，CL 58902052**，兼容 CL 仍为 55116800。此前缺失的 `PrimaryAssetId.generated.h` 和 CoreUObject 开发链接库均存在；使用新版本重新构建、加载项目模块，不复用旧 DLL。旧 5.8.3 manifest 的缺项统计仅是修复前证据，不拿它核对 5.8.4 的全部内容。

结论：**SDK 文件缺失导致的编译阻塞已解除；最新源码构建及 7 项队友原生测试通过，完整游戏闭环尚未通过。** 本轮没有修改 UE 源码、原 `E:\AesirWarden` 工作区或资产，没有连接目标服务器、训练 Boss 或调用付费模型。

## 固定基线与构建

- UE：`af5510f7c1a5244b0714893483a9475cab236bdb`，隔离目录 `.workbuddy/ue`，Source/Config/uproject 跟踪内容无修改；稀疏副本不含完整 Content。
- 服务：`b386931`，专用回环 `127.0.0.1:8011`，development/json/memory、rule/mock，独立 `data/runtime/u24`，仅授权固定合成合同存档。
- 标准 `Build.bat AesirWardenEditor Win64 Development`，`-WaitMutex -NoHotReloadFromIDE -NoUBA -MaxParallelActions=2`，**Exit 0 / Succeeded，73.50 秒**，生成新的 `UnrealEditor-AesirWarden.dll`。没有再加此前绕过规则缓存的强制参数。
- 工具链 MSVC 14.51.36260、Windows SDK 10.0.26100.0；构建仍提示该 MSVC 新于首选 14.50，以及引擎 API 弃用警告，不把成功构建写成零警告。

## 原生测试与真实 HTTP

运行 `UnrealEditor-Cmd.exe <隔离uproject> /Engine/Maps/Entry -unattended -NullRHI -nosound -nop4 -nosplash`，设置 `AESIR_NPC_CONTRACT_URL=http://127.0.0.1:8011`，执行 `Automation RunTests Aesir.Companion`，按 `Automation Test Queue Empty` 退出并导出报告。

**进程 Exit 0，7 succeeded、0 failed、0 notRun、0 succeededWithWarnings**；测试本身耗时约 1.61 秒，不含 Editor 启动。源码中的“未配置 URL 就返回 skipped 信息”的分支没有执行，导出记录明确写出合同通过。

| 测试 | 验证范围 |
| --- | --- |
| ScopedProtocol.ContextAndBind | context/bind 严格字段与绑定空值 |
| ScopedProtocol.IdentityIsolation | 玩家/存档/角色身份不混用 |
| ScopedProtocol.MonotonicValidity | 单调有效期与迟到失效 |
| ScopedProtocol.ExplorationActions | 支持的探索动作解析边界 |
| Lifecycle.CallbacksAndSessionIsolation | 旧回调失效与会话隔离 |
| ExplorationExecution | 瞬态世界中的有效 wait 实际清零速度；重复指令不重复产生副作用；旧代/过期不改变动作；无导航时 follow 不假报成功 |
| HttpContract.ExplorationRouting | UE C++ HTTP 驱动器实际发出 Alice follow/retry/wait/chat、Bruno 路由与 run 清理请求，使用生产解析逻辑 |

合同 10 步均为真实回环请求，含准备和结束后 context 检查的服务日志合计 12 条、全部 HTTP 200。首次 follow 和重试保留相同 logical request_id 与 directive_id；结束后查询确认 `run_id`/`run_binding_id` 为空。不是人工伪造执行回执。HTTP 驱动器测试和瞬态动作测试是分别验证，不把它们写成实际 UI 输入→真实地图行动→回执整链路。

原始 `index.json`、构建/启动日志及 DLL 哈希、精简 HTTP 决策见[机器记录](data/ue-native-verification-20261124.json)。原日志保存在忽略目录 `data/runtime/ue24-verified/`，合成 HTTP 原始请求/响应在 `data/runtime/u24/ue-http.jsonl`。

## 启动日志对照与清理

Editor 在执行项目测试前出现 13 条 `LogAutomationTest: Error: Condition failed`，没有归入这 7 项结果。另建不含 AesirWarden 模块的临时空项目对照，同样出现 13 条；因此该现象不限于 AesirWarden 工程，具体引擎/默认插件根因未定位，不据此宣称日志清零。空项目的 Quit 指令未正常结束进程，采集对照后核对完整命令行，仅停止该临时进程；该次对照不计为自动化通过。

稀疏工程 Content 缺失的 DirectoryWatcher 警告也保留。队友自动化按测试队列结束正常退出；测试后端已停止，run 已清理。没有以旧游戏 DLL、无 URL 的跳过或 Editor 窗口出现代替测试通过。

## 尚待完成

1. 恢复与最新版本相符的地图/蓝图/第三方资产，验证 UI 实际输入、字幕和正常游戏流程。
2. 在带有效 NavMesh 的地图证明 follow 实际移动；当前无导航 fixture 的失败保护不提供这一证据。
3. 贯通聊天入口的 burst/GAS 合法性复核、真实激活/效果与 `/v1/scoped/tactical/executions` 回执；现有队友入口仅 follow/wait，不能据后端支持 burst 判 UE 已支持。
4. UE 持久队列、读档/重启/旧 epoch、SQL/Bearer 与真实 LLM/ASR 按原 Issue 分别验收；保持 #101/#103 及 UE #19～24 等完整父项开放。

本轮修复的是环境前置，并取得此前未执行的真实原生证据；后续跨端功能仍需按上述范围继续实现和验收。
