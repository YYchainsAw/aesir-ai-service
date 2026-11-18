# 年底 NPC 服务交接指南

本页是 #116 的服务端首版交接入口。交付仅覆盖现有接口、支持的动作与可复现证据；UE 导航/BT/GAS/真实伤害由 UE 维护，目标服务器、真实 MySQL 进程恢复和正式发布仍分别在 #98/#123/#99，按当前安排暂缓。

## 固定版本与非敏感资产

从 [#116](https://github.com/YYchainsAw/aesir-ai-service/issues/116) 的最新完成记录获取本次**完整交付 SHA**，以独立副本检出该 SHA。不要用浮动分支名或公网 health 的旧提交替代交付版本。离线包的 `manifest.json.service_commit` 记录导出 SHA，`tracked_worktree_modified` 必须为 false。

随源码保留 `data/policy/`、`data/games/aesir/`、`data/personas/aesir/` 及依赖清单；配置示例为 `.env.example`，实际 `.env`、凭据、模型和状态不在源码包内。环境、Key 与已缓存 ASR 模型由接收方在私有位置配置，不能从聊天或日志复制凭据。

```powershell
git rev-parse HEAD
git status --short
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m scripts.export_ue_handoff --output-dir data/runtime/handoff-final
```

交接包为 `data/runtime/handoff-final/ue-service-handoff.zip`。它包含 OpenAPI、请求样例、当前契约、指南、源码哈希与本次合成样例；属于接口与证据材料，不能证明在接收机器上运行通过。安装按[本机指南](_02_local_setup_guide.md)，SQL/Linux 环境另按[持久化指南](_06_persistence_guide.md)与[远程指南](_08_remote_development_guide.md)。

## 本机 mock 与真实 LLM

在项目根的新终端中设置下列开发配置；采用独立数据目录、单进程及回环地址，保留已有服务和原数据。

```powershell
$env:AESIR_SCOPE_IDENTITY_BACKEND='development'
$env:AESIR_SCOPE_DEV_PLAYER_ID='11111111-1111-4111-8111-111111111111'
$env:AESIR_SCOPE_DEV_SAVE_IDS='["22222222-2222-4222-8222-222222222222"]'
$env:AESIR_SCOPE_STORAGE_BACKEND='json'
$env:AESIR_COORDINATION_BACKEND='memory'
$env:AESIR_SCOPE_LEGACY_ENABLED='false'
$env:AESIR_COMPANION_BACKEND='mock'
$env:AESIR_PARSER_BACKEND='rule'
$env:AESIR_INTENT_BACKEND='rule'
$env:AESIR_ASR_BACKEND='mock'
$env:AESIR_MEMORY_ROOT='data/runtime/handoff/memory'
$env:AESIR_RELATIONSHIP_ROOT='data/runtime/handoff/relationship'
$env:AESIR_DIALOGUE_SIGNALS_DIR='data/runtime/handoff/dialogue-signals'
$env:AESIR_AGENT_STEPS_DIR='data/runtime/handoff/agent-steps'
$env:AESIR_EVENT_SIGNALS_DIR='data/runtime/handoff/event-signals'
$env:AESIR_REQUEST_TRACES_DIR='data/runtime/handoff/request-traces'
$env:AESIR_RECEIPTS_DIR='data/runtime/handoff/executions'
.\.venv\Scripts\python.exe -m scripts.run_server --host 127.0.0.1 --port 18011
```

另开终端 `curl.exe --fail http://127.0.0.1:18011/health`，期望 status=ok、service=aesir-ai-service，核对 service_commit 与固定 SHA。health 的 protocol_version 不是所有端点的统一版本；scoped v0.4 与异步 chat v0.5 见[契约](../protocols/_01_npc_contract.md)。先 context、再 bind，然后替换[请求样例](../examples/ue-scoped.http)的占位 ID；不要直接发送 golden 中的旧绑定。

真实 LLM 使用同一启动方式，将 companion 后端改为 `llm`。按[LLM 指南](_03_llm_integration_guide.md)在私有配置设置 Key、base URL、model 和可选输出/思考参数，重启后生效；本次样例沿用已配置 DeepSeek、关闭思考和 1024 输出上限。不要将 Key 放进命令行或交接包。同名终端环境变量优先于 `.env`。intent/parser 保持 rule 时，动作样例明确标作规则，不能声称 LLM 解析；`source=fallback` 也不能算真实 LLM 通过。

## 当前可交付的正常与拒绝样例

逐请求输入、快照、输出、emotion/gesture/source 与重放断言见[本次验收](../records/_07_p0_closure_verification.md)及其 JSON；真实 chat、wait/follow/burst 均有正常样例，战斗 follow、burst 冷却/无目标与普通攻击有拒绝样例。

普通攻击虽然存在能力资产，但不在 agent 战斗 directive 白名单。明确的普攻命令返回 `BASIC_ATTACK_NOT_SUPPORTED`、action=none、directive=null；不能替换为消耗爆裂魔法，也不能用闲聊声称已发动。新 action_type 或真实普攻支持须先对齐两仓协议与 UE 执行器。本次交接交付的是如实拒绝，**没有新增普攻能力**。

已下发 directive 也不代表 UE 接受、激活、命中或完成。接收方核对原 request/directive/receipt 关联与 TTL，能力 ID 来自实际目录；不要为演示伪造 executed 回执。

## 重试、取消、重启与回退

同进程网络重试保留原 request_id 与语义载荷。异步 chat 先接收 202，再按当前 binding 轮询；完成后同 ID POST 返回原结果，修改载荷为 409。取消、过期与 unknown 不得换 ID 重做动作。示例和原子恢复的自动化入口如下；其中 SQL 专项是隔离 SQLite/测试运行对象重建，不是目标 MySQL/HTTP 进程重启证明。

```powershell
$env:AESIR_COORDINATION_BACKEND='memory'
.\.venv\Scripts\python.exe -m pytest tests/scoped/test_requests.py tests/persistence/test_recovery_api.py tests/persistence/test_memory_correction.py -q --tb=short
```

客户端流程及失败码见[接入指南](_05_client_integration_guide.md)和[模式差异](_06_persistence_guide.md)。运行中的开发实例也可按 `scripts/v05_async_e2e.py` 开头说明配置地址/身份后执行该脚本；脚本会写合成业务状态，仅对隔离实例执行。

停止本机前台实例用 Ctrl+C，确认进程退出后，用相同版本、相同私有配置和状态目录重新启动。JSON 保留记忆/关系文件，不保留内存请求缓存/绑定；重新 context/bind，不重播旧 POST。SQL 用当前自有 Bearer 读取 `/recovery/state`、`/recovery/operations/{id}`、`/recovery/directives/{id}`，核对原 run 后再建立新绑定；恢复结果不驱动历史动作，离线事实/回执沿用稳定身份及 generation/epoch 分项确认。操作级恢复不返回可执行 result。

代码回退在**独立副本**检出此前已验 SHA，验证依赖与配置后更换进程。先停止写入并取得完整恢复点，保留记忆、关系、账本、授权及版本边界。已有 SQL 写入后不能直接切回旧 JSON；schema/数据回退需独立迁移/恢复方案。这里没有自动回退命令，也没有运行任何目标部署操作。

## 交接清单

接收方按 manifest 固定源码；在自己的隔离环境核对启动、health、mock/真实 LLM 的 source、正常/拒绝及同 ID 重放。数据库恢复、Bearer 正式分权、HTTPS/容量和 UE 实际动作分项验收，沿用 #123/#99、UE #19/#20/#21/#30 的边界。阻断清单与角色分工见[Issue 核查](../records/_06_issue_audit_verification.md)，本次修复结果见[验收记录](../records/_07_p0_closure_verification.md)；旧缺陷记录保留历史含义，不当作当前未修复状态。
