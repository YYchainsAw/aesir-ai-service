# 对话 RL「导演层」立项评估（#54 / T39）

> 2026-10-27 立项评估，响应 [#54](https://github.com/YYchainsAw/aesir-ai-service/issues/54) 批准。
> 本页只做评估与最小切片建议，**不启用在线学习、不做自演化人格**（沿用 EXT-03 边界）。
> 路线基线见 memory `project-rl-dialogue-plan`：RL 不替代 LLM 生成，只做导演层（记忆调度 + 表现选择）。

## 1. 现状盘点（事实，非规划）

### 1.1 埋点代码已就位

- [dialogue_signals.py](../../app/services/companion/dialogue_signals.py)：每轮对话结束追加一条 JSONL。
- [agent_step_signals.py](../../app/services/companion/agent_step_signals.py)：每个自主步追加一条 JSONL。
- 埋点是观测非流程，写盘故障静默吞掉（不阻塞对话），v0.4 作用域失败才向外传播。

### 1.2 真实数据量（2026-10-27 实测）

| 文件 | 行数 | 时间跨度 |
| --- | --- | --- |
| `data/runtime/dialogue_signals/aesir/companion.alice.jsonl` | 16 | 2026-10-21 一天 |
| `data/runtime/dialogue_signals/aesir/companion.bruno.jsonl` | 3 | 2026-10-21 一天 |

**合计 19 条**。memory 自定的 bandit 起步触发条件是「几百轮真实对话」--当前缺口 **~1 个数量级**。

### 1.3 单条记录的实际字段分布（alice 16 条抽样）

```json
{
  "ts": "2026-10-21T01:36:05+00:00",
  "source": "llm",
  "player_text": "我最喜欢用什么武器来着？",
  "reply_text": "长剑呀……怎么，想考考我？",
  "emotion_id": "emotion.bright",
  "gesture_id": "gesture.cheerful_idle",
  "facial_expression_id": "face.bright_smile",
  "injected_topics": ["港口小镇","长剑","Boss战","护盾"],
  "signals": {"negative_feedback": null, "repetition_score": 0.0, "topic_continued": null},
  "repetitive": false,
  "style_violations": [],
  "memory_cited": true,
  "relationship_stage": "neutral",
  "sentiment": "none",
  "relationship_delta": 0,
  "relationship_reason": "no_signal"
}
```

**稀疏信号事实**：16 条里 `sentiment="none"`、`relationship_delta=0`、`relationship_reason="no_signal"`、`negative_feedback=null`、`repetition_score=0.0` 占绝大多数。即：**负面/情感/复读/关系变动这些潜在 reward 信号，在当前对话里几乎不触发**。

### 1.4 切片 A 基线报告实测（2026-10-27 跑）

`scripts/rl/dialogue_signal_report.py` 在上述 19 条真实数据上的输出：

```
总样本: 19  跨度: 2026-10-21 00:30 ~ 01:36（一小时内）
source: llm=17, fallback=2
reward 触发率:
  negative_feedback_hit_pct: 0.0%      ← 玩家否定 0 次
  repetitive_pct:             0.0%      ← 句式复读 0 次
  style_violation_pct:        0.0%      ← 风格违规 0 次
  relationship_delta_nonzero_pct: 10.5%← 仅 2 条有实际关系变动
  memory_cited_true_pct:      84.2%
sentiment 分布:  none=12, warm=7         ← 有情感信号仅 36.8%
relationship_reason: no_signal=12, scored=2, cooldown_blocked=5
context 分桶:  distant|conversation=3, neutral|conversation=14, neutral|exploration=2
```

**这份报告本身就是评估结论的硬证据**：bandit 可用的 reward 正负例（negative/repetitive/style/relationship_delta）合计仅 2 条，远不够分桶学习；context 三个桶里两个样本 ≤3 条，bandit 在空桶上学不到策略。结论与 §3 一致--当前数据条件不支持 bandit 起步。

## 2. 特征向量评估（能否支撑 bandit context / reward）

把现有字段按 bandit 的三要素拆分：

| bandit 角色 | 候选字段 | 评估 |
| --- | --- | --- |
| **context（状态）** | `game_state`、`relationship_stage`、`injected_topics`、`memory_cited`、`scene`（agent_steps） | ✅ 离散、低基数、可直接 one-hot。够用来分桶 |
| **action（导演层选什么）** | 当前 LLM 链路：`emotion_id` / `gesture_id` / `facial_expression_id` / `injected_topics` 注入 | ✅ 动作空间小（表情~6、手势~6、印象主题~4），bandit 适用 |
| **reward（反馈）** | `negative_feedback`、`repetition_score`、`style_violations`、`relationship_delta`、`memory_cited` | ⚠️ **方向可定，但当前数据稀疏**：reward 几乎全 0/None，学不到正负例 |

**结论**：context 与 action 空间已经具备 bandit 起步条件；**真正的瓶颈是 reward 信号太稀疏**--不是埋点没埋，是当前实测对话里负面/复读/关系变动事件本身就少。

## 3. 数据量与信号稀疏的根因

19 条全来自 2026-10-21 一次集中实测，不是日常累积。稀疏根因有二：

1. **样本量小**：16 条 alice 对话里出现「幻视/记岔/没说过」这类玩家否定的概率本就低（实测里 0 次）。
2. **信号触发条件偏严**：`relationship_delta` 依赖 LLM 判出 warm/deep/cold/hurtful，实测样本多为中性闲聊 -> `no_signal`。

这两点都不是代码缺陷，是「需要更多真实对话」的问题。

## 4. 最小可运行切片（不写在线 bandit）

基于 §3，现在直接上在线 bandit 会「在 reward 全 0 的样本上训出一个永远选默认动作的策略」。建议最小切片按序：

### 切片 A：离线信号评估脚本（现在就能做）

新增 `scripts/rl/dialogue_signal_report.py`：扫 `data/runtime/dialogue_signals/**/*.jsonl`，输出：

- 各 reward 信号触发率（`negative_feedback` 命中率、`repetitive=true` 占比、`style_violations` 非空占比、`relationship_delta≠0` 占比、`memory_cited` 分布）；
- 按 `relationship_stage` × `game_state` 分桶的样本数（识别哪些桶是空的，bandit 不会在空桶上学）；
- `sentiment` 分布与 `relationship_reason` 分布（核对「判定 vs 实收」是否脱节）。

产出物：一份基线信号报告。**作用是把「以为有信号」变成可见数字**，与 T38 把 SC-005 从「以为没问题」跑出 FAIL 的思路同构。

### 切片 B：攒数据到门槛（依赖实测，不写代码）

- 触发条件：alice+bruno 合计 ≥ 300 条真实对话，且 `relationship_delta≠0` 或 `negative_feedback≠null` 的样本 ≥ 30 条（reward 有正负例）。
- 期间不改在线行为，只持续埋点。每次用户实测对话自动累积。

### 切片 C：离线 bandit 回放（B 达标后）

- 复用 `rl/boss/` 的 MaskablePPO 脚手架做离线评估（off-policy 回放），先不接在线。
- 动作空间 = `(emotion, gesture)` 二元组（印象主题注入另算），context = `(game_state, relationship_stage, memory_cited)`。
- reward = `negative_feedback?-1 : (style_violations? -0.5 : (relationship_delta>0? +1 : 0))`。

### 切片 D：在线 bandit（C 验证后，最末）

- 只在「离线回放显著优于当前默认策略」时才切在线。
- 在线叠加方式：LLM 生成回复文本不变，bandit 只在生成前决定「注入哪些印象主题 + 选哪个表情/手势」。LLM 与 bandit 正交，互不回退。

## 5. 与现有 LLM 对话服务的叠加方式

- **LLM 负责生成回复文本**（不变，DeepSeek API 无法做策略梯度）。
- **bandit 负责导演层**：在 prompt 组装前选 `injected_topics` 与表现 ID。
- 两者正交：bandit 输出只影响 prompt 注入与表现，不影响 LLM 采样。回退时 bandit 选默认值（当前手调超参），LLM 行为零变化。
- 不做 RLHF/DPO 本地 QLoRA（8GB 显存跑不动 RLAIF 流水线，memory 已定）。

## 6. 风险

| 风险 | 缓解 |
| --- | --- |
| reward 信号长期稀疏（实测对话不触发负面事件） | 切片 A 报告暴露触发率；若长期 <5%，重新定义 reward（如把 `topic_continued` 作正向代理） |
| 300 条数据攒不到（用户实测频次低） | 接受数据驱动节奏，不强推；导演层延后不阻塞主线 |
| 离线 bandit 不优于默认策略 | 不切在线，维持手调超参；这本身是有效结论 |

## 7. 结论与建议

1. **立项批准成立，但当前不具备在线 bandit 起步条件**：特征/动作空间已就位，reward 信号稀疏 + 数据量仅 19 条（缺口一个数量级）。
2. **本轮交付切片 A**（离线信号评估脚本）是唯一可立即落地、不依赖外部、能产出可见数字的工作。切片 B 依赖实测攒数据（不可强推），切片 C/D 顺延。
3. **不启用在线学习**，不做自演化人格，LLM 生成路径零改动。
4. 与 50k 主线（阶段 2 异步化）并行，不阻塞。

---

> 下一步：实现切片 A `scripts/rl/dialogue_signal_report.py` + 基线报告，跑一次落数。issue #54 保持 open（立项评估完成 ≠ 导演层实现），在 issue 评论本结论。
