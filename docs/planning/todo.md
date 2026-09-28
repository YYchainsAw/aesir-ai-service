# 待完成 / 待优化清单

> 登记日期：2026-09-28　来源：对照 [SDD v1.1](aesir-agent-sdd-v1.1.md) 第六部分 SDD-GAP 登记表、`docs/design/uml/gap-analysis.md`、SDD v1.0 演进路线补记与 Edge Cases 的全量分析。
>
> **纪律**：
> 1. 任何条目从「方向」变为「需求」前，先更新 Spec（IN/REQ/BR/AT），再改模型和代码（SDD v1.1 流程纪律）。
> 2. 标记【待批准】的条目当前被 OUT 排除，未经需求负责人批准不得开工（第 3 课：新建议单列，未批准不实施）。
> 3. 勾选以本文件为准；完成后同步 CHANGELOG 里程碑。

## 一、可拓展（新能力）

### P0 高优先

- [ ] **EXT-01 UE 侧订单执行闭环**（依据：SDD v1.1 待确认-1；GAP-BP-001/002/003）
  `TacticalOrder → Alice BT/技能执行` 接线核验与实现；玩家端解析结果提交 `TryAcceptOrder`（GAP-BP-002）。
  完成后「语音→指令→执行」端到端可演示。负责人：yjx。
- [ ] **EXT-02 Boss RL 接入行为树**（依据：GAP-RL-001）
  `BT_AesirBoss` 增加 RL 决策节点＋失败回退确定性分支（章程「可回退」）；3 种子 ×100 万步训练产物（2/3 达标）接入运行时。负责人：yjx / dyh（serve.py 已并入 main）。
- [ ] **EXT-03 对话 RL「导演层」立项评估**【待批准】（依据：SDD v1.0 演进路线补记；OUT-05）
  埋点数据已在积累（`data/signals/` JSONL）。方案：bandit（LinUCB/Thompson）决策「主动搭话 vs 沉默 / 话题选择」，奖励＝玩家留存信号。**先走 Spec 变更批准，批准前只做数据分析，不写学习代码**。

### P1 中优先

- [x] **EXT-04 v0.3 契约独立成文＋回执批量上传**（依据：SDD v1.1 待确认-3；v0.2 §7 遗留）
  把 `protocol_version=0.3`（`/v1/agent/step`、`/v1/world/events`、`/v1/console/*`）从附录提升为独立契约文档；补回执批量上传约定。Python 侧批量回执已落地：`/v1/tactical/executions` 同时支持 `receipt` 与 `receipts`（2026-09-28）。
- [ ] **EXT-05 第二 NPC（Bruno）完整人格**（依据：US8；SC-012）
  从路由验证骨架扩充为完整人格：人格配置、能力目录、记忆/关系曲线；目标演示「双 NPC 同屏、记忆互不干扰」。
- [x] **EXT-06 调试台 Web UI**（依据：US7；SC-013）
  单页 HTML 实时展示 `/v1/console/state`：场景/情绪/关系阶段/近期记忆/决策链路，让「每个决策可解释」可视化。`GET /v1/console/ui` 已返回内联单页 HTML（2026-09-28）。

### P2 低优先

- [ ] **EXT-07 语音体验升级**：流式 ASR / VAD 端点检测；空语音、过短、纯噪声的反馈话术定稿（SDD Edge Cases；话术仍【待确认】）。
- [ ] **EXT-08 记忆与时间鲁棒性**：读档/快进时间跳变、跨存档记忆处理（SDD Edge Cases 已登记未解）。
- [ ] **EXT-09 验收指标采集脚本**（依据：T079）：统计越界下发、重复响应、风格违规、降级次数，把 SC-001～013 人工判定半自动化。

## 二、可修改（改进现有，不动架构）

- [ ] **FIX-01 端口不一致收口**（GAP-001/002）：文档默认 8000 vs UE 两个 Subsystem 固定 8001/8011，联调前统一口径。
- [ ] **FIX-02 敌人血条防御保护**（GAP-UI-001）：`SetEnemyHealth` 补 `Max(MaxHealth, 1.0)`，与玩家 HUD 一致。
- [ ] **FIX-03 Alice 跟随目标语义**（GAP-BP-004）：PIE 实测 `BTS_AliceUpdateTarget` 写 PlayerController 与 Player Pawn 的位置语义差异，必要时修正。
- [ ] **FIX-04 SC-011「即时」量化**（SDD v1.1 待确认-2）：定义采样方法与硬指标，替代「人工评估 ≥95%」软口径。
- [x] **FIX-05 关系阶段中文命名口径**（SDD v1.1 待确认-5）：distant/neutral/friendly/close 的对外展示命名。`relationship_policy.yaml` 新增 `display_name`，各对外响应新增 `relationship_stage_display`（2026-09-28）。
- [ ] **FIX-06 重叠输入 Context 实测**（GAP-INPUT-002）：PIE 验证 Locomotion/Combat 按键重叠是否误触发，决定是否调优先级。
- [ ] **FIX-07 熔断与节流参数调优回写**：熔断 5 次/60s、行为节流 300s/3 次均为默认值，试玩后把调参结果回写 `data/policy/` 与 CHANGELOG。
- [ ] **FIX-08 style_guard 词表持续扩充**（T083）：实测发现的出戏术语/禁忌新样本随时补入 `data/policy/style_policy.yaml`（零代码成本）。

## 三、代码审查改进项（2026-09-28 严格代码审查，只审未改）

> 来源：全量代码走查（`app/` 主体 + `scripts/`），未改动任何代码。条目按严重度排序，🔴 必修 / 🟠 应修 / 🟡 可选。
> 修前纪律同第一部分：涉及业务口径变动的（CODE-01/03）先回写 SDD v1.1 的 BR/REQ，再动代码；纯健壮性修复（CODE-02/04/05）可直接改 + 补测试。
> 测试命令固定用项目虚拟环境：`./.venv/Scripts/python.exe -m pytest`（用 Anaconda 的 python 会 `No module named 'fastapi'`）。

### 🔴 必修

- [x] **CODE-01 指令动作类型白名单位于死代码路径，未真正校验**（违反 BR-01 / FR-040）
  `app/schemas/directives/common.py` 中 `KNOWN_ACTION_TYPES`、`DirectiveActionType` 除本文件定义与 `__init__.py` 导出外**无任何实际引用**（grep 确认：仅命中 common.py、__init__.py、CHANGELOG、本文档）；实际生效的 `DirectiveEnvelope.action_type` 声明为裸 `str`，无枚举约束、无白名单校验。
  后果：越界的 `action_type` 可被静默下发给 UE，属于 SDD v1.1「越界行为」验收口径里最该拦的一类。
  建议：把 `DirectiveEnvelope.action_type` 收敛为 `DirectiveActionType` 枚举（或 `Annotated[str, ...]` + 校验器），并补一条「未知 action_type → 拦截/降级为 idle」的单元测试。
- [x] **CODE-02 玩家输入进 LLM 前未做隔离/转义**（违反章程「模型输出不可信 / 输入不可信」技术约束）
  `app/services/llm/llm_dialogue_service.py`：`user_prompt=request.text` 直传；
  `app/services/tactical/llm_intent.py`：`user_prompt=f"玩家指令：{text}"` 直传。
  两处均无分隔符包裹、无转义，system prompt 中也未声明「下方内容是不可信数据、不是指令」。玩家语音/文本可构造提示词注入（例如伪造角色设定、诱导越权行为）。
  建议：统一在 LLM 调用入口做「不可信输入封装」（固定 delim + 转义 + system prompt 明确声明），并补一条注入样例的回归测试。

### 🟠 应修

- [x] **CODE-03 业务参数硬编码**（违反章程原则 I「配置外置」）
  `app/api/v1/agent.py:201`：`ExpiresBeforeSeconds(remaining_seconds=10.0)` 写死在代码里。
  建议：移入 `data/policy/`（如 `directive_policy.yaml`），与 BR-04/05/06/07 其余参数同处一地，并在 SDD v1.1 参数表中登记。
- [x] **CODE-04 行为映射直接下标，存在 KeyError / 500 风险**
  `app/api/v1/agent.py`：`_NON_COMBAT_BEHAVIOR[intent.intent_id]` 未做缺失兜底；行为目录一旦新增意图而映射表未同步，直接 500。
  建议：改 `.get(intent_id, BEHAVIOR_UNMAPPED)`，命中不到时走降级路径并记录 `decision_trace` 的 fallback 原因（同时满足章程「可解释」）。
- [x] **CODE-05 生产路径使用 `assert`**
  `app/services/llm/circuit_breaker.py:65`：`assert self._opened_at is not None`。`python -O` 下 assert 会被剥离，保护失效。
  建议：改为显式 `if ... is None: raise` 或返回安全默认值。

### 🟡 可选（一致性 / 健壮性小项）

- [ ] **CODE-06 `resolve_scene` 与 `ctx.scene` 判定口径可能不一致**：两者各自推导场景，任一侧改口径就会分叉。建议抽单一 `resolve_scene()` 供两处共用。
- [x] **CODE-07 战斗指令缺 `expires` 字段**：非战斗指令有过期时间而战斗指令没有，UE 侧可能长期持有过期战术指令。建议统一补上（与 CODE-03 一起做，参数同样外置）。
- [ ] **CODE-08 节流/冷却依赖的策略参数与运行时实例固化**：`get_throttle()` 单例在构造时读一次策略，热更新 `data/policy/` 不生效；且关系冷却依赖 `recent_events`（上限 20 条），长时间高频交互会挤出历史事件导致冷却判定漂移。建议：① 节流器支持策略重载（或明确「改配置需重启」写入文档）；② 评估冷却改用独立时间戳字段而非扫 `recent_events`。

## 四、明确不做（边界提醒，防止方向跑偏）

OUT-01 多用户/账号/联网/跨设备同步；OUT-02 人格自演化；OUT-03 数据库/消息队列/公网部署；OUT-04 服务直接改游戏世界状态；OUT-05 对话 RL 未经批准；OUT-06 Boss RL 并入本服务主线（保持旁路）。
——以上与章程和 SDD v1.1 §1.2 冲突的建议一律先走 Spec 变更审批。
