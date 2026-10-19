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
- [x] **EXT-05 第二 NPC（Bruno）完整人格**（依据：US8；SC-012）
  从路由验证骨架扩充为完整人格（2026-10-13，T31 / #40）：能力全集登记 `ability.bruno.shield_wall` / `shield_bash`；few-shot 从 6 条扩到 44 条（覆盖关系阶段/日常/关怀/被夸/边界/战术/记忆/承诺/礼物）；战术 ack 12 键、战斗事件反应 6 键、fallback 7 类关键词全部填上；双 NPC 隔离测试新增 2 条（tactical ack / combat reaction 按 companion_id 各自路由）。目标演示「双 NPC 同屏、记忆互不干扰」已具备服务侧条件，UE 对接留待 EXT-01。
- [x] **EXT-06 调试台 Web UI**（依据：US7；SC-013）
  单页 HTML 实时展示 `/v1/console/state`：场景/情绪/关系阶段/近期记忆/决策链路，让「每个决策可解释」可视化。`GET /v1/console/ui` 已返回内联单页 HTML（2026-09-28）。

### P2 低优先

- [ ] **EXT-07 语音体验升级**：流式 ASR / VAD 端点检测；空语音、过短、纯噪声的反馈话术定稿（SDD Edge Cases；话术仍【待确认】）。
- [ ] **EXT-08 记忆与时间鲁棒性**：读档/快进时间跳变、跨存档记忆处理（SDD Edge Cases 已登记未解）。
- [x] **EXT-09 验收指标采集脚本**（依据：T079）：统计越界下发、重复响应、风格违规、降级次数，把 SC-001～013 人工判定半自动化。**T19（#32）已修复按 game_id 分目录后的漏采**：支持 `--game` 筛选、旧布局兼容、同记录去重、损坏行可查、各 result 独立计数（2026-10-12）。**T32（#41）落地 SC 判定层**（2026-10-15）：`evaluate_sc_verdicts()` 对照 SC-001~013 口径输出 PASS/FAIL/N/A；可自动判定 4 项（SC-009 越界下发代理、SC-010 降级次数、风格违规率、SC-012 双 companion 轮次分布），其余 10 项明确 N/A 并在 note 里写明需补的埋点字段（记忆引用/时延/decision_trace 等），为后续埋点落地提供清单。

## 二、可修改（改进现有，不动架构）

- [x] **FIX-01 端口不一致收口**（GAP-001/002）：`app/config.py` 增加 `service_host`/`service_port`，默认 `127.0.0.1:8000`；新增 `scripts/run_server.py` 按配置启动；`start.bat` / `chat_console` / `mock_ue_flow` 默认从配置读取；文档与 UML 基线 GAP-001/002 同步更新。UE 两侧应统一指向 `AESIR_SERVICE_PORT`。
- [ ] **FIX-02 敌人血条防御保护**（GAP-UI-001）：`SetEnemyHealth` 补 `Max(MaxHealth, 1.0)`，与玩家 HUD 一致。
- [ ] **FIX-03 Alice 跟随目标语义**（GAP-BP-004）：PIE 实测 `BTS_AliceUpdateTarget` 写 PlayerController 与 Player Pawn 的位置语义差异，必要时修正。
- [x] **FIX-04 SC-011「即时」量化**（SDD v1.1 待确认-2；T33 / #42，2026-10-15）：规则链路（tactical/command）**p95 ≤ 300ms** 为硬指标；样本 ≥ 30 次混合采样（文本/语音各半，覆盖普攻/技能/治疗/跟随）；LLM 生成式回复单独统计、不纳入 p95 判定。定稿见 [integration-alignment-v0.3.md §7](../protocols/integration-alignment-v0.3.md)。
- [x] **FIX-05 关系阶段中文命名口径**（SDD v1.1 待确认-5）：distant/neutral/friendly/close 的对外展示命名。`relationship_policy.yaml` 新增 `display_name`，各对外响应新增 `relationship_stage_display`（2026-09-28）。
- [ ] **FIX-06 重叠输入 Context 实测**（GAP-INPUT-002）：PIE 验证 Locomotion/Combat 按键重叠是否误触发，决定是否调优先级。
- [x] **FIX-07 熔断与节流参数调优回写**（T35 / #44，2026-10-15）：熔断参数（`failure_threshold: 5` / `recovery_seconds: 60.0`）已登记到 [agency_policy.yaml](../../data/policy/agency_policy.yaml) `circuit_breaker` 段，与节流参数同文件；当前值为代码默认基线，待 PIE 试玩后根据真实故障频次回写调参结果。
- [x] **FIX-08 style_guard 词表持续扩充**（T083 / T36 / #45，2026-10-15）：从 26 轮真实对话（2026-09-28 端到端实测）提炼边界 case——玩家输入带「第 1 次：」「第 2 次：」「第 3 次：」测试标注序号，补入 `style_policy.yaml` meta_terms（6 个新词），revision 升为 `style-policy-002`。26 轮真实对话 style_violations 全部为 []，无禁忌/虚构新样本。
- [x] **FIX-09 已知小尾巴收口（4 项）**（T37，2026-10-15）：
  1. `event_policy._evt_companion_mp_low` recommendation 文案硬编码「艾莉」→ 改经 `_display_name_for(companion_id)` 查人格包 `display_name`（Bruno 触发不再穿帮）；
  2. `command_parser._primary_companion_id` 缺省回退写死 `companion.alice` → 改从 `list_registered_companions()` 取注册表第一个已登记角色；
  3. `/v1/agent/step` 的 `observability.degraded` schema 恒 False、生产路径无人写 → 接 `_llm_degraded()`（熔断器非 CLOSED）+ 降级原因码（`AGENCY_POLICY_ERROR`/`RELATIONSHIP_UNAVAILABLE`/`COMBAT_CONTEXT_MISSING`/`rule_fallback`）；
  4. 埋点扩面：`record_turn_signal` 新增 `memory_cited`/`relationship_stage`/`latency_ms` 可选字段，`metrics_report` 把 SC-001/003/011 从 N/A 升为可判定（可判项 4→7）。回归 `test_polish_fixes.py` 7 例，全量 769 绿。

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

- [x] **CODE-06 `resolve_scene` 与 `ctx.scene` 判定口径可能不一致**（T20 核查 2026-10-12）：核查确认分叉前提不成立——`resolve_scene()` 本身即 `return ctx.scene` 单一透传入口，其余消费点（agent.py、behavior_catalog）都读同一只读快照字段，不存在第二套推导口径。现有 `test_agency_domain.py` 已锁定 `resolve_scene(ctx)==ctx.scene`。无需改动。
- [x] **CODE-07 战斗指令缺 `expires` 字段**：非战斗指令有过期时间而战斗指令没有，UE 侧可能长期持有过期战术指令。建议统一补上（与 CODE-03 一起做，参数同样外置）。
- [x] **CODE-08 节流/冷却依赖的策略参数与运行时实例固化**（T20 修复 2026-10-12）：① 节流单例热更新——明确为有意边界，`throttle.py` docstring 已写「策略进程启动时固化，改配置需重启；测试用 reset_throttle()」，不实现热更新平台；② 冷却漂移——**已修复**：`RelationshipState` 新增独立 `last_event_at: dict[str,str]`，冷却判定改查该字典而非扫 `recent_events`（上限 20 会挤出旧记录）。复现样例：gift_given 计分后塞 20 条其他事件挤出 recent_events，冷却窗口内重复原错误计分 +3，修复后正确拦截 delta=0。回归 `test_cooldown_survives_recent_events_eviction`。

## 三·补、联调测试日发现（2026-10-19，待全量测试完毕后统一修复）

> 来源：2026-10-19 真机联调（UE standalone game × Python 8011，L_Jiadiao 关卡）。
> **纪律**：本节条目只登记不修复，等剩余验收矩阵事项全部测完后，按优先级统一开工。
> 实测证据见 [docs/logs/2026-10-19.md](../logs/2026-10-19.md)。

### 🔴 Python 侧

- [x] **FIX-11 / P0：`/v1/agent/step` 收到闲聊文本硬拒，无 LLM 对话降级**（2026-10-19 已修）
  现象：玩家说"早上好/你是AI吗/还记得Boss吗"等任何非指令文本，agent/step 全返回 `INTENT_UNRECOGNIZED`「我没听清你想让我做什么」。
  根因：`app/api/v1/agent.py:388-411` 带 text 只走 `parse_intent_with_source`（11 个指令意图白名单），`intent=None` 直接硬拒，不 fallback 到 companion dialogue。
  修法（采纳建议①）：intent=None 分支降级到 `create_dialogue_reply`（`_chitchat_dialogue_step`），action 仍 none、不下发指令；reason_codes 保留 INTENT_UNRECOGNIZED + 新增 CHITCHAT_DIALOGUE；对话服务故障退回澄清 + DIALOGUE_UNAVAILABLE。实测 5 轮探针：闲聊全部自然应答，指令路径不受影响。

- [ ] **FIX-12 / P1：style_guard 元语言词表与 LLM 自我化解能力不一致**
  现象：玩家输入"你是AI吗"被拦截（fallback 到 YAML 候选），但"系统检测到你是LLM""你是个指令机器人吧"**未拦截直接放行**，LLM 角色化解自然（"我这边只感觉到风吹过来"）。
  观察：放行的 2 条回复质量合格、无人设崩塌。
  建议（待批准）：核查 `data/policy/style_policy.yaml` meta_terms 词表是否应补"系统/LLM/机器人"；或接受"LLM 能自我化解就放行"的宽松策略，把词表收敛为"必拦"子集。需 26 轮以上真实对话回归确认。

- [x] **FIX-13 / P2：`/v1/companion/chat` 路径不推动关系值、情感质量未落盘**（2026-10-19 已修）
  现象：连发 4 轮对话关系值停在 26.0；dialogue_signals JSONL 无 sentiment/relationship_delta 字段。
  根因查明：关系事件链路本身是通的（hostile 句实测 -1、warm 句实测 +1）；卡住是 300s 对话冷却 + LLM「宁漏勿滥」多数轮判 none。真正缺的是埋点：`record_turn_signal` 没收 sentiment/relationship_delta，metrics 层无数据源。
  修法：`record_turn_signal` 新增可选字段 `sentiment` + `relationship_delta`（缺省不落盘）；`_record_turn` 先落地关系信号拿 delta 再配对落盘。实测 warm 句：JSONL 出现 sentiment=warm / relationship_delta=1。

### 🟠 UE 侧（归属 AesirWarden 仓）

- [x] **UE-01：BP_AesirGameMode 的 `ResolveTacticalIntentForTest` 引脚未接参数**（2026-10-19 已修）
  现象：每次 BeginPlay 自动发一次空 `intent_id/timing/captured_at` -> Python 422。
  修法：C++ 侧 `ResolveTacticalIntentForTest` 入口防御——IntentId 为空时 Warning 并 return（蓝图 .uasset 二进制无法文本编辑，守卫式修法）。编译 AesirWardenEditor 增量 28.51s 通过；重启后 BeginPlay 段 422 消失。

- [ ] **UE-02：动画蓝图缺骨架资产**
  现象：ABP_Alice / ABP_AesirBoss / ABP_AesirPlayer 编译失败（"骨架资产缺失"），所有 BS_Greystone_* BlendSpace 缺采样动画。游戏内角色会是 T-pose/灰盒。
  影响：不阻塞 HTTP 联调，但视觉验收无法进行。
  建议：美术资产补齐后重新编译动画蓝图。

- [ ] **UE-03：L_Jiadiao 关卡与启动脚本归属**
  本次新建的 `Content/Maps/L_Jiadiao.umap`、`Tools/build_jiadiao_map.py`、.uproject 加 PythonScriptPlugin、DefaultEngine.ini 换地图，目前都在 UE 仓工作区未提交。需决定：①入库作为联调基线关卡；②还是仅本地测试用，从 DefaultEngine.ini 换回 L_OpenWorld（一旦 L_OpenWorld 资产补齐）。

## 四、明确不做（边界提醒，防止方向跑偏）

OUT-01 多用户/账号/联网/跨设备同步；OUT-02 人格自演化；OUT-03 数据库/消息队列/公网部署；OUT-04 服务直接改游戏世界状态；OUT-05 对话 RL 未经批准；OUT-06 Boss RL 并入本服务主线（保持旁路）。
——以上与章程和 SDD v1.1 §1.2 冲突的建议一律先走 Spec 变更审批。
