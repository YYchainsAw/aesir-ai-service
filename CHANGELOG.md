# Changelog

按里程碑记录本项目进展。原始逐日开发记录归档于 [`docs/logs/`](docs/logs/)，本文件只保留里程碑摘要与当前测试数锚点。

> 测试数锚点纪律：各文档不单独维护测试数，统一以本文件最新锚点为准（当前：2026-09-14，**286 通过 + 3 冒烟跳过**）。

## 2026-09-14 — 终端对话调试台 + B1 人格语料扩充（SDD Phase 1~3 补记见下）

### 终端对话 REPL（方案 A：start.bat chat 直接与 NPC 对话）

- **`start.bat chat [端口]`**：服务已运行则直接复用，否则后台最小化启动 uvicorn，随后进入终端对话；退出对话后服务留在后台。
- **`scripts/chat_console.py`**：httpx REPL——等 `/health` 就绪（最长 60s）、固定 `session_id`（跨轮短期记忆生效）、每轮显示 `source`（mock/llm/fallback）与 emotion/gesture/face 三个表现 ID，便于人设合格检查。内置命令：`/help` `/memory` `/reset` `/scene exploration|conversation` `/quit`。Windows 下 stdin/stdout 统一 UTF-8。
- **新调试端点 `GET /v1/console/memory`**：返回指定角色三级长期记忆全量视图（counts + short_term/summaries/archive 精简条目），支撑 `/memory` 命令与 US1 验收检查。

### B1：人格训练语料（few-shot 优先路线）

- **`dialogue_examples` 8 → 62 组**：新增问候/告别/情绪关怀/称赞/设定问答/战斗闲聊/记忆引用/承诺/边界拒绝/礼物共 14 个互动类别；记忆引用类示范如何自然使用长期记忆；战斗请求全部角色口吻婉拒。
- **`fallback_dialogue_responses` 新增 comfort/greeting/farewell 三类**：mock 后端（无 LLM）也能覆盖关怀与寒暄场景。
- **`data/training/`**：语料管道落库——`README.md`（格式/分类表/流程：批量生成→人工过滤→入库→评测）+ `filter_checklist.md`（六条人工过滤红线）。语料攒 500+ 后再评估 B2 微调。
- **语料红线自动测试**：禁出戏术语（指令/接口/频道/协议/系统/模型等）扫描全部 few-shot 与回退候选；体量与类别覆盖断言（≥60 组、≥12 类、关键类别齐全）。
- **测试**：新增 5 例（console/memory 视图×2、语料红线×2、回退默认路径修正）。**286 通过 + 3 冒烟跳过**。

### 补记：SDD Phase 1~3（feadebf / 61de0a6 / e20fcc9，此前漏登 CHANGELOG）

- **Phase 1 Setup**：记忆/关系/活动域/技能服务子包骨架；记忆、心跳限流、关系数值、工具调用轮次等全部配置外置（`AESIR_MEMORY_*` 等）。
- **Phase 2 Foundational**：v0.3 骨架——统一信封 `DirectiveEnvelope`、`WorldContext` 世界快照、`POST /v1/agent/step`（心跳限流 429 / 空动作）、`POST /v1/world/events`（幂等回放）、`GET /v1/console/state` + `POST /v1/console/memory/reset`；`data/golden/` 增世界快照与心跳样例。
- **Phase 3 US1 记忆**：三级分级记忆（短期/摘要/档案，承诺不淘汰）、原子落盘 + `.bak` + 损坏隔离、预算检索注入 LLM prompt、对话链路全降级（记忆故障对话不中断，FR-011）、`scripts/demo_memory_persistence.py` 演示。测试 236 → 282。

## 2026-09-10 — 陪伴对话质量方案 B（短期会话记忆）+ RL 100 万步多种子训练

### 方案 B：短期会话记忆（服务端先行，向后兼容）

- **`session_id`（选填）**：`/v1/companion/chat` 请求新增；响应同步回显。不传时行为与 v0.1 完全一致（无状态）。
- **滚动窗口记忆**：`app/services/companion/session_memory.py`——按 `session_id` 维护最近 N 轮（`AESIR_DIALOGUE_HISTORY_TURNS`，默认 10，0 = 关闭）「玩家输入 + 艾莉回复」，线程安全、进程内存、重启即清空；刻意不做长期记忆/玩家画像。
- **LLM prompt 注入对话历史**：历史以「Player:/Alice:」对话块进入系统提示，角色可接续上文；mock/回退路径不受影响但同样记录（后端切换不断档）。
- **YAML `runtime_state_policy` 修订**：v0.1 无状态条款升级为 v0.3 会话记忆语义（含「未携带 session_id 时无状态」）。
- **测试**：新增 8 例（记忆读写/淘汰/隔离/关闭、历史注入 prompt、session_id 回显与 422 校验、mock 记录集成）。**250 通过 + 3 冒烟跳过**。

### RL：3 种子 × 100 万步 PPO 训练与 A/B 评测（结论：2/3 种子达标）

| agent | mean_reward | win_rate | stun_burst_rate |
| --- | --- | --- | --- |
| rule 基线 | 17.62 | 1.00 | 0.00 |
| ppo seed 0 | 15.11 | 1.00 | 0.00（训练后期震荡，最终 checkpoint 恰在坏相位） |
| ppo seed 1 | 21.76 | 1.00 | **1.00** |
| ppo seed 2 | 21.76 | 1.00 | **1.00** |

- seed 1/2 稳定学到「眩晕窗口施放爆裂」（reward +23%），**满足 §8 上线判定**（win_rate 不降且 stun_burst_rate 显著更高）；seed 0 训练后期在两解间震荡且无中间 checkpoint 保留——后续训练应按评测选优保存 checkpoint，而非只存最终点。
- 模型与日志：`models/rl/ppo_bossfight_seed{0,1,2}.zip`、`models/rl/train_multi_seed.log`、`models/rl/eval_multi_seed.log`。

## 2026-09-10 — 陪伴对话质量方案 A（人设深度 + 语料样例 + 回退多样化）

- **背景**：对话链路此前只把 background/tone 注入 prompt，YAML 人设大半没被模型看到；无 few-shot 语料；无 LLM 时回退是单句静态「我在呢。想聊什么？」——表现为复读机。
- **YAML 新增 `dialogue_examples`**：8 组 few-shot 示范（smalltalk/question/praised/cared_for/lore_question/tactical_redirect），示范「同类输入 → 对应风格与情绪 ID」模式；ID 受白名单校验。
- **YAML 新增 `fallback_dialogue_responses`**：按类别的多条回退候选（tactical_redirect/praise/concern/question），关键词命中选类、组内按输入的稳定哈希轮换（CRC32，跨进程重启恒定）。
- **LLM prompt 全量注入**：core_traits / values / dislikes / relationship（surface+subtext+behavior_rules）/ speaking habits / avoid 全部进系统提示 + few-shot 块。
- **profile_repository** 解析并校验两个新字段（示例/候选 ID 不在白名单 → 503 配置错误）。
- **测试**：新增 6 例（分类命中、确定性、战术引导、未命中回默认、prompt 注入断言、YAML 解析校验）；全链路 `mock_ue_flow` 已验证。**242 通过 + 3 冒烟跳过**。
- **后续路线（已写入策划书 §11）**：B = 短期对话记忆（需 `session_id`，v0.3 协议、待 UE）；C = 工具调用 + 世界观知识库（查设定/查战况，按需做）。

## 2026-09-10 — 战术指令 LLM 意图解析

- **LLM 意图解析后端**：`app/services/tactical/llm_intent.py`——组合端点 `/v1/tactical/command` 的意图解析按 `AESIR_INTENT_BACKEND` 选 rule / LLM；LLM 输出严格 JSON 的 `TacticalIntent`（`intent_id` 受 Literal 白名单约束），任何失败（配置缺失、网络、非法输出）回退规则解析器。
- **降级可观测**：`source` 字段标记实际来源（`rule` / `llm` / `rule_fallback`），供 UE 端降级观测。
- 测试：**236 通过 + 3 冒烟跳过**。

## 2026-09-09 — v0.2 定稿 + 全项目审查整改

- **P0 文档修正**：getting-started 标题手误；llm-integration.md 失效 import 路径（重构后门面已移至 `app/services/parsers/`）；v0.2 §7 回执示例改为与实现一致的 `{"receipt": {...}}` 信封结构。
- **事件幂等（总策划书 §4.2）**：`/v1/combat/events` 按 `encounter_id + event_id` 去重——重试回放首次响应（同一 `order_id`，不重复施法），新增 `duplicate: true` 响应标记；跨 encounter 同 ID 独立处理。
- **快照时间校验**：`captured_at` / `occurred_at` 非法 ISO-8601 按 422 拒绝（v0.2 §2.1）。
- **策略阈值迁移 YAML**：resolver/event_policy 的阈值与优先级迁至 `data/policy/tactical_policy.yaml`（兑现策划书 §5.1「YAML 阈值/优先级策略」），`policy_revision` 与 YAML `revision` 真实挂钩；试玩调参只改 YAML；保留原常量名供 RL 基线引用。
- **v0.2 协议定稿**：`combat-tactical-protocol-v0.2-draft.md` → `combat-tactical-protocol-v0.2.md`，状态改正式版；全部端点 Python 侧已实现并有测试。
- **UE 联调支持资产**：`data/golden/` 四类战况 golden 快照（与回归集 A/B/C/D 同源）+ `scripts/mock_ue_flow.py` 假 UE 全链路演示（chat → parse → resolve×4 → events 幂等 → executions），已端到端验证。
- **文档体系整改**：策划书成为进度勾选唯一来源（README 路线图只做版本级摘要）；阶段验收统一标注「待 UE」；§11 下一步清单更新；新增 §12 风险登记。
- **组合端点 `POST /v1/tactical/command`**：文本 + 快照 → 上下文决策一次到位。新增规则意图解析器 `intent_parser.py`（关键词白名单 → 7 个 `intent_id`，wake 词与 v0.1 一致，多意图按优先级判序），不可识别回复澄清（`recognized:false` + `decision:null`）；`mock_ue_flow` 演示同步覆盖。
- 测试：**224 通过 + 3 冒烟跳过**。

## 2026-09-08 — 契约 v0.1 收尾 + RL 训练前清理 + 结构重构

- **已知未修清零**：规则解析器多意图冲突按 `priority` 降序判序（retreat 90 早于 hold 60）；`order` 内部模型补 `extra="forbid"`；companion YAML 损坏返回 503 而非 500。
- **`POST /v1/combat/events`**：v0.2 最后一个未实现端点落地——六类战斗事件 → 艾莉反应/建议/候选动作；阈值常量与 resolver 同源。
- **RL 训练前冗余清理**：删 `rl/storage.py` 死代码；复用同一份 `CombatContext`；训练日志从「不变基线」改为「PPO 自身学习曲线」。
- **项目结构全面重构**（行为零变化）：services 归位、路由注册集中化、解析器 facade 回子包、pydantic-settings 统一、`pyproject.toml` 包安装。
- 测试：**208 通过 + 3 冒烟跳过**。

## 2026-09-07 — 阶段 3 转写 + 角色 ID 统一 + v0.2 第一阶段 + RL 脚手架

- **专用转写端点 `/v1/speech/transcribe`** 落地，与组合端点 `/v1/voice/command` 并存；真人声调优脚手架 `scripts/asr_eval.py`（真人录音样本未提供，调优进程取消、脚手架保留）。
- **角色 ID 统一**：eirin → `companion.alice` / `ability.alice.*`，显示名「艾莉」；wake 词保留旧名向后兼容。
- **全项目可行性审查**：修复 LLM 越界静默替换、prompt golden 硬编码 alice、契约缺字段等；结论「整体可行，无致命问题」，faster-whisper small + 8GB 显存端到端在 UE 3s 预算内。
- **v0.2 第一阶段**：`CombatContext`/`TacticalIntent`/`TacticalDecision` schema + `/v1/tactical/resolve` 规则策略 v1 + 85 例回归评测集。
- **RL 脚手架落地**：顶层 `rl/` 包（BossSim + PPO 闭环 + executions 回执），物理隔离不接服务路径；规则基线 `stun_burst_rate=0.00` 成为留给 RL 的核心学习空间。
- 测试：**197 通过 + 3 冒烟跳过**。

## 2026-09-03 — 语音 mock 全链路 + 设计文档

- **`/v1/voice/command`** 语音组合端点：音频 → ASR（mock）→ 同一解析层，共享契约 v0.1。
- 新增设计文档：`game-design-doc-v0.1.md`、`combat-tactical-protocol-v0.2-draft.md`（上下文感知 AI 队友的策划/协议，尚未实现）。
- 测试：全链路 **42 通过**。

## 2026-09-02 — 服务基础 + 非战斗聊天 + 战术解析原型

- FastAPI 骨架 + `/health` + 通用 OpenAI 兼容 `LLMClient`（代理兼容）。
- **非战斗陪伴聊天 `/v1/companion/chat`**：Alice 人设 YAML 单一来源，mock/llm 双后端，故障回退默认回复。
- **战术解析原型 `/parse-command`**：五类指令（条件施法/保留技能/优先普攻/跟随保持距离/撤退保命），`source` 标注 `llm`/`rule`/`rule_fallback`。
- 明确分工：yjx（人设/聊天/LLM Client）、dyh（战术协议/能力目录/测试集/ASR）。
- 测试：**23 passed**。
