# Changelog

按里程碑记录本项目进展。原始逐日开发记录归档于 [`docs/logs/`](docs/logs/)，本文件只保留里程碑摘要与当前测试数锚点。

> 测试数锚点纪律：各文档不单独维护测试数，统一以本文件最新锚点为准（当前：2026-09-09，**218 通过 + 3 冒烟跳过**）。

## 2026-09-09 — v0.2 定稿 + 全项目审查整改

- **P0 文档修正**：getting-started 标题手误；llm-integration.md 失效 import 路径（重构后门面已移至 `app/services/parsers/`）；v0.2 §7 回执示例改为与实现一致的 `{"receipt": {...}}` 信封结构。
- **事件幂等（总策划书 §4.2）**：`/v1/combat/events` 按 `encounter_id + event_id` 去重——重试回放首次响应（同一 `order_id`，不重复施法），新增 `duplicate: true` 响应标记；跨 encounter 同 ID 独立处理。
- **快照时间校验**：`captured_at` / `occurred_at` 非法 ISO-8601 按 422 拒绝（v0.2 §2.1）。
- **策略阈值迁移 YAML**：resolver/event_policy 的阈值与优先级迁至 `data/policy/tactical_policy.yaml`（兑现策划书 §5.1「YAML 阈值/优先级策略」），`policy_revision` 与 YAML `revision` 真实挂钩；试玩调参只改 YAML；保留原常量名供 RL 基线引用。
- **v0.2 协议定稿**：`combat-tactical-protocol-v0.2-draft.md` → `combat-tactical-protocol-v0.2.md`，状态改正式版；全部端点 Python 侧已实现并有测试。
- **UE 联调支持资产**：`data/golden/` 四类战况 golden 快照（与回归集 A/B/C/D 同源）+ `scripts/mock_ue_flow.py` 假 UE 全链路演示（chat → parse → resolve×4 → events 幂等 → executions），已端到端验证。
- **文档体系整改**：策划书成为进度勾选唯一来源（README 路线图只做版本级摘要）；阶段验收统一标注「待 UE」；§11 下一步清单更新；新增 §12 风险登记。
- 测试：**218 通过 + 3 冒烟跳过**。

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
