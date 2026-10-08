# NPC ↔ UE 联调对齐表（v0.3 基线）

> 本文件是 T18（Issue #31）的**联调配置收口**：固定两仓版本、端口、ID、分流口径，
> 给出能力/表现 ID 对照表与验收矩阵，并记录实测启动与 health 结果。
> 协议字段定义见 [NPC 服务契约 v0.3](npc-contract-v0.3.md)；文中接口样例为
> **2026-10-08 对运行中实例的实测抓取**。

---

## 1. 版本基线（两仓固定）

| 仓库 | 提交 | 说明 |
|------|------|------|
| `YYchainsAw/aesir-ai-service` | `75ac7a3`（本任务完成时以收尾提交为准） | NPC Python 服务，分支 `develop-dyh` |
| `YYchainsAw/AesirWarden` | `facba39` | UE 工程（联调核查起点） |

> 后续联调以两仓 main/develop 最新提交复核；本表记录的是验收时刻的核查基线。

## 2. 实例、端口与启动记录（实测 2026-10-08）

| 实例 | 进程 | 默认端口 | UE 侧指向（代码默认值） | 联调口径 |
|------|------|----------|--------------------------|----------|
| NPC 服务 | `aesir-ai-service`（本仓库） | **8000**（`AESIR_SERVICE_PORT`，[config.py](../../app/config.py)） | `CompanionChatSubsystem` / `CommandServiceSubsystem` 均为 `http://127.0.0.1:8011` | **统一指向 8000**：UE 两个 Subsystem 的 `ServiceBaseUrl` 改为 `http://127.0.0.1:8000`（FIX-01 已收口 Python 侧，UE 侧改默认值属 UE 仓改动） |
| Boss 服务 | Boss RL `serve.py`（独立实例） | **8012** | `AesirBossPolicyClientComponent` = `http://127.0.0.1:8012` | 与 NPC **分开部署**，互不占用端口 |

**启动命令（实测）**

```bash
# NPC 服务（仓库根目录，.env 已配置 LLM）
./.venv/Scripts/python.exe -m scripts.run_server          # 默认 127.0.0.1:8000
./.venv/Scripts/python.exe -m scripts.run_server --port 8002   # 指定端口（如 demo-vn 第二实例）
```

**health 实测（2026-10-08，端口 8000）**

```json
// GET /health → 200
{"status": "ok", "service": "aesir-ai-service", "protocol_version": "0.3"}
```

## 3. ID 与分流约定

- `game_id = aesir`（一进程一游戏，`AESIR_GAME_ID`）；单 NPC：`companion_id = companion.alice`；
  玩家 `party.player`；未登记/跨游戏 `companion_id` 一律 404，**不回退默认角色**。
- 分流（详见契约 §1）：闲聊/语音 → chat 链路；战斗指令 → `/v1/tactical/command`；
  心跳 → `/v1/agent/step`；游戏事实事件 → `/v1/world/events`；执行结果 → `/v1/tactical/executions`。
- 基础语音与文本进入约定链路：`/v1/voice/command`（WAV → ASR → 同一指令/对话分流）、
  `/v1/speech/transcribe`（纯转写）已可用，UE `ParseVoiceCommand` 已对接。

## 4. 能力 ID 对照表与演示目标

Python 声明全集（[capability.yaml](../../data/games/aesir/capability.yaml)）vs
UE 实现（`TacticalOrderComponent::SupportedAbilityIds`，AesirWarden@facba39）：

| ability_id | Python 声明 | UE 实现 | 状态 | 联调行为 |
|------------|:----------:|:------:|------|----------|
| `ability.alice.basic_attack` | ✓ | ✓ | **启用** | 正常下发执行 |
| `ability.alice.explosion` | ✓ | ✓ | **启用（演示目标）** | 正常下发执行 |
| `ability.alice.quick_heal` | ✓ | ✗ | 未制作 | UE `ValidateOrder` 拒绝（「队友能力目录不包含」）→ 回执 `rejected` |
| `ability.alice.major_heal` | ✓ | ✗ | 未制作 | 同上 |
| `ability.alice.shield` | ✓ | ✗ | 未制作 | 同上 |

- **演示能力目标：`ability.alice.explosion`**（UE 已实现、Python 可决策、可端到端演示；核查起点 basic_attack/explosion 均已核对）。
- **未制作能力口径**：Python 侧按当前策略仍可能决策治疗/护盾（实测 `tactical/command` 曾下发 `major_heal`，见契约 §3 样例 2），
  此时由 **UE 本地校验拒绝并上报 `rejected` 回执**，服务端据回执落盘，不重复强推；
  能力声明（Python 全集）与 UE 实现（2 项）的差异以本表为准，UE 新增能力后同步更新两边。

## 5. 表现 / 行为 / 事件 ID 对照

| 类别 | Python 声明（capability.yaml） | UE 侧状态 |
|------|-------------------------------|-----------|
| 情绪 `emotion.*` | 9 项（bright/excited/pleased/concerned/shy/playfully_annoyed/serious/thoughtful/neutral） | 映射表待 UE 侧确认（YYchainsAw）；未映射 ID 应由 UE 兜底为 neutral 表现 |
| 动作 `gesture.*` | 10 项（cheerful_idle/small_wave/enthusiastic_nod/think/look_away/fold_arms/step_closer/nod/look_around/ready_weapon） | 同上 |
| 表情 `face.*` | 9 项（bright_smile/excited/gentle_smile/concerned/shy/playfully_annoyed/serious/thoughtful/neutral） | 同上 |
| 行为 behaviors | 11 项（follow/move_to/observe/inspect/interact/pickup/rest/wait/express/self_talk/alert_player） | UE 当前支持 Follow / CastAbility / HoldAbility 及 `when: state_entered` 触发结构，其余按未制作处理 |
| 战斗事件 | 6 项（player_hp_critical/boss_stun_near/boss_stunned/boss_enraged/companion_mp_low/boss_defeated） | 由 UE 战斗系统上报，逐事件联调核对 |
| 生活事件 | 6 项（region_first_entered/weather_changed/gift_given/companion_recovered/player_protected_companion/promise_kept） | `gift_given` 已实测通路（契约 §4 样例），其余随 UE 上报核对 |

## 6. 验收矩阵（端点 × 状态 × 实测）

| 链路 | 协议版本 | 状态 | 实测样例（2026-10-08，端口 8000） |
|------|----------|------|-----------------------------------|
| 文本对话 `POST /v1/companion/chat` | 0.1 | 已实现·启用 | 200 / 2328.8ms（LLM，`source: "llm"`，关系阶段 distant/疏远） |
| 玩家战斗指令 `POST /v1/tactical/command` | 0.2 | 已实现·启用 | 200 / 19.3ms（rule，actionable；reason_codes 含 PLAYER_HP_CRITICAL） |
| 心跳自主行为 `POST /v1/agent/step` | 0.3 | 已实现·启用 | 200 / 31.8ms（自主 `observe` 指令，`expires.before_seconds=10.0`） |
| 世界事件 `POST /v1/world/events` | 0.3 | 已实现·启用 | 200 / 27.5ms（gift_given，relationship_delta=3） |
| 执行回执·单条 `POST /v1/tactical/executions` | 0.2 | 已实现·启用 | 202 / 4.1ms（落盘 `executions/aesir/20261008.jsonl`） |
| 执行回执·批量（v0.3） | 0.3 | 已实现·启用 | 202 / 3.5ms（count=2） |
| 语音指令 `/v1/voice/command`、转写 `/v1/speech/transcribe` | 0.1 | 已实现·启用 | mock / faster_whisper 链路测试覆盖 |
| 未登记/跨游戏角色 | — | 拒绝（设计行为） | 404 / 19.3ms，不回退 |
| 请求体违规 | — | 拒绝（设计行为） | 422 / 1.5ms（`extra="forbid"`） |
| L0 游戏访问完整链路 / 未声明事件 | — | 拒绝（S4 门控） | 403 结构化 `reason_code`（demo-vn 实测，见 #38 验收记录） |
| 治疗/护盾等未制作能力下发 | — | 未制作·UE 拒绝 | UE `ValidateOrder` 失败 → `rejected` 回执（§4 口径） |
| 调试台 `GET /v1/console/state` `/ui` | 0.3 | 已实现·启用 | 单页 HTML + 状态 JSON |

## 7. 响应时间 / SC-011 采样口径（先定义，T33 定稿）

> SC-011 原文：战斗场景下从玩家发出指令到 NPC 开始响应的等待时间，玩家可感知为「即时」。
> 此处先固定**采样点、样本与临时通过口径**；硬指标量化由 T33（FIX-04 / Issue #42）定稿后回写本节。

- **采样点（两端打戳）**：
  - 起点 `t0`：UE 玩家确认输入（`ParseCommand` 请求发出 / 语音 `ParseVoiceCommand` 请求发出）的本地时间戳；
  - 终点 `t1`：UE 收到 `OnCommandParsed` / `OnTacticalResolved` 回调且 Alice 开始表现（首个可见动作/语音/动画触发）的本地时间戳；
  - 服务端分段：请求到达 → 响应发出的耗时由日志/`X-Request-Id` 关联核对，用于区分「网络+排队」与「服务决策」。
- **样本**：同一场 boss 遭遇战内混合采样 **≥ 30 次**玩家指令（文本与语音各半，覆盖普攻/技能/治疗/跟随意图），
  记录每次 `t1 - t0` 与服务端耗时。
- **临时通过口径（待 T33 确认）**：本地回环规则链路（tactical/command）参考实测 **≈20ms 级**；
  「即时」感知口径暂定 **p95 ≤ 300ms**（不含 LLM 生成式回复；LLM 链路单独统计，参考实测 chat ≈2.3s）。
- **历史测试数量按 commit 标注**：本仓 CHANGELOG 每个里程碑条目均带「测试锚点 N passed + M skipped @ commit」，验收时按提交号对齐。

## 8. 同步记录

- SDD / todo / 开发日志的旧状态已随本任务同步：
  [todo.md](../planning/todo.md) EXT-04 标记完成、[game-design-doc v0.2 §6.5](../planning/game-design-doc-v0.2.md) 同步勾选、
  [CHANGELOG](../../CHANGELOG.md) 新增 T18 里程碑、[开发日志 2026-10-08](../logs/2026-10-08.md) §8。
- 范围边界（Issue #31）：本任务只收口现有服务与当前 UE 能力；端口、批量回执、多角色路由不重新开发；
  不新增对话 RL、流式 ASR/VAD 与未确认技能。
