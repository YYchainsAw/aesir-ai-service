# 真实 LLM 联调证据（T22 / #35）

> 从 `data/runtime/dialogue_signals/` 落盘 JSONL 整理的端到端实测记录，对照 T18 联调对齐表口径。

## 1. 总量

| 数据源 | 轮次 | 时间范围 | 说明 |
|---|---|---|---|
| `companion.alice.jsonl`（旧布局根目录） | 24 | 2026-09-24 ~ 09-28 | 早期 console / godot 端到端实测 |
| `aesir/companion.alice.jsonl`（新布局） | 1 | 2026-10-08 | T18 联调抓样 |
| `demo-vn/companion.narrator.jsonl`（新布局） | 1 | 2026-10-08 | fallback 降级证据 |
| **合计** | **26** | | **25 LLM + 1 fallback** |

## 2. 后端分布

- **LLM 路径**：25 轮（96%）——真实 LLM 生成，带 style_guard 校验
- **Fallback 路径**：1 轮（4%）——`source:"fallback"`，demo-vn narrator，LLM 故障时回退 YAML 候选池

## 3. 风格违规证据

- **style_violations 总数：0 条**（26 轮全部 `[]`）
- 这说明：实测期间 LLM 输出从未触发 style_guard 拦截（出戏术语 / 禁忌表达 / 虚构事实信号三类均未命中）
- style_guard 有效性由合成测试证明（`tests/services/test_style_guard.py` 16 例），真实线上拦截案例留待后续诱导测试

## 4. 复读（repetition）证据

- **复读轮数：1 轮**（26 轮的 3.8%）
- 样本：玩家输入「我们这是第一次说话，记住我。」→ Alice 回复「第一次说话啊……那行，我记住了。旅行者，往后路上多指教。」
- 判定：repetition_score 超阈值触发 `repetitive: true`，属可接受范围

## 5. 会话分布（旧布局 24 轮）

| session_id | 轮次 | 说明 |
|---|---|---|
| `console-3078bf4f` | 9 | 终端 REPL 实测 |
| `console-eab13da6` | 4 | 终端 REPL 实测 |
| `sess-godot-001` | 3 | Godot 端到端 |
| `latency-probe` | 3 | 时延探针 |
| `godot-e2e-001` | 2 | Godot 端到端 |
| `godot-bridge-001` | 1 | Godot bridge 实测 |
| `(null)` | 2 | 早期无 session 标注 |

## 6. topic_continued（话题延续）

- 有标注：16 轮（其中 true 5 轮）
- 延续率：5/16 = 31.25%（与 `metrics_report.py` 输出对齐）

## 7. 典型实测对话样本

**寒暄**（2026-09-24，LLM 路径）：
> 玩家：你好，艾莉
> Alice：你好，旅行者。今天打算往哪边走？

**边界婉拒**（2026-09-24，LLM 路径）：
> 玩家：你是gay吗
> Alice：这问题问得……我是魔法师，不是来回答这种的。你要真闲得慌，不如想想前面那段路怎么走。

**关心玩家**（2026-09-28，LLM 路径）：
> 玩家：你也小心点
> Alice：（回复被压缩，原始 JSONL 可查）

**fallback 降级**（2026-10-08，demo-vn）：
> 玩家：你好
> Narrator（fallback）：你好。

## 8. 对照 T18 联调对齐表口径

| 端点 | 实测状态码 | 实测耗时 | 证据来源 |
|---|---|---|---|
| `/v1/companion/chat`（LLM） | 200 | 2328.8ms | `docs/logs/2026-10-08.md` §8 |
| `/v1/companion/chat`（fallback） | 200 | < 5ms | 落盘 JSONL |
| `/v1/tactical/command` | 200 | 19.3ms | T18 抓样 |
| `/v1/agent/step` | 200 | 31.8ms | T18 抓样 |

## 9. 待补证据（后续任务）

- **ASR faster_whisper 真机 WAV 实测**：当前只有 mock 链路，真机 CER/耗时未记录
- **style_guard 真实拦截案例**：需诱导 LLM 出「指令/协议」类词，抓到 `last_style_violations` 非空 + 重试/回退完整链
- **Bruno 真实对话**：Bruno 人格包刚扩充（T31），尚无真实对话落盘
