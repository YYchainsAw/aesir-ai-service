# 历史验证与决策记录

本页于 2026-10-19 合并原 10 篇开发日志、旧需求/策划中的有效决策和 CHANGELOG 验证摘要。原日期、样本与测试数按当时记录保留；没有重新运行服务、测试、训练或 UE，也没有补造已丢失的原始输出。旧日志的推送代理、进程号、会话收尾和重复文件清单不再维护。课程建模过程见 [UML 入口](../design/uml/README.md)，当前需求见 [SDD v1.1](../planning/aesir-agent-sdd-v1.1.md)，后续工作见[未决清单](../planning/todo.md)。

<a id="scope"></a>
## 证据范围

| 类别 | 记录能支持什么 | 不能据此推断什么 |
| --- | --- | --- |
| 单元/回归测试历史输出 | 当时版本、桩和数据条件下的自动检查 | 当前 HEAD 全量已跑、真实模型质量、UE 实际技能完成 |
| Python HTTP / console / Godot 抓样 | 指定客户端、后端和端点的响应 | 全部样本都来自 UE，或真实战斗闭环已验收 |
| E 盘临时 UE 工程心跳 | 当日临时工程至服务的连通与状态更新 | D 盘正式 UE 工程内容、动画、玩家 UI 和技能执行均已通过 |
| 模拟器训练/选模汇总 | 对应模拟器、策略和样本条件下的记录 | 独立测试、UE BT 战绩或正式部署身份已自动核验 |

原 `data/runtime/`、记忆、模型等运行产物被 Git 忽略，只在原本机保管；本页是已有记录的整理，不是完整原始数据包。缺少 commit 的条目标“原记录未给出”，不按后续提交号倒填。

<a id="decisions"></a>
## 既有决策与边界

| 日期 / 来源 | 决策 | 当前解释 |
| --- | --- | --- |
| 2026-09-13 项目章程与定位升级 | NPC 从语音解析扩展为人格、记忆、关系、非战斗自主行为与只读查证 | UE 仍是世界状态和执行的唯一权威；服务输出受限建议，模型输出不视为可信指令 |
| 2026-09-22 用户拍板、历史实现补记 | 关系可由世界事实事件和对话情感信号共同驱动 | 普通闲聊可为 none，不因每次对话必加分；不是人格自演化批准 |
| 2026-09-30 旧策划已记录的四项裁决 | 一进程一游戏、多实例隔离；用 field_validator 校验能力子集；S5后置；Bruno随S2迁移 | 同进程多 profile、动态场景枚举、通用方言映射不在当前实现；S5未完成前不接第三方资产，现有 L0/L3 两档不等于完整外部资产审核 |
| 2026-10-15 T33 / FIX-04 / #42 | SC-011 规则链路 p95≤300ms，样本≥30，UE输入到NPC开始实际表现；文本/语音混采，生成式LLM回复单列 | 这是历史已记录的验收口径，未附该正式采集的通过结果；不把 HTTP 单点耗时替代端到端时延 |
| 2026-10-19 FIX-10、提交46feea3 | Python默认端口从8000改为8011，与UE两Subsystem对齐 | 8000保留为旧抓样事实；Boss独立推理仍8012；使用读取Settings的启动入口 |
| 本轮跨仓对照 | UE已确认Boss连续3次错误切BT且本场保持、完整合法响应才清零；NPC技能数量待定、按条件约束 | 来自UE需求目标，不能改写成Python已实现/已批准单技能；NPC LLM默认5次/60秒熔断另计 |

原章程的模块隔离、外部输入不可信、UE唯一权威、契约/测试、可解释回退、单一指令信封和简单优先等约束，以及旧 FR/SC 的有效目标，已统一由 SDD v1.1 承接；本页不保留第二份需求基线。旧任务 T001～T088 的未勾选状态不能用来否认后来已发生的实现与回归。

<a id="regression"></a>
## 自动检查与实现修正的历史记录

下表保留日志/CHANGELOG的结果，不作为本次复跑结果。不同日期有合并、测试选择或计数差异；没有完整机器记录的地方不强行拼成单调增长曲线。

| 日期 | 版本或任务 | 已记录修正 / 验证 | 历史输出与限制 |
| --- | --- | --- | --- |
| 2026-09-24 | 原记录未给统一commit；US8/T083/T084 | 角色路由与状态隔离、style_guard、LLM共享熔断 | 当日里程碑643→659→669 passed、2 skipped；669为当时末次锚点；原开发日志另记文档整理，不是代码验证 |
| 2026-09-28 | d453e07；CODE-01/02 | action_type真正白名单校验；LLM不可信输入封装；回归覆盖拒绝/降级、分隔符与转义 | 之后批次A同时完成CODE-03/04/05/07：有效期配置化、映射兜底、显式异常、战斗expires；原输出 `711 passed, 2 skipped, 7 warnings in 13.10s` |
| 2026-09-29 | S0、S1；原日志未给统一commit | memory/relationship/lore按game命名空间、唤醒词外置、ack/事件角色路由、回执/信号透传game_id | S0原输出709 passed / 7 warnings；S1原输出712 passed / 7 warnings；不据此修改此前711+2 |
| 2026-09-30 | 15cfc55（S1提交）；FIX-01 | game_id隔离提交；统一Settings启动入口和可配置端口，当时默认8000 | S1记录 `714 passed, 2 skipped, 7 warnings in 18.18s`；另有726+2历史锚点，但原日志未给出该次完整命令/commit |
| 2026-10-08 | b7ac0e5 / S2 / #36 | Alice/Bruno从单YAML迁为8文件包，逐字段等价检查、归属校验 | 730 passed, 2 skipped；三处预期数据差异单列：profile_version、game_name上移、Bruno空节 |
| 2026-10-08 | 5f9727e / S3 / #37；S4 / #38 | 游戏档案与demo-vn；L0/L3和事件声明门控 | 736→745 passed, 2 skipped；demo-vn端口8002实抓chat200、tactical403、跨游戏404、已声明事件200/未声明403；不等于第三方资产守卫 |
| 2026-10-12 | T19 / #32 | metrics_report修复新game目录漏采；旧布局兼容、物理重复行去重、坏行可查 | 新增10例；755 passed, 2 skipped。真实旧数据回执2→5、轮次24→26、fallback0→1；支持按game筛选 |
| 2026-10-12 | 199e22f / T20 / #33、T34 / #43 | 关系冷却改独立last_event_at，不再依赖易被挤出的20条recent_events；resolve_scene分叉核查不成立 | 756 passed, 2 skipped；复现gift_given后挤出20条、30秒内重复：修前delta+3，修后0；70秒后+3。策略改动需重启为明确边界 |
| 2026-10-13 | T31 / #40，原日志未给commit | Bruno44条few-shot、2能力、12ack、6战斗反应、7类fallback；角色路由隔离 | 隔离10 passed；战斗相关30 passed；全量原文“756 passed（改前754+新增2）”，与前日基线不同，未经复核不擅改；服务声明不证明UE已制作Bruno技能 |
| 2026-10-15 | T32 / #41；T33 / #42 | 指标脚本SC判定层；SC-011口径定稿 | 脚本16 passed；全量历史762 passed，CHANGELOG记2 skipped；SC代理含义见下节 |
| 2026-10-15 | T21 / #34、T22 / #35 | health增加service_commit，复现指引及26轮LLM证据整理 | health单例通过；全量原记762 passed；health实抓335acb6。后续记录不得冒用此值为当前commit |
| 2026-10-15 | T35/#44、T36/#45 | 默认熔断值登记至策略、style-policy-002补6个测试序号词 | style_guard16 passed；全量762 passed；登记不是PIE调优。熔断实际读取Settings；YAML登记不代表改该段立即生效 |
| 2026-10-15 | b30f4cc / T37 / FIX-09 | Bruno展示文案、缺省角色路由、degraded观测、可选memory/stage/latency字段 | 新增7例，全量历史769 passed；原CHANGELOG锚点769 passed+2 skipped。生产只接memory_cited/relationship_stage，未传latency_ms |
| 2026-10-19 | 46feea3 / FIX-10 | 端口默认8011；读取Settings启动、不带port时8011 | health_commands 12 passed；原记录health200、service_commit=b30f4cc。单组测试不能称a2dd426全量已跑 |

CODE-01～08对应的已解决或核查为非缺陷部分已从日常清单移除；未把“过期问题描述”继续当作当前缺陷。已完成 EXT-04 独立v0.3/批量回执、EXT-06调试台、FIX-05中文阶段名也保留其交付事实，2026-09-28对应里程碑原记678 passed+2 skipped，与同日711+2为不同检查快照。

<a id="http-20261008"></a>
## 2026-10-08 Python HTTP抓样（T18 / #31）

两仓登记为 `aesir-ai-service@75ac7a3` / `AesirWarden@facba39`；当时NPC8000、Boss8012，UE两个Subsystem8011。样例由脚本请求运行中服务取得，不是UE完整战斗录制。契约定义见[联调对齐表](../protocols/integration-alignment-v0.3.md)。

| 端点 / 情形 | 当时结果 | 解释 |
| --- | --- | --- |
| POST /v1/companion/chat，LLM | 200，2328.8ms | 单次真实对话耗时 |
| POST /v1/tactical/command | 200，19.3ms，actionable major_heal | 服务建议；不能证明UE已制作治疗技能 |
| POST /v1/agent/step | 200，31.8ms，自主observe | 服务侧指令输出 |
| POST /v1/world/events，gift_given | 200，27.5ms，delta=3 | 服务关系更新 |
| POST /v1/tactical/executions | 单条202/4.1ms，批量202/3.5ms | 回执受理；不证明服务执行动作 |
| 未登记角色 / 请求体违规 | 404 / 422 | 拒绝路径样例 |
| demo-vn实例，8002 | chat200、tactical403、跨游戏404、已声明事件200/未声明403 | L0能力门控样例 |

当时UE支持能力记录仅basic_attack/explosion；Python治疗/护盾属于声明和建议，不能把HTTP actionable写为游戏已执行。端口现已8011，原8000样例无需追写成新实测。

<a id="llm-26"></a>
## 2026-10-15整理的26轮真实对话证据（T22 / #35）

原数据时段为2026-09-24～10-08，生成commit未逐轮登记；不是10-15新运行26轮。

| 原数据位置（相对data/runtime/dialogue_signals） | 轮次 / 日期 | 客户端与后端 |
| --- | --- | --- |
| companion.alice.jsonl（旧布局） | 24，09-24～09-28 | console / Godot / latency-probe历史样本 |
| aesir/companion.alice.jsonl | 1，10-08 | T18 HTTP抓样，LLM |
| demo-vn/companion.narrator.jsonl | 1，10-08 | T18第二游戏，fallback |
| 合计 | 26 | 25 LLM、1 fallback；不能统称26轮UE实测或26轮LLM |

原统计复读1/26（3.8%）；topic_continued已标16轮，其中true5轮（31.25%）。旧24轮session分布：console-3078bf4f=9、console-eab13da6=4、sess-godot-001=3、latency-probe=3、godot-e2e-001=2、godot-bridge-001=1、无session=2。

原风格统计为0条，旧摘要将26轮字段都记为 `[]`；当前mock/fallback的“未校验”语义为null，不能把fallback样本算作真实LLM守门验证。0条只说明保留输出未记录违规，不能证明原始LLM从未触发过内部重试/拦截，也不能据此证明守门层对所有违规有效；历史16例合成测试提供另一个有限范围的验证。

保留的典型样例：09-24玩家“你好，艾莉”→“你好，旅行者。今天打算往哪边走？”；复读标记样例是“我们这是第一次说话，记住我。”→“第一次说话啊……那行，我记住了。旅行者，往后路上多指教。”；10-08 narrator fallback对“你好”回“你好。”。原文“回复被压缩”样例不作为完整原始证据。

原记录仍待补：真人WAV/faster-whisper质量与耗时、style_guard真实拦截/重试/回退全链、Bruno真实LLM对话。后续若补样本，另记运行版本、端点与来源，不把旧数据换名为新实测。

<a id="metrics-boundary"></a>
## 指标脚本的证据边界

历史 `metrics_report` 已修漏采并增加PASS/FAIL/N/A，但这些字样沿用了SC编号，不能直接判正式需求通过。

| 当前脚本代理 | 真正仍需的证据 |
| --- | --- |
| rejected/expired/cancelled计数（SC-009代理） | 合法拒绝或过期不等于越界下发；需核对授权/目标及实际执行 |
| fallback次数（SC-010代理） | 有降级不等于游戏中断；无降级也不证明故障时流程可继续 |
| 两个companion有轮次（SC-012代理） | 相同游戏内角色路由与记忆/关系/指令隔离；不能把Alice与另一游戏narrator的轮次当双NPC隔离通过 |
| memory_cited>0（SC-001代理） | 引用内容正确、真实重启后仍成立、满足规定样本和正确率；注入记忆不等于回复正确引用 |
| ≥3个关系阶段出现（SC-003代理） | 同条件语气/行为可区分的人工判定与比例；阶段覆盖不等于区别成立 |
| 任意latency_ms的p95（SC-011代理） | UE输入到首次实际表现、规则/LLM分组、文本/语音采样、至少30次；当前生产_record_turn未传latency_ms，不能等新对话就自动完成采集 |

因此保留原T32/T37实现和历史回归，不把其代理PASS升级为正式SC验收；正式结论由[需求基线](../planning/aesir-agent-sdd-v1.1.md)与[采样口径](../protocols/integration-alignment-v0.3.md)逐项核对。SC-002/004/005/006/007/008/013也仍需相应人工或真实运行证据。

<a id="ue-20261019"></a>
## 2026-10-19临时UE工程联调（原日志深夜续记）

Python端口改动提交 `46feea3`；记录随后随 `1ac8751`进入服务仓，最终审计基线 `a2dd426`。原UE操作指向 **E:/AesirWarden**，引擎位于D:/UE_5.8，UE工作区未提交，未给出可信UE提交锚点；不是本次主工程 `D:/YYchainsaw/Unreal-Projects/AesirWarden` 的资产检查。

原记录先称临时工程无可用umap，后用 `Tools/build_jiadiao_map.py` 创建 `/Game/Maps/L_Jiadiao`（PlayerStart + BP_AliceCompanion），调整默认地图。此前“零关卡”是该环境当时判断，不能据此覆盖D盘正式工程事实。

保留的HTTP轨迹为：

```text
GET  /health               → 200
POST /v1/tactical/resolve  → 422  （BeginPlay测试钩子空参数）
POST /v1/agent/step        → 200 ×28 （每3秒心跳）
```

原422重放定位为intent_id/timing空字符串、captured_at非ISO-8601，属于空测试请求被schema拒绝。UE日志记“AI服务连接成功”；console/state记last_scene=combat、relationship_value=26、last_seen=2026-10-19T01:08:19Z。原始完整请求/响应、蓝图导出、进程日志未随服务仓归档，本页保留历史摘要，不重新断言关系变化由哪些心跳造成。

这些材料支持当时临时游戏世界→CompanionChatSubsystem心跳→HTTP8011→服务状态更新的连通。原文“UE↔Python全链路打通”缩限于此；玩家UI文本/语音、技能实际启动/命中/完成、回执阶段和正式D盘工程仍需独立核验。原先动画/资产缺失、T-pose等结论同样不扩展为D盘当前状态。

<a id="rl-history"></a>
## 旧队友实验与当前Boss候选

2026-09-10旧CHANGELOG记3种子×100万步：rule mean_reward17.62 / win_rate1.00 / stun_burst_rate0；seed0为15.11/1.00/0，seed1与seed2为21.76/1.00/1.00，并据此写“2/3达标”。Git历史 `5d0730d^` 的 `rl/features.py` 和 `rl/sim/core.py` 表明这是17维、7种队友动作（含爆裂/治疗/护盾）的旧实验。其ZIP/日志旧路径为 `models/rl/ppo_bossfight_seed{0,1,2}.zip`、`train_multi_seed.log`、`eval_multi_seed.log`；本轮未核验其全部产物。旧“上线判定”不作为当前Boss-as-agent结论。

当前Boss候选是schema4 / boss-sim-005 / boss-reward-003 / seed1，26维、9动作。原训练manifest记录2026-09-16生成、实际总步数1015808（请求1000000），训练后评估每画像100局；2026-09-17冻结selection用base_seed50000、每画像300局共900局，Boss胜率0.8433。该900局用于选模，未找到逐局原始记录，不能当作独立测试或UE结果。

2026-10-19仅静态读源和重算本机ZIP SHA，与selection记录一致。路径、获取限制、依赖和真实命令集中在 [RL说明](../../rl/README.md)。本次没有重训/独立评估/UE BT成组对照，运行时也未自动核对模型hash和训练身份。

<a id="maintenance-20261019"></a>
## 2026-10-19文档整合

本次工作只整合需求、入口、契约、模型视图和历史证据，清理重复旧稿与分散日志；未运行服务、测试、训练或UE验收，未修改模型权重和程序实现。历史769 passed+2 skipped保留为10-15末次全量记录，12 passed保留为10-19端口专项，不写成本次完整复跑结果。文档链接/模型静态检查和排版结果由本次交付说明记录；尚待人工或运行验收的部分不因文件整合而变为通过。