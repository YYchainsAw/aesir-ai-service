# 历史验证与决策记录

<a id="shadow-0c-20261026"></a>
## 2026-10-26 阶段 0c 影子模式双写比对

`ShadowScheduler` 同时委托 `InMemoryScheduler`（权威基线）与 `RedisScheduler`（fakeredis 替身），每次调度操作后比对决策返回值与状态快照（running/waiting/sessions 编码域）。任一不一致即抛 `ShadowMismatchError`。

- **9 个测试**：5 个调度原语比对（槽上限/释放放行/同会话串行/排队深度/出队释放）+ 3 个 RequestCoordinator 端到端（串行/并发/取消排队）+ 1 个故意污染状态验证 Shadow 确实能抓到偏差。
- **关键设计**：`try_acquire` 成功后必须立即 `start()`（与协调器控制流一致——内存后端 try_acquire 只判定不占槽，Redis 后端原子占槽）；`wait()` 退化为 sleep（与 Redis 后端一致），不依赖内存 Condition 唤醒时序。
- **验证结论**：两个后端在 fakeredis 上单机单 worker 语义逐字节一致。跨 worker NX 抢占与真实 Redis 行为仍留待 0d。

| 检查 | 本轮实测 |
| --- | --- |
| shadow 单测 | 9 passed |
| scoped 全量 | 490 passed |
| 完整适用核心 | **1522 passed、10 skipped、80.25s** |

<a id="stream-llm-fix-20261026"></a>
## 2026-10-26 legacy SSE LLM 分支 TypeError 修复（issue #102）

`stream_dialogue_reply` 把 `game_id=game_id` 传给 `_stream_llm_reply`，但后者签名不接收该参数（函数体内部自行从 `profile.game_name.lower()` 重算）。切到 `companion_backend=llm` 时立刻抛 `TypeError: _stream_llm_reply() got an unexpected keyword argument 'game_id'`，legacy SSE 的 LLM 分支完全不可达。现有 SSE 测试只覆盖 mock 后端，故未暴露。

- **修法**：给 `_stream_llm_reply` 加 `game_id: str` 参数（与 `_stream_mock_reply` 签名对称）；删掉函数内部重算；fallback 路径直接复用调用方传入的 `game_id`。
- **测试**：新增 3 个走真实 SSE 端点的 LLM 后端测试（无付费桩）——正常流 delta+meta（source=llm）、前置失败回退 mock（source=fallback）、已发 delta 后中断发 error 帧（不发 meta）。

| 检查 | 本轮实测 |
| --- | --- |
| SSE 测试 | 6 passed（原 3 mock + 新 3 LLM） |
| 相关回归 | 52 passed（test_companion_stream + test_llm_services + test_companion） |
| 完整适用核心 | **1513 passed、10 skipped、78.95s**（whisper 需本地模型单独跑） |
| 边界 | 未改动流式提交语义、未绕过认证、未把此修复当作 scoped SSE 已交付 |

<a id="coord-0ab-20261026"></a>
## 2026-10-26 请求协调器外置 0a/0b 与 Windows MAX_PATH 修复

为支撑 50k 人规模，把请求协调器的易失调度态（全局生成槽/会话串行/排队深度/唤醒）从进程内存抽到可替换后端后，再外置到 Redis。用户拍板三项：阶段0保持同步（UE 契约零改动）、单实例 Redis+哨兵足够、`coordination_backend=redis` 但 `scope_storage_backend=json` 启动即拒绝。

- **0a**：新增 `app/scoped/scheduling.py`（`SchedulerBackend` Protocol + `InMemoryScheduler` + `_Request`），`requests.py` 调度操作全部委托；默认后端逐字节保留原单进程语义。
- **0b**：新增 `app/scoped/redis_scheduling.py`（`RedisScheduler`）。不用 Lua——用 `SET key token NX EX <lease>` 这条原子命令表达全局槽与会话锁（NX 即占槽 backstop，租约 TTL 崩溃自愈）；`exclusive()` 退化为进程内 RLock，`wait()` 退化为 50ms 轮询。`config.py` 新增 `coordination_backend`/`coordination_redis_url`/`coordination_lease_seconds` 及硬边界校验器；`reset_coordinator()` 惰性构造 Redis 客户端并 `ping()` 快速失败。
- **Windows 65 失败真因**：之前误判为「刚 mkdir 紧接着 open 的线程竞争」，实为 **MAX_PATH(260)**。pytest 临时基座叠加 v0.4 分区（game/player/save/npc/run 三层 UUID）使信号 JSONL 路径达 ~265 字符，`mkdir` 报 exists 但 `open` 报 `FileNotFoundError[Errno 2]`。修法：`tests/conftest.py` 在 win32 把 `tempfile.tempdir` 指向短目录 `C:\aesir_pytmp`；同时把三个埋点（agent_step/dialogue/event）的 mkdir+open 收拢为 `storage.append_jsonl`（带瞬时错误有界重试）。

| 检查 | 本轮实测 |
| --- | --- |
| 完整适用核心 | **1503 passed、0 failed、12 skipped、77.64s**；对比上轮基线 1430 passed/65 failed——65 个 Windows 失败全部恢复 + 8 个新增 0b 测试，零回归 |
| RedisScheduler 单测 | 6 passed：全局槽上限、释放放行、同会话串行、排队深度上限、出队释放深度、走 RequestCoordinator 端到端 |
| 配置硬边界 | redis+json 启动拒绝（match `scope_storage_backend=sql`）、redis+sql 放行 |
| 未验证 | 跨 worker NX 抢占、真实 Redis 行为——本机无 Redis/无 docker，fakeredis 不支持 EVAL。留待 0c 影子模式双写比对、0d 双 worker 混沌测试 |

<a id="text-routing-20261023"></a>
## 2026-10-23 文本角色入口修复与两仓交接

本轮在独立Windows worktree从`main@b641b2f`建立`codex/npc-alignment-20261023`，代码与测试提交为`a0869b8106196956416d7626c46ae1cbd3b3606b`；该候选提交已由 PR #104（`df0f4f9`）合入 main。原开发工作区及未提交内容未改动。两仓比较基线仍为服务`b641b2f`、UE`ea43abc`，实际接入使用包含本修复的服务提交并另记UE构建/资产。

共享`agent/step`文本入口调用意图解析门面时漏传`companion_id`，使Bruno命令按Alice默认唤醒词/LLM prompt解析。现将已校验的请求角色传给原门面，legacy与scoped复用同一修复，不改变协议、能力目录或执行权。新增40例HTTP回归使用真实解析门面，LLM客户端仅使用无网络替身，覆盖双入口、Alice/Bruno中英文唤醒词、跨角色/闲聊无动作、LLM角色prompt与故障规则回退及快照目标。

| 检查 | 本轮实测与限制 |
| --- | --- |
| 修前新回归 | 14 failed、26 passed，分别暴露Bruno命令落闲聊、Alice唤醒词误触发Bruno、Bruno使用默认Alice prompt；生产修复后同批纳入下列通过结果 |
| 修后相关回归 | 136 passed，18.86秒；范围为新文本路由、既有agent API、scoped动作/API、LLM意图与多角色隔离6个文件 |
| 完整适用核心首轮 | 1492 passed、1 failed、11 skipped；失败为已有迁移报告断言写死Linux路径分隔符，Windows返回本机路径。仅将测试改为比较`Path.parts`，未改迁移业务、源文件处理或输出格式；数据库文件专项随后24 passed、2 skipped |
| 完整适用核心最终 | **1493 passed、11 skipped、7 warnings，86.51秒**；Windows、CPython3.12.15，包含SQLite持久化与scoped回归。11跳过为5项未提供专用MySQL URL、5项POSIX/Linux权限/目录策略专项及缺可选faster-whisper模块；不冒充Linux或实际MySQL复验。7条为既有Starlette/httpx及422常量弃用提示 |
| 环境与文档 | 独立venv按现有requirements-dev安装；`pip check`通过。两仓Markdown链接与`git diff --check`另行检查；仅更新文档和任务不改变原UE场景的未执行状态 |

最终命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q --tb=short --junitxml=data/runtime/alignment-20261023/core-pytest-final.xml
.\.venv\Scripts\python.exe -m pip check
```

原始JUnit位于本worktree忽略目录`data/runtime/alignment-20261023/`，首轮与最终XML分别保留。本次没有访问真实供应商或MySQL、运行UE、训练/选模、部署/合并远端main。遗留LLM SSE参数不匹配独立跟踪[#102](https://github.com/YYchainsAw/aesir-ai-service/issues/102)，未纳入本次文本修复。

用户提供的AIRI清单20项逐项对照、支持边界与两仓任务在[交接基线](../planning/airi-learning-alignment-20261023.md)及[#103](https://github.com/YYchainsAw/aesir-ai-service/issues/103)维护。服务端子集、UE接入、实际动作及正式发布分别验收；本轮修复与文档对齐不关闭这些后续工作。

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

<a id="scope-20261021"></a>
## 2026-10-21 第二步v0.4服务端实现与回归

用户批准计划后，在服务器 `/www/wwwroot/aesir-ai-service` 从 `main@93d9d6c` 创建 `feature/npc-scope-v04`；审批文档单独提交 `d720474`，随后实现新版入口、数据分区和生命周期。此次未修改UE工作区，也未连接UE。解释器为项目 `.venv/bin/python`，Python 3.12.15；单worker、本轮业务后端为rule/mock。

2026-10-21 23:45（Asia/Shanghai）的适用核心回归：**1029 passed、1 skipped、7 warnings，28.24秒**。其中新版 `tests/scoped` 的190项通过；21个完整golden在模型测试内回读校验。命令为：

```bash
.venv/bin/python -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped -q --tb=short --junitxml=data/runtime/remote-dev/verification/step2-pytest.xml
```

跳过项为未安装可选faster-whisper的测试模块；7条是现有Starlette弃用提示。本轮不安装可选ML/RL，未执行需要NumPy/Torch的Boss推理/训练测试，不能将该命令称为所有可选功能的全量验证。保留此前848 passed+2 skipped等历史结果，不用不同环境的计数互相替换。

| 验收范围 | 本轮证据及实测含义 |
| --- | --- |
| AT-SCOPE-01/02/04 | principal与UUID校验、双玩家/双存档/角色分区、完整session/run键、长期文件重载、legacy与scoped隔离 |
| AT-SCOPE-03/11 | run/encounter CAS及ABA、并发唯一赢家、旧绑定拒绝、reset_runtime模拟服务实例替换；落盘epoch保持，不能当作正式发布重启演练 |
| AT-SCOPE-05/06/09 | HTTP生成过程由线程事件阻塞，期间reset/end run/推进受控单调时钟，释放后409且没有迟到对话历史；缓存重放不刷新预算；旧epoch/遭遇拒绝 |
| AT-SCOPE-07/08 | single-flight、稳定directive ID、冲突/窗口/容量、跨world/combat同版通道、receipt原scope/run/请求关联；未开始容量拒绝与开始后UNKNOWN分开 |
| AT-SCOPE-10/12 | 17条旧入口严格门控、scoped未支持流式/语音明确404、console同版模型、21个golden以及适用核心回归 |
| 部分提交失败 | 在session写入之后模拟信号写失败，返回UNKNOWN；同逻辑ID再次请求不重做副作用。此证据不表示具有多文件事务或自动回滚 |

运行原始文件在服务器 `data/runtime/remote-dev/verification/step2-pytest.log`、`step2-pytest.xml`和`step2-pytest-result.json`，后者包含测试时间、命令、计数、源码SHA256和保留文件校验；这些运行产物不入Git。既有 `test_memory_degradation.py` 修正、`.python-version`与Linux锁文件的SHA256与实施前保存值全部一致。第一步留下的Linux测试可移植性修正以独立提交 `cb05cfa` 保留，未混入第二步实现提交 `ba3740c`；版本/锁文件仍保持原有未提交状态。

开发实例仍在 `127.0.0.1:18011`，最终启动与健康/OpenAPI检查另存同目录 `step2-http-smoke.json`。该HTTP检查只证明环回服务能启动及路由可发现，不是UE连通、真实LLM/ASR效果、端到端延迟或正式多人服务验收。配置与UE后续清单见[v0.4开发与交接](../guides/scoped-development.md)。


干净检出复核：在临时detached worktree `cb05cfa` 使用同一项目解释器重新执行上述适用核心命令，**1029 passed、1 skipped、7 warnings，29.20秒**，不依赖服务器其余未提交文件或开发`.env`。JUnit、日志和含commit/真实app模块路径的结果分别为`step2-clean-pytest.xml`、`step2-clean-pytest.log`、`step2-clean-pytest-result.json`；临时检出已清理。仓库当前未配置GitHub Actions检查，本轮自动验证在服务器运行，PR保持草稿待审查。

<a id="loop-20261022"></a>
## 2026-10-22 第三步请求与执行反馈服务端回归

用户授权继续第三步后，在服务器 `/www/wwwroot/aesir-ai-service` 从 `main@e96151b` 创建 `feature/npc-execution-loop`。跟踪为[DEP3里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/7)与#76～#80；范围以[实施计划](../planning/step-03-execution-loop-plan.md)和[闭环增量契约](../protocols/npc-loop-contract-v0.4.md)为准。项目解释器Python 3.12.15；未新增依赖或修改开发`.env`。

2026-10-22 12:30（Asia/Shanghai）的适用核心回归：**1272 passed、1 skipped、7 warnings，36.47秒**。其中 `tests/scoped` 从190增至433项（新增243项），新增10个完整golden由模型测试回读。命令为：

```bash
.venv/bin/python -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped -q --tb=short --junitxml=data/runtime/remote-dev/verification/step3-pytest.xml
```

跳过的是未安装可选faster-whisper的模块，7条为既有Starlette弃用提示。此命令只覆盖适用核心，不包括需要NumPy/Torch的Boss推理/训练或真实ASR；没有调用付费LLM、测试UE连接或修改UE工程。

| 验收范围 | 本轮实测及限制 |
| --- | --- |
| AT-LOOP-01/03 | 线程事件控制同会话chat/agent文本FIFO与新历史、跨session全局限额、队列/状态容量、规则心跳旁路；非生产并发容量结论 |
| AT-LOOP-02/05 | 排队/运行/先到取消、最终提交竞争、重复请求single-flight、旧绑定/epoch拒绝；取消不强杀供应商HTTP，不撤销已提交事实 |
| AT-LOOP-04 | 真实兼容客户端配httpx.MockTransport核对剩余1.5秒→1.25秒timeout与较短供应商timeout；取消/过期/旧身份穿透intent fallback及熔断；真实网络/计费未验 |
| AT-LOOP-06/07 | 同sequence冲突、无序号重复、终态后accepted不倒退、批内错误无追加；注入open/部分write/flush/fsync失败，订单unknown且该NPC/run后续指令/回执封锁；clear或重启不会修复磁盘 |
| AT-LOOP-08 | 跟随引用快照玩家、等待不虚构目标、治疗/护盾/爆发保留ability关联；未满足眩晕及未知on_condition无动作；只验证服务建议，不能证明UE有对应技能或已执行 |
| AT-LOOP-09 | 生命周期与已知指令原请求查询、未知ID错误、只读不返回payload/不续期；executed为UE自报，完整started/hit/completed及持久历史不在此账本 |
| AT-LOOP-10 | 严格新增模型、10个golden、旧JSON兼容与核心回归；3次HTTP（原请求/同ID重试/新请求）对应3个HTTP尝试UUID、2个实际上游UUID，日志无测试玩家/回复/提示词/API key原文 |
| 提交边界 | 受控时钟令coordinator最终写入后、外层校验前过期：HTTP503/状态unknown，历史仅写一次且重试不重做；区别于后续因过期拒绝回放已完成结果 |

原始记录保存在服务器 `data/runtime/remote-dev/verification/step3-pytest.log`、`step3-pytest.xml`、`step3-pytest-result.json`；专项433项为`step3-scoped.xml`。结果JSON保留时间、命令、分支基线、源码SHA256和保留文件校验，最终提交另记于运行元数据。这些文件不入Git。`.env`、`.python-version`、`requirements-dev-linux-py312.lock`与实施前SHA256完全一致，后两者继续保持原未提交状态。

当前仅服务端开发增量通过，第三步整体验收与EVO-01生产余项没有关闭。UE仍需完成输入/回调代际、动作去重与实际执行/回执、条件监听协议、断网兜底及SC-011真实端到端采样；正式认证、数据库事务、跨重启恢复和离线同步留第四步。[开发指南](../guides/scoped-development.md#loop-usage)维护操作清单。

<a id="persist-20261022"></a>
## 2026-10-22 第四步SQL、访问控制与恢复服务端验证

第三步PR #81已合入 `main@15f1672`，按用户授权在服务器 `/www/wwwroot/aesir-ai-service` 创建 `feature/npc-persistence-access`。跟踪为[DEP4里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/8)与#82～#87；范围见[计划](../planning/step-04-persistence-access-plan.md)。没有改动现有MySQL5.7、开发`.env`或UE工作区，未连接UE，也未调用真实LLM/ASR/训练。

项目Python 3.12.15，新增SQLAlchemy 2.1.6、PyMySQL 1.2.3（RSA extra安装cryptography 50.0.2）。独立MySQL 8.4.13容器仅在127.0.0.1:13306，限制640MiB/0.75CPU；项目dev/test/restore库、迁移/运行账号分离，凭据与数据在站点根外。开发18011保留原配置；本轮18012临时SQL/Bearer进程在演练后停止，没有发布公网入口。

2026-10-22 20:30（Asia/Shanghai）适用核心回归：**1404 passed、1 skipped、7 warnings，74.71秒**。新增 `tests/persistence` 共132项（其中5项实际MySQL），新增10个完整golden由strict模型回读；原scoped 433项继续通过。命令为：

```bash
AESIR_TEST_MYSQL_URL_FILE=/etc/aesir-ai/dev/mysql84-test-runtime.url \
  .venv/bin/python -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q --tb=short --junitxml=data/runtime/remote-dev/verification/step4-pytest.xml
```

跳过项为未安装可选faster-whisper的模块，7条是既有Starlette弃用提示。未包含需要NumPy/Torch的Boss推理/训练，也不是UE/真实模型质量或容量验收。未显式提供MySQL测试文件的普通运行会另跳过这5项，不能与本次真实库通过混淆。

| 验收范围 | 本轮证据及实测含义 |
| --- | --- |
| AT-PERSIST-01/02 | Bearer缺失/错误/过期/撤销、玩家停用/存档撤回、console/reset分权、跨玩家拒绝、DB故障503无身份/JSON回退；生成中撤销无最终SQL/会话提交 |
| AT-PERSIST-03/04 | SQL UoW文档与最终mutation故障全回滚、CAS冲突不覆盖赢家、会话提交后更新；journal持久身份/UNKNOWN/先到取消与重启后不可重做；归档提交失败也全回滚并保留unknown |
| AT-PERSIST-05/06 | 原实例/绑定失效而历史确认可读，无可执行payload；实时/离线共用fact与receipt身份，终态保护、原run/encounter/epoch/能力及游戏目录校验，整批冲突无部分写入 |
| AT-PERSIST-07/08 | 清记忆→旧epoch事实memory skipped_reset、relationship独立确认；旧回执归档不恢复记忆；服务受理时间不被旧UTC倒退；并发/持久调用额度与缓存不重复调用供应商 |
| AT-PERSIST-09/10 | 默认dry-run、归属明确JSON与SHA、源不改/重复不重导/冲突拒绝、备份格式与校验/空目标约束；恢复默认撤销旧凭据，显式新发后可用 |
| AT-PERSIST-11 | 实际MySQL5项：8.4版本、运行账号无DDL/无法读mysql.user、事务故障回滚两文档/版本、新Python进程读提交、HTTP runtime替换后旧绑定/同ID新绑定拒绝与历史恢复、CAS赢家保留 |
| AT-PERSIST-12 | 适用核心、strict样例、实际MySQL与真实进程演练分别记录；所有模型调用为rule/mock/MockTransport |

真实进程/恢复演练另于同日20:27（Asia/Shanghai）运行 `data/runtime/remote-dev/verification/step4-process-proof.py`，结果 `step4-process-proof.json`。两个实际HTTP进程PID为1377172→1377205（均已退出）：新实例不继承旧绑定，旧请求409，同ID换binding仍拒绝，历史确认complete；实时事件再离线同步duplicate，不重复加分；reset后旧epoch新事实跳过记忆；原旧epoch指令从accepted归档到executed，receipt_count=2，未改变记忆/关系。这里executed仍为测试客户端自报，不是UE技能实际执行。

同一演练使用合成、完整归属的两份JSON验证实际MySQL dry-run/apply/重复导入及源SHA不变，没有迁移玩家真实数据。私有备份恢复至空隔离MySQL后，8张应用表计数一致（documents=13、operation_journal=6），memory_epoch与原事件确认保留；旧token即使备份时仍有效也被恢复策略停用，显式新签发凭据可验证原存档授权。备份SHA256为 `04fdd8682768818bbf9137b8b4f84e8693a10542c660c10b6ef72037d12a5b78`，原备份只在 `/etc/aesir-ai/dev/backups` 0600私有文件，不入Git。

开发期首次bootstrap在时间列DOUBLE修正前发生；仅对本轮新建且相关表0行的独立dev库显式改正4个时间列，未改其他库。最终schema检查会拒绝MySQL单精度时间列，create_all不被描述为自动升级。恢复业务数据遵守备份恢复点，不能保留备份之后未知的reset/撤销；正式灾备切换仍需恢复点/RPO和后续清理收敛。

原始JUnit/日志为 `step4-pytest.xml` / `step4-pytest.log`，元数据为 `step4-pytest-result.json`，含解释器/依赖、实际MySQL标志、源码SHA256、时间和保留文件校验。测试本身通过后，记录包装脚本因用系统解释器读取新依赖元数据失败；已从通过的JUnit/日志恢复元数据，并确认所有代码/样例文件mtime均早于测试开始，记录此事实而未伪造重跑。最终提交再核对源码哈希。`.env`、`.python-version`和原Linux锁文件SHA256与实施前完全一致，后两者继续保持原未提交状态。

结论只覆盖第四步服务端开发增量。UE凭据/按档缓存/事实与回执本地队列、冲突处理、断网游戏兜底与SC-011仍待接入；正式数据切换、OS受限用户、HTTPS/传输限制、备份调度/保留/完整RPO演练和真实容量留发布验收。当前单worker，未启用生产多worker或公众服务。操作见[持久化开发指南](../guides/persistent-development.md)。


<a id="database-design-20261022"></a>
## 2026-10-22 第四步数据库设计补齐与结构审计

用户要求补齐需求导向的ER/PDM、数据字典和保留建表SQL。在既有第四步分支 `feature/npc-persistence-access`、实现基线 `8e3362c` 上完成[数据库设计](../design/database/README.md)，未追记为编码前已完成设计。保留原45FR/7UC和协议含义，补需求→17类逻辑实体→8物理表44列的映射、10个JSON命名空间及聚合/拆表边界；没有更换现有业务schema或数据后端。

本地Windows使用draw.io MCP的 `list_pages/set_page` 保存2份源的3页，再由draw.io Desktop 32.4.1逐页导出含XML的3张PNG，上传服务器 `docs/design/database/src` 和 `png`。ER两页区分逻辑归属与物理外键，PDM逐列列出类型、PK/FK、NN/NULL、AI及索引。已逐页AI目视检查文字、基数和连线；PNG的CRC、嵌入的对应页XML与源页结构一致，服务器5文件SHA256与本地导出一致。没有把既有UML领域图当ER/PDM，也未重新绘制UML或回填UE Word。

2026-10-22 21:17（Asia/Shanghai），项目Python 3.12.15上的最终脚本回归 **50 passed、1 warning，0.57秒**，其中新增数据库设计检查15项。唯一warning为既有Starlette/httpx弃用提示。命令：

```bash
.venv/bin/python -m pytest tests/scripts -q --tb=short \
  --junitxml=data/runtime/remote-dev/verification/database-design-script-tests.xml
.venv/bin/python -m scripts.check_database_design
.venv/bin/python -m scripts.check_database_design \
  --database-url-file /etc/aesir-ai/dev/mysql84-test-runtime.url
.venv/bin/python -m scripts.check_database_design \
  --database-url-file /etc/aesir-ai/dev/mysql84-restore-runtime.url
```

离线检查保留SQL与MySQL metadata规范化编译结果一致、字典逐列类型/空性/键/数据库默认表述、PDM表列全集/类型/完整标记/归属及2条实线FK端点。只读数据库审计比较表列顺序、类型、可空性、默认、自增、PK、FK及目标schema、二级索引、CHECK、引擎、字符集、参考collation与版本标记；不是由HTTP启动成功推定一致。针对工件变异及跨schema FK的负向回归能拒绝伪造约束。本次未重跑第四步1404项核心业务回归；其255个源码文件SHA256仍与通过回归的 `8e3362c` 一致，该历史结果仍以原记录及提交为准。

| 核对或演练 | 实际结果及限制 |
| --- | --- |
| test84、restore84只读结构审计 | 均通过；8表44列、2FK、1个MySQL隐式二级索引，符合当前v1及参考排序规则 |
| dev84只读结构审计 | 退出码1，唯一差异为 `access_credentials.expires_at` 实际DOUBLE NULL，源码要求DOUBLE NOT NULL；三个既有库的该列NULL行数均0、版本均1。失败结果保留，未自动修复 |
| 初始DDL真实执行 | 最终文件在新建隔离 `aesir_ai_design84_final_20261022` 执行，MySQL8.4.13；8次CREATE及1次版本INSERT，8表44列/2FK和结构审计通过；重复执行被重名表明确阻断。先前未规范行尾空格的初稿在另库验证，不代替最终文件证据 |
| v1到期列修复SQL | 在新增隔离 `aesir_ai_design84_20261022` 模拟漂移后验证成功；版本错误、FLOAT列型、存在NULL三个反例由SIGNAL阻断ALTER；最终结构审计通过且无残留helper过程 |
| 图纸与文档 | 2源3页/3PNG；全部嵌入页与源一致、上传哈希一致；本次新增/修改Markdown相对文件链接检查与 `git diff --check` 通过 |
| 既有环境保留 | dev/test/restore数据和结构、现有5.7、开发.env、Python版本文件和历史Linux锁不改；后三项SHA256与实施前清单一致 |

保留初始SQL的SHA256为 `b989fe243e5c3561a5ae8dea0bbd2eefde7482d52c66295732d56b5f5c91bc3f`，v1修复SQL为 `e6bbd7121533e45348b739771c80f6ae4f76b3324c31865e62fbadf2bb3f23ca`。初始SQL最终只规范生成器的行尾空格，语义不变，且已单独执行最终文件；原SHA和两次目标分别保留于证据。修复是恢复v1既有约束，不伪装成不存在的v2迁移；未启用自动迁移执行器。新隔离库仅保留核对结构，合成数据及辅助过程已清除，临时私有root连接文件已删除。

原始证据位于服务器忽略目录：`database-design-v1.json`（DDL/修复正反场景）、`database-design-audits.json`（三个既有库只读结果）、`database-design-diagrams.json`（图源/PNG校验）与 `database-design-script-tests.xml`（脚本JUnit）。这些文件在 `data/runtime/remote-dev/verification`，不与私有凭据或业务数据一起提交。

结论只覆盖数据库设计材料、保留SQL的隔离执行与结构检查；dev偏差仍需安排受检修复，JSON账本容量/索引/长期保留、正式数据切换和生产恢复演练继续待验。UE、真实LLM/ASR、HTTPS/公众网络、容量或多worker没有因图纸补齐而通过。审查入口保持PR #88草稿。


<a id="schema-gate-20261022"></a>
## 2026-10-22 第四步结构门禁与既有开发库修复

PR #88已由用户合入main，服务器快进至 `eea7532` 后从main创建 `fix/npc-schema-validation`，继续第四步受检收尾，跟踪[#89](https://github.com/YYchainsAw/aesir-ai-service/issues/89)。本次修复既有dev库的expires_at可空性偏差，并把离线结构审计接入实际SQL启动/首次访问和初始化边界；schema仍为v1，没有另建无实际结构变化的v2迁移。

新增共享模块 `app/persistence/validation.py`，由运行时 `check_schema()` 与设计审计复用metadata规则。核对8表、44列及顺序/类型/可空/数据库默认、自增/生成列、PK/FK（含schema及动作）、索引、CHECK、引擎/字符集和唯一版本标记。metadata未固定的collation不硬编码为样本0900，大小写策略仍需正式部署核定。结构差异统一拒绝为503 `DATABASE_SCHEMA_MISMATCH`，SQL访问/反射失败仍报告不可用，不向HTTP回显差异或DSN。

SQL lifespan每次复核（包括缓存连接），首次获取SQL连接只有验证成功才进入缓存；普通请求不重复反射。初始化使用独立、未缓存的operator连接，只有完全空库才建表；已有完整库仅只读幂等核对，错误版本、残缺或其他表拒绝且不先补建DDL。认证对缺失、非有限或非数值到期数据返回AUTH_UNAVAILABLE，不再抛TypeError或形成无期限凭据。

### 开发库备份与修复

21:38（Asia/Shanghai）先确认dev唯一偏差是 `access_credentials.expires_at` 的NULL属性、当前NULL行数0；没有运行中的18012 SQL验证进程。为修复前保全已知偏差库，使用受控只读REPEATABLE READ快照保存完整8表格式v1逻辑备份，并单独保存原SHOW CREATE定义；不为运行服务绕过门禁。两文件在 `/etc/aesir-ai/dev/backups`，0600，文件名为 `step4-followup-dev-before-schema-repair-20261022.json` 及同前缀 `-ddl.json`，没有进入站点根或Git。

随后原样执行已审的v1修复SQL三段CREATE/CALL/DROP；过程内版本、DOUBLE列型和NULL计数检查通过后才改为NOT NULL。8张表的业务行逐行及规范内容SHA256前后完全一致：documents13、journal6、state_versions3，其余五表各1行；无残留helper过程，版本仍1。逻辑备份内容SHA256为 `047182d75c7f3f68a54c77b700f6ce34f8dceb4bc3275f8afd3650f53c57edeb`。只对专用dev执行这一既有约束修复，test/restore结构及旧5.7未变。dev/test/restore之后的共享只读审计均通过8表44列。

### 回归与真实MySQL门禁

2026-10-22 21:42～21:44（Asia/Shanghai），Python3.12.15适用核心回归 **1463 passed、1 skipped、7 warnings，81.35秒**，含5项实际MySQL。相比已合入main的1419项适用核心基线净增44项；persistence共176项。跳过的仍是未安装可选faster-whisper模块，warnings为既有Starlette弃用提示。命令：

```bash
AESIR_TEST_MYSQL_URL_FILE=/etc/aesir-ai/dev/mysql84-test-runtime.url \
  .venv/bin/python -m pytest tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q --tb=short --junitxml=data/runtime/remote-dev/verification/step4-followup-pytest.xml
```

| 证据 | 本轮真实结果 |
| --- | --- |
| SQLite与反射回归 | 漂移类型/NULL/default/列、键、索引、引擎等拒绝；已有库init不补表/不改标记；失败连接不缓存；缓存后结构变化仍阻止下次SQL lifespan；异常expiry拒绝 |
| 独立MySQL空库 | 新库 `aesir_ai_gate84_20261022` 运行入口先503且保持零表；init preview仍零表；只有显式operator init创建完整8表 |
| 实际SQL启动负例 | 在上述新库把expires_at改成DOUBLE NULL后，直接check与首次get_database均拒绝；实际18012进程PID1448600在lifespan退出码3，无监听及业务写入 |
| 实际SQL启动正例 | 仅将该隔离库恢复NOT NULL后，实际进程PID1448632健康200、无Bearer业务请求401；演练后进程已终止，18012无监听 |
| 既有库初始化边界 | 隔离完整库的错误marker999保持不变，init退出1；新 `aesir_ai_gate_partial84_20261022` 始终只有schema_versions表，init退出1而不补表 |
| 账号与开发实例 | 两个新增验证库只授予项目迁移/运行账号各自权限；运行账号DDL和读取mysql.user均拒绝；原18011 JSON进程健康200 |
| 图与文档 | PDM仅改修复状态注记；本地MCP保存、Desktop32.4.1导出含XML PNG，1644×1503，嵌入页与源一致并目视通过；ER与8表44列/2FK设计不变 |

实际进程证明发生于21:43:02～21:43:09，与pytest使用不同独立库，不混用原test库做DDL。两个新隔离库及四份0600连接文件保留用于复现，临时rootURL从未落盘；helper和合成业务数据无残留。HTTP证明只覆盖服务启动与认证门禁，没有UE或真实模型调用。

原始记录位于服务器忽略目录 `data/runtime/remote-dev/verification`：`step4-followup-repair.json`、`step4-followup-audits.json`、`step4-followup-mysql-gate.json/.log`及 `-process.log`、`step4-followup-pytest.xml/.log/-result.json`、`step4-followup-diagrams.json`。回归前后303份源码/样例SHA256一致；`.env`、Python版本文件和历史Linux锁SHA256与本轮开始一致，原未提交文件保留。最终提交后再把证据源码SHA与Git核对。

本轮完成第四步已知服务端门禁与dev结构整改，单worker边界不变。未切换原开发.env为SQL/Bearer，未迁移真实玩家数据，也未测试UE连接；UE凭据/缓存/事实队列、完整跨端恢复，HTTPS/OS隔离、自动备份/保留、真实容量和正式RPO继续按既定步骤验收。


<a id="stage1-status-fallback-20261026"></a>
## 2026-10-26 50k 人架构改造 · 阶段 1（status journal fallback）

阶段 0（易失调度外置 Redis）闭环后，多 worker 非粘性部署的真实剩余缺口收敛为一个：**GET /requests/{id} 的内存 miss**。`coordinator._entries` 是进程内存，请求在 worker A 完成、status 打到 worker B 时直接 404。原本设想的「结果写 journal / 重放读 journal / 取消跨进程」已由 `DurableIdempotencyStore`（SQL 模式外层）实现，无需重复建设。

本次改动（commit `5d003c9`，develop-dyh）：

- `app/persistence/journal.py`：新增 `DurableIdempotencyStore.read_status(scope, operation, request_id)`。把 journal row 折成 `coordinator._record()` 同形状字段（state/reason_code/queue_ms/processing_ms/total_ms/upstream_attempts/cancel_requested）。running 且 `owner_instance` 不是本实例 → 报 unknown（与 `recover()` 同口径，不 mutate SQL）；row 存在但 `scope_parts` 与查询 npc 不一致 → 409 `REQUEST_ID_CONFLICT`（防御性检查，正常调用因 identity 含 npc.key 而不可达）；row 不存在但有 `request_cancel` tombstone → 返回 cancelled 记录。journal 不存 `started_at`，queue_ms/processing_ms 只能给 0，total_ms 用 `finished_at - created_at` 估算。
- `app/scoped/requests.py`：`RequestCoordinator.__init__` 加 `status_fallback` 回调参数；`status()` 在 entry 为 None 时先调它，返回 None 再抛 404。`reset_coordinator()` 在 SQL 模式惰性注入 `journal.read_status`（try/except 包住，数据库不可用时退化为纯内存 status，与阶段 0 前行为一致）。
- 测试：`tests/scoped/test_status_fallback.py` 4 个（内存命中跳过 fallback / memory miss 读 journal / 都 miss 抛 404 `REQUEST_UNKNOWN` / 无 fallback 保持经典 404）；`tests/persistence/test_journal.py` 追加 5 个 read_status 用例（completed 含耗时 / 无该请求返回 None / cancel tombstone / abandoned running 直插 row 模拟 worker A 崩溃→unknown / 篡改 scope_parts 触发 409）。

### 回归

2026-10-26，Windows venv Python 3.12：**1539 passed、10 skipped、7 warnings，82.37 秒**。相比阶段 0e 的 1530 净增 9 项（4 + 5）。跳过项仍是未安装可选 faster-whisper。

| 核对点 | 结果 |
| --- | --- |
| 内存命中不打数据库 | 测试 `test_status_memory_hit_skips_fallback`：fallback_calls == [] |
| 跨 worker 完成可读 | worker A 执行 `store.execute(...)` 完成后，worker B 的 `coordinator.status()` 经 fallback 读到 completed 记录 |
| 真 404 语义不变 | fallback 返回 None 时仍抛 404 `REQUEST_UNKNOWN`；memory 模式不注入 fallback 时行为零变化 |
| 崩溃 owner 不被误读为 running | 直插 running row（owner='worker-a-crashed'）→ read_status 返回 unknown + `REQUEST_OUTCOME_UNKNOWN` |
| 跨 scope 碰撞防御 | 篡改 row.scope_parts 后抛 409 `REQUEST_ID_CONFLICT` |

边界与未做：本次只覆盖 status 读路径；取消的跨进程语义已由 `request_cancel` tombstone + `DurableIdempotencyStore._claim` 守卫实现，未重复建设。阶段 2（异步化，UE 契约变更）仍未启动；真实 MySQL 上的跨 worker 演练待 Linux 环境验证。

<a id="ci-gate-20261026"></a>
## 2026-10-26 最小核心回归 CI（GitHub Actions）

此前 1463→1539 全量回归一直靠人工本地跑、手工记入 CHANGELOG。本轮补最小门禁：新增 `.github/workflows/core-tests.yml`（ubuntu-latest + Python 3.12，push/PR 到 develop-dyh 与 main 触发）。

- 安装：`pip install -r requirements-dev.txt -c requirements-sql-linux-py312.lock`（与 Linux 服务器 3.12.15 实测锁对齐，不引入新依赖）。
- 测试命令即 README「检查改动」原句：`tests/api tests/services tests/schemas tests/scripts tests/rl/boss/test_contract.py tests/scoped tests/persistence -q`。
- 不配置 secrets：真实 MySQL（`AESIR_TEST_MYSQL_URL_FILE`）、faster-whisper、RL 依赖在 CI 默认环境天然 skip，与本地「无 ML/RL 依赖核心回归」边界一致。
- 本地同命令复跑：**1532 passed、12 skipped、84.12s**（Windows venv 3.12.7）。skip 项为 faster-whisper 真机冒烟与 RL 门控用例。
- 未覆盖：首次 push 到远端前 CI 实际跑次未经验证；如需缓存 pip、加 Linux 矩阵（3.13）、或把真实 MySQL 接成可选 job，留待后续。
