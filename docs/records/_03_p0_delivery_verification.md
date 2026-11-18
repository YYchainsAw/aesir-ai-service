# P0 服务端交付核查（2026-11-16）

本轮验证源码为 `develop-dyh@95f217a`，环境为 Windows 11、Python 3.12.7。本页是 #122 的本地阻塞与责任清单、#119/#98 的证据索引及 #116 的交接补充；不代表已更新或关闭远端 Issue。责任按所需角色划分，具体人员仍由维护者分配。

同日后续：用户指定改用 DeepSeek。本地配置已切为 `https://api.deepseek.com` + `deepseek-flash`，对话使用 llm、parser/intent 使用 rule；补充可选 thinking/max_tokens 参数后，本机显式关闭思考、限制 1024 输出 tokens。相关 30 项专项及完整核心 **1632 passed、13 skipped、7 warnings（122.39 秒）**通过。此结果对应 `95f217a` 上的未提交工作区增量，原 ASR 结果仍对应下表的修改前基线。

更换 Key 期间的历史诊断：首次文本请求为 401，再次为非标准 550；随后两次只读 `/models` 诊断均为 HTTP 401 / authentication_error。文件和进程读取的 Key 一致，没有环境变量覆盖。有效 Key 保存后已解除该阻塞，最终状态见下方整链路验收。

**同日最新复测：认证阻塞已解除。** 用户更新并保存有效 Key 后，系统网络设置与直连的 `/models` 均返回 HTTP 200，包含 `deepseek-flash`。独立服务的 v0.5 scoped 文本提交 HTTP 202 后轮询 completed，`source=llm`，总耗时 1750 ms；同 request_id 重放 HTTP 200 且响应完全一致。此轮未提交执行回执；只覆盖本机 development/JSON/memory，真实 ASR→LLM、LLM 指令、Bearer/目标服务器及 UE 仍待验。当前证据为 `deepseek-connectivity.json`、`deepseek-real-text.json` 与 `deepseek-success.json`；源码包含上文省费参数的未提交增量，健康接口的 `95f217a` 仅表示基础提交。

## 最新整链路验收

有效 Key 恢复后完成以下本机真实服务验证，未再次修改应用代码，因此沿用已通过的 **1632 passed、13 skipped、7 warnings**核心回归。隔离实例使用 development/JSON/memory，不提交执行回执；日常 `.env` 的 parser/intent 仍保持 rule，只有隔离指令测试使用 llm。

| 验证 | 结果 | 边界 |
| --- | --- | --- |
| v0.5 文本 | HTTP 202→completed，source=llm，1781 ms；同 ID 重放完全一致 | 合成测试文本，非 fallback |
| 真实 LLM 指令 | wait / follow / burst 分别 1344 / 1203 / 1203 ms，均为合法 directive | 保留快照、时效和请求关联；follow 使用真实快照目标，burst 使用既有 ability.alice.explosion 与 encounter.primary_hostile |
| 缺少目标 | none / NO_VALID_TARGET，1000 ms | 上游确实调用 LLM；最终拒绝由规则门禁给出，observability.source=rule，不是模型失败回退 |
| 未满足条件 | none / CONDITION_NOT_SUPPORTED，875 ms，source=llm | 未把未来眩晕条件变成立即执行 |
| 指令幂等 | 五例同 ID 重放均一致，模型调用计数不增加 | 没有提交 accepted/executed 等回执，不证明实际游戏动作 |
| 真实 ASR→LLM | 转写“開放時間早上9點至下午5點”，两次回复均 source=llm；首请求 4640 ms、热请求 3047 ms | 5.616 秒官方样例，不是 UE 麦克风录音或 p95 |
| 语音去重 | 同 ID 重放 31 ms，响应一致，ASR/LLM 调用均不增加；同 ID 换音频 409 / REQUEST_ID_CONFLICT | 透明包装仅计数，不修改转写或模型输出 |
| 上传门禁 | 空音频 422 / ASR_EMPTY；坏格式 422 / AUDIO_INVALID_FORMAT；超大上传 413 / AUDIO_TOO_LARGE；过期绑定 409 / RUN_BINDING_STALE | 前两项不调用 LLM；后两项不调用 ASR/LLM |
| ASR 故障与切文本 | 独立实例指定缺失模型且关闭下载，真实适配器返回 502 / ASR_UNAVAILABLE；同 ID 故障重放不再调用 ASR；该实例真实文本 source=llm，1766 ms | 使用实际模型配置故障，未用 mock；证明文本服务可继续，不证明 UE 切换界面 |

真实文本样例出现“路我大致看过了”的无来源世界叙述；请求没有路线快照或路况事实。该样例证明调用、结构与幂等通过，不能证明事实约束/角色质量通过。原回复保留在 `live/text-normal.json`，后续须整改与正式采样。

缓存观察：语音首请求命中 7040/7213 输入 tokens（97.6%），加入历史后的热请求命中 896/7465（12.0%）。当前 prompt_builder 在固定规则/示例前插入动态记忆与历史，影响共同前缀复用；后续优化应优先固定前缀布局与提示词长度，并验证行为语义，不以额外付费请求刷高命中率。缓存匹配与落盘规则见 [DeepSeek 文档](https://api-docs.deepseek.com/zh-cn/guides/kv_cache/)。

| 任务 | 当前本机交付 | 仍需验收 |
| --- | --- | --- |
| #122 | 阻塞与证据清单已更新，认证阻塞解除 | 回复事实约束、缓存布局优化与远端 Issue 同步 |
| #119 | 真实文本、wait/follow/burst、拒绝与幂等样例完成 | 实际 UE 动作和完整内容质量 |
| #98 | 真实 ASR→LLM、音频门禁、去重、ASR 故障切文本完成 | 目标服务器、正式身份、UE 录音与切换界面 |
| #116 | 离线接口包与运行证据包已生成 | 接收方、目标实例的启动/重启/回退验收 |
| #121/#123、#96 | 原边界保持 | 真实目标 MySQL/Bearer/UE 恢复；冻结 Boss 材料仍缺失，新训练暂停 |

最新证据位于 `data/runtime/p0-20261116/live/`：`text-normal.json`、`llm-intents.json`、`voice-chain.json`、`voice-failure.json`、`text-fallback.json`、健康快照和透明上游计数。指令跨两个隔离实例，各例按自身 service_instance_id 完成幂等验证。第一轮脚本对缺目标结果错误要求 source=llm；核对规则门禁后修正核查条件，并保留日志，未修改应用代码或重复已通过的三个模型指令样例。

交接 ZIP 为 `p0-real-backends-evidence.zip`，包括合成请求/响应、脱敏计数、最终 JUnit、源码指纹、文件 SHA256 与核查说明；不包含 Key、私有 .env、原始录音、模型、记忆目录或完整服务日志。离线接口包另存于 `handoff/ue-service-handoff.zip`。证据中的 ID 仅作历史关联，不能用作新实例有效凭据。

## 初始阶段结果（历史）

| 验证 | 结果 | 适用范围 |
| --- | --- | --- |
| 真实 LLM 最小请求 | HTTP 400，`InvalidSubscription`；原接口为 `/api/coding/v3`、模型为 `ark-code-latest` | 已验证提供方可达；订阅不可用，真实文本与 ASR→LLM 整链路阻塞。探测未改凭据或路由 |
| 真实 ASR HTTP 上传 | `faster_whisper` 转写得到“開放時間早上9點至下午5點” | development 身份 + JSON + memory，scoped context/bind 后上传；回复 `source=mock` |
| ASR 首请求/热请求/重放 | 7032 / 1469 / 31 ms | 单条 5.616 秒音频，首请求包含模型加载；不是 p95 或容量结论 |
| ASR 去重与空音频 | 同 ID、同音频响应一致；新 ID 热请求转写一致；空音频 HTTP 422 / `ASR_EMPTY` | 本机真实模型及 HTTP；商业 ASR、Bearer 目标服务器及 UE 麦克风未实测 |
| 规则指令 HTTP 样例 | “艾莉，原地等我”→ wait；“艾莉，跟着我”→ follow；“布鲁诺，跟着我”发给 Alice → none、directive=null | 前两项 `source=player_command`，可观测解析来源为 `rule`；没有提交执行回执，没有证明游戏内移动或执行 |
| 核心自动回归 | **1625 passed、13 skipped、7 warnings，92.37 秒** | 无付费模型的 API、service、schema、script、scoped、persistence 和 Boss 契约测试；SQL 测试替身/SQLite 不等于本轮真实 MySQL |
| Boss 产物清点 | 冻结 ZIP、配套 training manifest、selection 均缺失；`sb3-contrib` 未安装 | 未反序列化旧模型、未训练新模型，保留 #96 材料阻塞 |

ASR 模型为 `small`，快照 `536b0662742c02347bc0e980a01041f333bce120`，CPU/int8；依赖 faster-whisper 1.2.1、CTranslate2 4.8.2。使用已有本地缓存，并设置 `HF_HUB_OFFLINE=1`。音频为已有官方中文样例转换的 16 kHz、单声道、16-bit PCM WAV；来源见 [ASR 指南](../guides/_11_asr_guide.md)，SHA256 为 `1c92a4a54368e0371bfa2dbf50304b0b0b42738a2fe9832b59c41db2e86fe23f`。

13 个跳过项分别为：2 项需显式启用的 ASR 真机冒烟、1 项未注册 narrator 的表现白名单、5 项 POSIX/Linux 文件权限与部署边界、5 项未提供专用 MySQL URL。单独的真实 ASR HTTP 复测不改变 pytest 中真机用例的跳过状态。warnings 为现有 Starlette 弃用提示。

## 初始阻塞与责任（历史；以最新整链路验收为准）

| 对应任务 | 当前状态 | 所需角色与下一步 | 完成凭据 |
| --- | --- | --- | --- |
| #122 阻塞清单 | 本地更新完成；远端 Issue 待同步 | 服务端维护者核对本页和原 Issue；分配以下依赖的实际责任人 | 版本、日期、环境、测试范围与未验项一致 |
| #119 真实文本/指令 | 规则样例通过；真实 LLM 阻塞 | 凭据维护者恢复有效订阅及匹配的 Key/基础地址/模型；服务端随后复测 | 真实 chat `source=llm`、请求关联和幂等；合法/拒绝指令保留目录与时效，LLM 失败回退单列 |
| #98 真实语音 | 本机 ASR 通过；目标服务器与 LLM 串联待验 | 部署维护者在目标机器预置模型并配置身份；服务端复测；UE 维护者提供录音与文本切换 | 认证上传、音频门禁、去重、空白/失败兜底，真实 ASR→LLM；UE 独立提供交互证据 |
| #116 交接基线 | 本轮离线包可导出；整体验收未完成 | 服务端交接源码 SHA、契约、非敏感配置和本轮证据；维护者确定接收方和环境 | 离线接口包与实际运行证据分开；目标实例启动/重启/回退记录 |
| #121/#123 恢复 | 本轮自动回归通过；真实目标库未验 | 数据库/部署维护者提供隔离库与私有连接文件；服务端验证认证、重启与历史恢复 | 真实 MySQL、Bearer、重启后重新绑定、旧结果不重复副作用 |
| #96 Boss | 材料阻塞；新训练继续暂停 | 模型保管者提供已登记冻结 ZIP、training manifest、selection 和可信来源；服务端核对后再验证 | SHA、Schema/空间检查、真实启动与独立评估；UE fallback 另验 |

默认完整对话信号保留、正式数据切换/HTTPS/备份调度、实际 UE 执行与恢复仍按[质量计划](../planning/_14_quality_plan.md)跟踪。自动回归成功不关闭这些交付项。

## 证据与复现

本机忽略目录 `data/runtime/p0-20261116/` 保存脱敏 LLM 诊断、真实 ASR 结果、健康版本、规则请求/响应、最终 JUnit 和带文件 SHA256 的 `verification-summary.json`。不将 Key、私有 `.env`、原始录音或完整服务日志纳入交接包。

最终回归使用仓库外短临时目录：

```powershell
$env:AESIR_COORDINATION_BACKEND='memory'
.\.venv\Scripts\python.exe -B -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q --tb=short -p no:cacheprovider --basetemp C:\aesir_pytmp\p0-20261116 --junitxml=data/runtime/p0-20261116/core-final-tests.xml
```

初次临时目录父目录未预建导致 setup 失败，后续仓库内长目录触发 Windows 路径问题，缩短后仍有 6 项因凭据/备份禁止放在应用目录内而失败；最终改用仓库外短目录全部通过。保留失败记录用于解释环境差异，没有修改安全门禁或应用代码。

离线契约包生成命令：

```powershell
.\.venv\Scripts\python.exe -B -m scripts.export_ue_handoff --output-dir data/runtime/p0-20261116/handoff
```

该 ZIP 只证明源码接口与指南可导出，运行验证见独立证据。人工恢复 `.env` 中 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 后需重启实例；已有进程环境变量优先于 `.env`。随后先做最小连通检查，再补 #119 和 ASR→LLM，不能把 fallback 回复作为真实 LLM 成功。
