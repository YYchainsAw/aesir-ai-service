# Changelog

按里程碑记录本项目进展。原始逐日开发记录归档于 [`docs/logs/`](docs/logs/)，本文件只保留里程碑摘要与当前测试数锚点。

> 测试数锚点纪律：各文档不单独维护测试数，统一以本文件最新锚点为准（当前：2026-09-24，**633 通过**）。

## 2026-09-24 — 对话实测七修：收尾不再复读 + 诚实规则补第五类 + 被批评不当圣旨

同一份真实会话（2026-09-21 魔法对话约 30 轮）复盘的再续修（承六修）。六修堵住最大幻觉源头后，剩余问题集中在「复读惯性」与「诚实规则矫枉过正」两个方向。

- **Anti-repetition 从开场扩到收尾与口头禅**：模型对「不复用开场/句式」执行得很好，但收尾动作惯性复制——实测出现「那就接着走吧」×2 +「走吧，路还长着呢」三连；「说不上来」「记不清」这类不确定口头禅也连续两轮。prompt 明确：不得连续两轮以同类动作收尾（尤其催促出发的「走吧」），不确定短语每轮最多用一次，然后换说法。
- **Memory honesty 第五类—— invented pastimes（虚构既往游戏）**：实测玩家接招 few-shot 里的「猜猜我口袋里装什么」后，模型没有答案，只能编造「上次那个谜题你还没猜出来」来岔开，形成二阶编造。新增规则：不得引用记录里没有的既往谜题/游戏/赌约/承诺（如「上次那个谜题」）；可以临时发起一个新小游戏，但谜底必须自己已决定，猜中了要认。
- **诚实规则矫枉过正的另一半——接受玩家当场告知的信息**：玩家明说「我们上次说话还是昨天」时，她仍回「具体哪天还真说不上来」——无据不说没错，但玩家给了据还不接，就是不接人话。新增规则：玩家当场陈述的相处时长/关系信息即为依据，收下即可，不得在他们已经给出答案后仍反复拉扯「说不上来」。
- **从 few-shot 撤下两个反例**：「猜猜我左边口袋里装的是什么」无解谜题（没有任何地方定义答案）与「才认识几天就忘了」相处时长断言，正是六修实测「才几天不见」与二阶编造的老根。改为把话头交给玩家的问法，并去掉时长断言但保留傲娇语气。同时加强示例框定：即使玩家输入与示例高度相似，也只许学风格、不许抄内容。
- **被批评不当圣旨**：实测玩家说「你说话不如以前」，她立刻「你说得对，我最近确实有点走神」——全盘认错 + 给自己安了一个无据状态（最近走神），讨好式找补。五修管了「不把玩家的话当挑衅」，这是另一头：把玩家的话当圣旨。`conversation_rules.response_rules` 新增：面对批评/贬低，不立刻全盘认错，不给自己安没有依据的状态或理由；可以不服气、反问具体哪里不行、轻描淡写顶回去，自尊在线。
- **测试**：新增 5 例（收尾/口头禅反复读、接受玩家告知信息、禁止虚构既往游戏、few-shot 撤下无解谜题与时长断言、批评场景自尊规则），628 → **633 通过**。

## 2026-09-22 — 对话推动关系：聊得动感情了

实测（约 45 轮真诚交流后仍是 distant(20) 被叫「旅行者」）暴露：关系只由 `/v1/world/events` 驱动、对话链路纯只读——但对话才是陪伴玩法的主体。三项用户拍板：信号走 LLM 顺带返回；五档含负面；节奏半天~一天一档。

- **信号通道**：`_DialoguePayload` 新增 `relationship_signal`（none/warm/deep/cold/hurtful，默认 none）。LLM 判的是玩家本轮发言的**情感质量**（不判她自己的语气），prompt 明示「绝大多数轮次必须是 none，宁漏勿滥——误判比漏判伤关系，因为它动的是一个持久分」。零额外请求，与 topics/facts/reply_topics 同构。
- **写入复用关系规则层全套**：信号映射成 4 类新事件（`dialogue_warm_exchange` +1 / `dialogue_deep_connection` +2 / `dialogue_cold_dismissal` -1 / `dialogue_hurtful_remark` -2）走 `RelationshipStore.apply_event` 唯一入口——冷却/日上限/持久化/损坏降级零新增代码。对话专属冷却 300 秒（新配置 `AESIR_RELATIONSHIP_DIALOGUE_COOLDOWN_SECONDS`，比事实事件的 60 秒严：对话每轮都发生）。
- **校准**（半天~一天一档）：distant→neutral 需 3~5 轮 warm 或 2~3 轮 deep；每日正向上限 15 与事实事件共享（对话刷不满）；负向不限——疏远不需要配额。
- **可观测**：`CompanionDialogueResponse` 新增 `relationship_delta`（本轮实际增减，契约附录登记）；阶段变化自下一轮生效（称呼/语气/硬边界/战术调制/自主行为全部下游自动跟随，无需接线）。mock/回退路径不推动关系（规则判不了情感质量）；关系层故障静默 delta=0（FR-011）。
- **测试**：新增 10 例（枚举校验/暴露/prompt 说明/非法值/缺键兼容、warm +1 落库、冷却拦截、hurtful -2、none 与 mock 不动、5 轮跨 neutral 校准断言、关系故障对话照常、规则层 4 事件 delta 与对话冷却），618 → **628 通过 + 2 跳过**。DeepSeek 实测：普通闲聊 delta 恒 0；「今天辛苦你了」+1；「你对我来说很重要」判为 deep +2；累计跨入 neutral 后她不再叫「旅行者」。

## 2026-09-22 — 对话实测六修：止住幻觉源头 + 能力有据可依 + 印象噪声走 LLM 通道

同一份真实会话（2026-09-21 魔法对话约 30 轮）复盘的续修（承五修）。本轮处理五修未覆盖的另一半问题，六个根因全部带代码级证据。

- **few-shot 语料在教她编造记忆（分量最重的根因）**：`primary_companion.yaml` 的 5 条 `memory_recall` 示范全部是「自信说出玩家从没说过的事」（你怕高／旧王国桥边／看海／蘑菇／热汤面），与 prompt 的 Memory honesty 正面冲突，且 few-shot 权重压过规则文字——实测「当然记得，才几天不见」就是这个模式的翻版。**5 条全部重写**为「有据直说、无据就不确定/反问」，并新增一条正向示范（玩家当场说过 → 如实引用，避免矫枉过正变得什么都不知道）。这是「prompt 指令静默打架」最重的一例：措辞冲突不报错，只表现为角色行为怪。
- **few-shot 的天气条被当成事实源**：实测玩家问「帮我看看天气怎么样」（请求无 world_context），她几乎逐字复述示范里的「云层压得有点低」——模型把示例当成了数据源。天气条改写为「这天色我说不准……等真变了样我再提醒你」；同时在 prompt 示例块加框定：示例中的世界细节（人名/地点/物品/事件/天气）是占位不是事实，不得当作已发生的事引用。
- **能力目录注入对话 prompt**：对话链路此前完全不引用能力清单，被问「你会什么魔法」时只能现编「水系魔法/水膜/水球」且越编越自洽。现在注入 `Your complete and ONLY abilities: 奥术弹（…）爆裂魔法（…）…`（真相源 `tactical_policy.abilities`，与战斗同一份配置不漂移）+「不得发明清单外的能力，被问到就说不会」。
- **Memory honesty 覆盖面从一类扩到四类**：旧版只管「过去事件」，实测她还现编了天气（世界状态）、水系魔法（自身能力）与「才几天不见」（相处时长——她没有钟也没有记录）。四类均无据则不确定/反问。
- **自述主题改走 LLM 顺带返回**（用户选定方案）：她自己的回复此前走 `extract_topics()` 规则切词（无分词库），产出「主修/厉害/代价/不小/水系本来/可不能当没听见」这类碎片直接落印象层，且新印象权重 1.0 ≥ 注入阈值 0.75 立即回注污染下一轮。`_DialoguePayload` 新增 `reply_topics`（0~3 个她自己本轮谈及的名词），LLM 路径完全绕开规则切词；mock/回退路径维持规则兜底。实测碎片同步扩入 `_NOISE_TOPICS` 全等表，存量清洗 6 条（`prune_noise_impressions`）。
- **response_rules 补两条**（五修的另半边）：玩家明显开玩笑/打趣时不当真、不较劲、顺着玩回去（实测「那你很弱欸」被当真接招连较两轮）；先接住玩家本轮说的内容再推进，同一句指令式叮嘱（「跟紧点」）不得连用两轮。
- **测试**：新增 7 例（honesty 四类覆盖、能力目录注入、示例框定、reply_topics 暴露与 prompt 说明、老负载兼容、实测碎片判噪声、reply_topics 落印象两例），611 → **618 通过 + 2 跳过**。

## 2026-09-22 — 对话实测五修：情绪惯性 + 关系阶段硬边界 + 按字面理解玩家

同一份 45 轮真实会话复盘的续修（承三修、四补）。

- **情绪惯性**：此前每轮独立生成，prompt 里没有「她现在什么心情」，模型只能按剧情张力重挑一个——实测出现无来由的情绪跳变与回摆。`DialogueTurn` 新增 `emotion_id` 作为惯性载体（`session_memory.record` 接收、`dialogue_service._record_turn` 传 `response.emotion_id`），prompt 注入 `Your current mood: <上一轮情绪>` 并要求「除非玩家的消息真的改变了处境，否则保持这个心情」。**同时收回上一版 Anti-repetition 里「emotion_id 也要轮换」的指令**——那条指令正是情绪抽签的来源（手势/表情仍要求轮换）。mock/回退路径同样有 `emotion_id`，降级时心情照常延续。
- **关系阶段硬边界**：阶段化人设原先只偏移称呼与语气，`distant` 的「保持距离」压不住基础人设的「暗藏情愫」，实测出现「一边叫旅行者、一边讨论两人合披一块油布还害羞」的割裂。`relationship_stage_personas` 四阶段各补一段 `boundary`（硬边界，非语气建议），prompt 明确「与基础人设的 subtext / behavior rules 冲突时，以边界为准」。亲密度越界比称呼不符更伤体验。
- **按字面理解玩家**：实测连续四轮把普通提问/陈述事实读成挑衅，并给玩家安上「嘴硬」「硬撑」「不肯靠过来」这些他没表达过的态度——敌意归因比记错事更伤体验。`conversation_rules.response_rules` 新增 4 条：按字面理解（不得读成挑衅/较劲/嘴硬，不得指责逞强找借口）、不得安上玩家未表达过的态度动机、打趣只在玩家起头或情境轻松时用且不得连续两轮带刺、大部分回复应是平常温和语气（俏皮是调味不是主菜）。
- **人设同步**：`runtime_state_policy` 改为「同一窗口内延续上一轮情绪」+「关系数值与阶段、四级长期记忆为跨会话状态」，与已落地的 US1/US2 对齐（原文还写着「不维护当前心情、长期摘要」）。
- **测试**：新增 6 例（会话记忆带情绪往返/默认空、链路落情绪、prompt 注入心情、无情绪不注入、阶段边界注入），605 → **611 通过 + 2 跳过**。

## 2026-09-21 — 记忆四层全接线：让「有据可说」成为默认路径

- **根因**（三修之后的继续复盘）：`short_term` / `summaries` / `archive` 三层在真实运行中**恒为空**（`record_experience` 只有测试与 demo 在调），长期信息全靠只有话题、没有事实的印象层承载——她手里没有任何可引用的事实，遇到「上次的烤鱼」这类问法只能脑补。这才是幻视的土壤，三修的「不许断言」只是堵，接上另两层才是疏。
- **事实通道**：LLM 顺带返回 `facts`（0~3 条关于玩家的第三人称陈述）→ `MemoryStore.record_facts` 落档案层（按内容去重、重复提及只刷新时效不新增、重要性不降级）。注入端 `format_memory_block` 按来源分口吻（player told you / you two went through / player promised you），并明确许可「记得的可以直说，但不得加细节」——否则她连真记得的事也含糊其辞。
- **接地校验**（`app/services/memory/facts.py`）：档案事实会以「她确定知道」长期注入，编造一条就是**永久**错误记忆，比当场幻视严重得多。写档前做轻量接地校验——事实实词（剥离「玩家」前缀与高频功能字后的字符集）至少一半要能在玩家真说过的话（本轮 + 近期会话）里找到，对不上直接丢弃。宁可漏一条真事实（印象层仍留痕），也不让编造进档案。
- **共同经历通道**：`/v1/world/events`（含 v0.2 战斗通道）幂等检查之后，把有共同经历语义的事件（第一次踏进某地 / 收到礼物 / 玩家替她挡刀 / 承诺兑现 / 击败强敌）写进摘要层；瞬时战斗状态（血量告急、蓝量过低）不入记忆——那是当下要处理的情况，不是回忆。细节只取上报方给过的 `details`/快照字段，取不到就写泛一点，绝不推断；重放事件不重复记。
- **测试**：新增 22 例，583 → **605 通过 + 2 跳过**。文档同步 SDD 实现补记、契约附加扩展、README 路线图。

## 2026-09-21 — 对话实测三修：首轮幻视 / 印象正反馈回路 / 印象噪声

拿 45 轮真实会话对照后修三个问题：

- **首轮幻视**：prompt 里「不得凭空断言过去事件」原先包在 `if history:` 内，会话第一轮根本不生效，于是首轮就出现「上次的烤鱼」这类无据断言。移到常驻约束并加强（模糊印象只有话题、不含事实），补齐无历史用例。
- **印象正反馈回路**：她自己的回复也提取主题入印象，但走与玩家同一条强化路径，「注入 → 她提起 → 计数+1 → 更必注入」自激，实测「钓鱼」计到 24 次、印象层满 200 条。现在 `origin=companion` 的提及不加深、不刷新时间（仅首次留痕，表示「她记得自己说过」），玩家提及仍可升级来源并正常强化；`retrieve_impressions` 新增 `recent_texts`，近期会话已聊过的话题本轮冷却不注入。
- **印象噪声**：黑名单加 幻视/幻觉/人机/人机味，噪声表加 指代/领属词（这话/你的/那你…）。过滤规则升级不会自愈旧数据，新增一次性清洗脚本 `scripts/prune_noise_impressions.py`（支持 `--dry-run`，已清 14 条）。
- **测试**：新增 8 例，575 → **583 通过 + 2 跳过**。文档同步 SDD 实现补记、README 脚本与路线图。

## 2026-09-21 — SDD Phase 9（US7）：可解释性

- **T076**：`AgentStepObservability` / `CompanionDialogueResponse` / tactical `Observability` 统一新增 `persona_revision`；对话响应带 `memory_layers`（本轮实际注入的记忆条数，按通道分）；心跳路径如实为空（不谎报）。
- **T077**：`/v1/console/state` 扩展——关系阶段/数值、最近场景/情绪（`app/services/console/runtime_state.py` 运行期观测）、近期记忆摘要、三个策略版本。
- **T078**：`mock_ue_flow` 新增 US7 可解释链路演示（输入 → 理解 → 关系 → 决策 → 依据 → 结果 逐段打印）。
- **T079**：`scripts/metrics_report.py` 验收指标采集（回执分布/降级/复读/负反馈/话题延续率，支持 `--json`）。
- **测试**：**575 通过 + 2 跳过**。

## 2026-09-21 — SDD Phase 8（US4）：回归加固

- **T072/T073**：回归集新增关系阶段维度（4 阶段 × 4 意图 × 4 战况抽样）+ `devoted` 护盾前置校验、抗议只加原因码、不虚构 CD 能力三条安全断言。
- **T074**：意图白名单按域扩展（`inspect_interactable` / `pickup_item` / `rest_here` / `wait_here`），规则与 LLM 解析器同步按域分组。
- **T075**：`/v1/agent/step` 文本路径与 `/v1/tactical/command` 共用决策层（战斗意图含 US2 关系调制；非战斗意图映射 agency 行为目录）。
- **文档**：SDD 补勾 T001~T031（漏勾）+ 登记模糊记忆/RL 对话路线规格；协议契约与 README 同步新行为。

## 2026-09-17 — 语音陪伴对话端点（音频 → ASR → 对话）

- **`POST /v1/companion/chat/voice`**（`app/api/v1/companion.py`）：multipart 音频 → 转写 → **既有**对话链路——记忆/关系/信号埋点全部生效，与 `/v1/voice/command`（音频→战术指令）同款模式但尾部接陪伴对话。请求带可选 `session_id` / `world_context_json`；响应 = `CompanionDialogueResponse` + `transcribed_text`（UE 展示「你说了什么」/ 调试转写质量）。契约记入 v0.1 附录 A（附加式扩展，不升版本）。
- **错误语义**：转写故障 502、空转写 422——对话里「听错还硬答」比「明确听不清」更糟，不回退 mock 文本。
- **测试**：新增 6 例（全链路含记忆/埋点生效、空转写、转写故障、未登记角色、非法 game_state/world_context），485 → **491 通过 + 2 跳过**。转写桩注入不加载真实模型；真实 faster_whisper 质量验证留待有真人录音时（历史决策不变）。

## 2026-09-17 — 对话信号埋点（RL 路线的第 2 步：奖励的前提是数据）

- **决策**：对话生成不用 RL 替代 LLM（动作空间 10^100+ / 奖励不可自动判定 / API 模型无法做策略梯度 / 8GB 显存跑不动 RLHF 流水线）；RL 的正确位置是「导演层」——记忆调度、表现选择。先埋点攒数据，攒够几百轮真实对话后复用 `rl/boss/` 脚手架（bandit 起步）。
- **信号模块**（`services/companion/dialogue_signals.py`）：每轮对话向 `data/runtime/dialogue_signals/<companion_id>.jsonl` 追加一条记录——玩家否定反馈（实测日志出现过的「幻视/记岔/没说过/没答应/又模糊/返回相同」模式）、复读度（回复 vs 会话近期回复的字符二元组 Jaccard）、话题延续（主题重叠/包含关系，engagement 粗代理）、当轮注入的印象主题、情绪/手势/表情选择。
- **挂点**：`_record_turn`（流式/非流式汇合点），记录会话历史**之前**采集上轮文本供比较；埋点任何故障静默（同 FR-011 纪律，绝不阻塞对话）。
- **测试隔离**：`conftest` 新增 autouse 把 `AESIR_DIALOGUE_SIGNALS_DIR` 指到临时目录——信号是 RL 前置资产，测试 mock 回复混入会污染日后训练数据。
- **配置**：`AESIR_DIALOGUE_SIGNALS_DIR`（默认 `data/runtime/dialogue_signals`，`data/runtime/` 已在 .gitignore）。
- **测试**：新增 12 例（否定检测 2 + 复读度 4 + 话题延续 3 + 落盘/容错/跨轮 3），473 → **485 通过 + 2 跳过**。

## 2026-09-17 — 实测反馈二修：印象防张冠李戴 + 防编造 + 防复读

- **问题 1（张冠李戴）**：实测中艾莉说「你还说钓上来的鱼归我烤」——这话是她自己说的。上次改动让她自己的回复也入印象，但注入文案统一写成「玩家提过 X」，她把自己的话记成了玩家的话。**修复**：`TopicImpression` 新增 `origin`（player/companion，旧数据默认 player）；玩家后提及时 companion 主题升级为 player；注入文案区分——她的主题明确标注 "her own words, NOT the player's"。对话链路 `reply_topics` 落盘时标 `origin="companion"`。
- **问题 2（编造细节）**：「刚才不是还嘴硬说不怕吗」（玩家从没说过）——模糊印象注入后模型自己脑补出「具体原话」。**修复**：注入块与 system prompt 双处加 Memory honesty 指令：绝不能声称玩家说过/答应过上下文与记忆里没有的话，不确定就模糊表述或反问。
- **问题 3（复读机）**：句式「……不过……吧」反复出现，emotion/gesture 长时间锁同一个。**修复**：有会话历史时注入 Anti-repetition 指令：禁止复用近期轮次的句式/口头禅/开场（点名「……不过」模式），每轮变换句法、长度、节奏，情绪/手势/表情也要轮换。
- **控制台 `/memory` 现在展示印象**：按权重前 10 条，标注谁提的（玩家/她自己）+ 次数 + 权重；`TopicImpressionView` 增加 `origin` 字段。
- **测试**：3 个既有测试扩展断言（origin 持久化/升级、注入文案区分、控制台视图带 origin），**473 通过 + 2 跳过**（数量不变）。

## 2026-09-17 — 记忆注入改为「近期必记 + 权重衰减」（实测反馈修复）

- **问题**（真人实测反馈）：注入门槛是提及次数 ≥3 的硬门槛，而真实对话 55 条印象里 51 条只提过 1 次——昨天的闲聊 96% 被丢弃，「没有印象」；且门槛完全不看时间，与真人「时间不过太久就记得」相悖。
- **注入判定改为权重阈值**（`topics.tier_of` 重写）：不看次数、看现算权重 `log2(1+次数) × 0.5^(距上次提及天数/半衰期)`。新配置 `AESIR_MEMORY_IMPRESSION_INJECT_WEIGHT`（默认 0.75）/ `AESIR_MEMORY_IMPRESSION_DEEP_WEIGHT`（默认 2.5），取代并删除 `MIN_MENTIONS`。默认语义：昨天聊过 1 次的闲聊也记得（权重 0.91），约 3 天淡出；提 2~3 次存活约 7~10 天；郑重声明 + 在意值缩放照旧拉长存活（28 天半衰期）。**近期必记 → 随时间衰减 → 因频率和重视程度增强**。
- **注入份额 3→5**（`AESIR_MEMORY_IMPRESSION_INJECTION_SHARE` 默认值），近期话题在 prompt 文案中标注「刚聊过」，并指示模型可主动拉回近期话题（提升活人感）。
- **口语噪声碎片过滤**（`topics.looks_like_noise`）：LLM 顺带返回的主题里实测出现「不过」「趁天」「意思呀」这类连接词/语气词碎片——不成话题，注入只会让角色说怪话。合并入口（LLM 返回/规则提取/迁移）与检索侧（兜住存量旧数据）双重过滤；提取 prompt 同步要求主题必须是 2~6 字具体名词。
- **测试**：改写 8 个旧门槛语义断言，新增 11 例（近期单提/3 天淡出/频率强化存活/显著存活更久/噪声碎片 4 + store 检索 3），462 → **473 通过 + 2 跳过**。用真实 `memory.json`（昨日 55 条印象）验证：注入 5 条且噪声已拦。

## 2026-09-17 — SDD Phase 7（US6）：能力注册表 + 只读查证 + 两轮调用

- **能力注册表**（`services/skills/registry.py`，T067）：统一登记战斗行为 / 生活行为 / 信息工具三类（FR-035），且是既有配置源的**投影**而非第二份真相——测试守住「注册表与策略不漂移」。为此把战斗能力目录沉到 `tactical_policy.yaml` 新增 `abilities:` 段（ID / 展示名 / 描述），`resolver.py` 的 `ABIL_*` 常量改为从策略**派生**：能力 ID 从此只写一次，不在代码里另留一份字面量。
- **只读查证工具**（`services/skills/tools.py`，T068）：`tool.lore.query`（世界观）、`tool.world.snapshot`（战况）、`tool.world.interactables`（环境）、`tool.self.status`（自身）、`tool.memory.recall`（记忆）五个工具全部只读，输出按 `AESIR_TOOLS_OUTPUT_MAX_CHARS` 裁剪（默认 400）。未命中一律 `found=False` + `TOOL_NO_RESULT` +「没有记载」文案——**编造在工具层就是不可能的**，不是「不鼓励」（FR-037）。模型给的查证请求先过 `run_lookup` 的结构校验（类型 / 白名单）才执行。
- **两轮调用**（T069）：`llm_dialogue_service` 第一轮 prompt 附工具清单，模型可返回 `{"action":"lookup",...}` 索取查证；服务端执行只读查证后把结果回填第二轮 prompt。上限 2 轮 + 时间预算（`AESIR_TOOLS_LOOKUP_TIMEOUT_SECONDS`，超限降级为直接回应，FR-038）。流式路径复用同一逻辑：查证轮负载不含 `reply_text`，玩家不会看到半截话。`CompanionDialogueRequest` 新增**可选** `world_context` 字段（v0.1 向后兼容）——战况/环境/自身状态类查证以请求内快照为准，不用过期缓存。
- **知识库**（T070，`data/world/lore.yaml`）：首版 4 条目（艾莉 / 能力目录 / 战斗分工 / Boss 眩晕），全部登记来源（FR-012）；加载器强制「没出处不进库」。收录纪律：**只收设计文档已确立的事实**——「这个遗迹是谁建的」刻意留空，正是「明确不确定」验收路径的用例。
- **战斗链路禁用查证**（T071）：工具场景白名单不含 combat，注册表层面 `for_scene("combat", kind="info_tool")` 恒为空；查证只存在于非战斗对话链路。
- **配置**：新增 `AESIR_TOOLS_{OUTPUT_MAX_CHARS,LOOKUP_TIMEOUT_SECONDS,MAX_ROUNDS}`。
- **测试**：新增 54 例（注册表 17 + 工具命中/未命中 17 + 降级 14 + 两轮调用 6），408 → **462 通过 + 2 跳过**。

## 2026-09-16 — SDD Phase 6（US5）：世界事件统一处理 + 幂等 + 关系联动

- **统一决策层**（`services/tactical/event_policy.py`）：抽出与响应 schema 无关的 `EventEvaluation`，v0.2 `/v1/combat/events` 与 v0.3 `/v1/world/events` 共享同一张幂等表——缓存的是评估结果而非响应对象，两个通道各自组装自己的响应格式。同一 `event_id` 无论经哪个通道上报，都只评估一次、只产生一次副作用。
- **幂等键含遭遇维度**：`companion_id + encounter_id + event_id`（生活类以空串占位）。评估在锁内进行——关系计分是副作用，若挪到锁外，并发重试可能在两次查表之间都未命中而重复计分（SC-007）。
- **关系数值有了 HTTP 上报入口**（T062）：生活事件按 `data/policy/relationship_policy.yaml` 调 `relationship` 计分，`observability` 新增 `relationship_stage` / `relationship_delta` 留痕；事件不在策略表内时**跳过而非谎报「未变化」**（不加载不写盘），存储故障按 FR-041 降级不中断事件处理。原因码区分 `RELATIONSHIP_UPDATED` / `RELATIONSHIP_UNCHANGED` / `RELATIONSHIP_UNAVAILABLE`。
- **生活事件六类**（T060）：`region_first_entered`、`weather_changed`、`gift_given`、`companion_recovered`、`player_protected_companion`、`promise_kept`；人设反应新增 `world_event_reactions` 段（结构同 `combat_event_reactions`，共用白名单校验路径）。
- **战斗类经世界通道**（T061）：内嵌 `combat` 快照折成 v0.2 请求复用既有决策表，不重写策略；快照缺失时只给反应 + 保守建议，`companion_action` 恒为 `null`（FR-025 不虚构）。
- **路由瘦身**（T063）：`app/api/v1/world.py` 从 83 行降到 35 行，只留 HTTP 边界（未登记角色 404），策略全部下沉到 `event_policy`。
- **golden 样例 +2**：`world_event_gift_given.json`（关系 +3 留痕）、`world_event_boss_stunned.json`（战斗事件内嵌快照 → 爆发动作），由 `tests/api/test_world_events.py` 直接回放校验，保证 fixture 与真实端点不脱节。
- **测试**：新增 `tests/api/test_world_events.py`、`tests/api/test_world_events_idempotency.py`、`tests/services/test_event_no_fabrication.py`，净增 20 例（388 → **408 通过 + 2 跳过**）。

## 2026-09-16 — 记忆三补：主题黑名单 + 自述入印象 + 在意值缩放

- **主题黑名单**（`topics._TOPIC_BLACKLIST` + `is_blocked_topic`）：角色自指（艾莉/爱莉/alice）与记忆/对话元语言碎片（名字/记得/记住/告诉/事情/重要…）不构成「对玩家的印象」——迁移实测出现过的「艾莉」「记得」「名字」这类碎片词从此被拦下。按「包含」匹配（碎片常带粘连字如「叫艾莉」）；过滤点在 `store._merge_mentions_locked` 合并入口，LLM 顺带返回 / 规则提取 / 迁移脚本三条路径统一覆盖。
- **艾莉自身回复入印象**：`_record_turn` 对 `response.reply_text` 也提取主题并 `record_mention`（非显著）——她记得自己说过什么，反复谈起的话题同样形成印象；黑名单同步拦掉她回复里的自指。
- **在意值缩放显著记忆强度**：郑重声明的等效提及加成不再固定，而按「在意值」缩放——在意 = 偏离无感的程度，**太不喜欢也是在意的一部分**（极亲密 100 与极度讨厌 0 同为最在意，中性无感 50 最健忘）。`care_scale`：缩放乘子 = 0.25 + 1.75 × 偏离中性点(默认 50)的归一距离，钳制 [0.25, 2.0]；加成 = `SALIENCE_BOOST × care_scale(关系数值)` 在声明那一刻定格，持久化到 `TopicImpression.salience_boost`（`None` 回退全局默认，旧数据兼容），检索档位与权重按各条自带的加成现算。语义：初值 20 → 乘子 1.3（首提达 faint）；无感 50 → 0.25（郑重声明也几乎记不住）；0/100 → 2.0（首提即 deep）。在意加深取最大值强化、淡化不回退（与 `salient` 旗标同语义）。
- **配置**：新增 `AESIR_MEMORY_IMPRESSION_CARE_NEUTRAL`（默认 50，在意值中性锚点）。
- **测试**：新增 13 例（黑名单 4 + care_scale 5 + store 过滤/持久化/最大值 3 + 集成自述入印象 1）。**388 通过 + 2 跳过**。

## 2026-09-16 — 双通道记忆：郑重声明不靠频率（显著性维度）

- **缺口**：「有件重要的事情告诉你」这类一次性郑重声明，纯频率权重 log2(2)=1 达不到注入阈值，被错杀；而真人恰恰对郑重声明过一次的事记得最清楚。
- **通道 1（档案分流）**：LLM 顺带返回 `salient: true`（规则兜底线索表「记住/重要/别忘/告诉你…」）→ 玩家原话逐字入 archive（`importance=high`，容量淘汰优先保留）——玩家期待精确复述的事不适合模糊化。
- **通道 2（显著性加成）**：`TopicImpression.salient`；权重 = `log2(1+次数+2×salient) × 衰减`，郑重提过一次 ≈ 等效 3 次普通提及**首提即达注入阈值**；显著话题半衰期 7→28 天（重要的事遗忘更慢）；主题一旦显著不回退（普通提及只刷计数）。
- **判定来源**：LLM 响应新增 `salient` 键（与 `topics` 同批，零额外请求）；mock/回退路径退化为 `looks_salient()` 关键词规则。
- **配置**：`AESIR_MEMORY_IMPRESSION_SALIENCE_BOOST`（默认 2.0）、`AESIR_MEMORY_IMPRESSION_SALIENT_HALF_LIFE_DAYS`（默认 28）。
- **测试**：新增 8 例（显著性权重/慢衰减/首提达档/线索词判定/档案分流/普通闲聊不进档案等）。**375 通过 + 2 跳过**。

## 2026-09-16 — 模糊记忆模式（SDD US1 增补：主题 × 提及频率）

- **动机**：真人不会逐字记住所有对话，但对反复出现的主题形成强印象。旧「长期逐字存玩家发言」改为模糊印象层。
- **第四层记忆 `impressions`**（`schemas/memory.py`）：`TopicImpression`（主题/累计提及/首末次时间/权重），旧 `memory.json` 无此字段时默认空列表，向后兼容。
- **频率强化 + 半衰期衰减**（`services/memory/topics.py`）：权重 = `log2(1+次数) × 0.5**(距上次提及天数/半衰期)`（默认 7 天）；提及次数达阈值（默认 3）才注入 prompt——「有点印象 / 印象很深」两档口吻（`format_impression_block`），占固定注入份额（默认 3 条）不挤占记忆预算。
- **主题提取**：LLM 顺带返回（对话 JSON 响应新增 `topics` 键，零额外请求）；mock/回退路径退化为规则提取（停用词切段，质量有限、已文档注明）。
- **对话链路**：`_remember_turn` 由「逐字写短期层」改为「按主题 `record_mention`」；会话内逐字历史（session memory）不变。
- **可观测与运维**：`GET /v1/console/memory` 增加 `impressions` 视图（主题/次数/权重）；记忆重置端点顺带清空印象。
- **一次性迁移**：`python -m scripts.migrate_memory_impressions`（支持 `--dry-run`）把已存逐字发言按规则提主题后清出短期层；本地 8 条已迁移为 13 个主题印象。
- **配置**：`AESIR_MEMORY_IMPRESSION_{LIMIT,HALF_LIFE_DAYS,MIN_MENTIONS,INJECTION_SHARE}`。
- **测试**：新增 13 例（topics 单元 11 + 集成迁移/频率强化 2），改写 5 个逐字断言旧测试。**367 通过 + 2 跳过**。

## 2026-09-16 — 死代码清理（合并 main 后）

- **合并 main**：`develop-dyh` 合入 `origin/main`（RL 重构为 `rl/boss/`、scripts 按域拆分、UML/blueprint 证据文档），无冲突。
- **修复 main 既有 bug**：`rl/boss/env.py` 观测空间 `Box` 的 low/high 需 `np.asarray`（gymnasium 拒绝 tuple），修复后 main 带来的 4 个失败测试全绿。
- **死代码清理**：删除 `app/config.py` 中 6 个无代码读取的字段（`behavior_throttle_*` 已被 `agency_policy.yaml` 取代、`relationship_min/max` 已被 `_VALUE_BOUNDS` 取代、`tools_max_rounds/timeout` 属未实现的 US6 预定义）；删除 `app/schemas/ids.py` 中从未被引用的 `ABILITY_BASIC_ATTACK`、`STATE_PHASE_TWO` 常量。
- **`.gitignore`**：补 `data/rl/executions/`（record_execution 运行期回执产物，一直以 untracked 状态遗漏）。
- 全量测试 **354 通过 + 2 跳过**（main 合并后新测试基线）。

## 2026-09-15 — 陪伴对话流式输出（SSE，P1 清账）

- **`LLMClient` 流式能力**：新增 `stream_completion` 迭代器（OpenAI 兼容 `stream=true`，逐段透传 `delta.content` 原始增量、忽略 DeepSeek `reasoning_content`、异常统一包 `LLMClientError`）；`generate_json` 原样不动，非流式路径零改动。
- **服务层**：`stream_reply` 与 `reply` 共用同一 system prompt 与校验（提取共享 `_validate_dialogue_payload`），流式只是传输层差异；`_ReplyTextStreamExtractor` 从部分 JSON 增量抽取 `reply_text`（缓冲重解码，天然处理 `\n`/`\uXXXX` 转义跨 chunk 分割）。
- **SSE 端点**：`POST /v1/companion/chat/stream`（请求体复用 `CompanionDialogueRequest`），三种帧——`delta`（文本增量）/ `meta`（权威完整响应）/ `error`（中途故障）。契约以 v0.1 附加附录 A 形式记录（schema 零改动、不升版本）；非流式端点与全部既有契约测试不动、全绿。
- **回退语义**：LLM 未发出任何 delta 即失败 → 静默回退 mock（`source="fallback"`）与非流式一致；已发 delta 后中断 → `error` 帧、不写记忆（唯一行为差异，已在契约注明）。未登记角色的 404 在 SSE 响应头发出之前抛出。
- **终端调试台**：`chat_console.py` 默认改走流式端点打字机式输出（meta 帧打印来源/表现 ID 信息行），`--no-stream` 回退旧非流式路径；首字延迟从「整条生成时长」降为「首 token 时长」。
- **测试**：新增 7 例（流式服务层 4：delta 拼接/转义跨 chunk/白名单拒绝/非法 JSON；SSE API 3：帧形状与 meta 权威字段/战斗场景 422/未知角色 404）。**362 通过 + 3 冒烟跳过**。


## 2026-09-15 — SDD Phase 5 US3 自主行为体系（P1 闭环达成：她在没有战斗的时候也活着）

- **测试先行**（T044~T048）：先写五组失败测试再实现——`test_agency_domain.py`（五场景判定/战斗域排除生活行为/禁打断聚合/scene 与内嵌战斗快照矛盾以 scene 为准）、`test_agency_catalog.py`（白名单闭集/域过滤/候选生成/kind 与距离防护/关系阶段调制/YAML 非法报错）、`test_agency_arbiter.py`（六级优先级两两顺序/同级比数值再比稳定序/未知类目丢弃）、`test_agency_throttle.py`（去重窗口/窗口过期/单周期上限/角色隔离/并发安全/reset）、`test_agency_not_actionable.py`（不虚构目标/pickup 仅 item/距离超限丢弃/战斗场景空/禁打断静止）。
- **指令类型分文件**（T049）：`app/schemas/directives/{combat,movement,interaction,social,routine}.py` 各域 action_type 白名单 Literal，`common.py` 汇总 `DirectiveActionType` 联合与 `KNOWN_ACTION_TYPES`；信封 `action_type` 保持 `str`（白名单校验在目录层），不破坏既有契约。T055（表现块）Phase 2 已完成。
- **场景判定**（T050）：`app/services/agency/domain.py` 纯函数——`resolve_scene` 透传 UE 上报、`allows_lifestyle`（combat → False）、`no_interrupt_reason`（四种禁打断标志聚合为单一原因名，与策略 YAML 名单对齐）。
- **行为目录与候选生成**（T051）：`behavior_catalog.py` 参照 tactical/policy 模式加载 `agency_policy.yaml`（revision 升至 `agency-policy-002`，每行为补 `allowed_kinds`/`max_distance_m` 参数约束）；`generate_candidates` 为确定性规则驱动（无 LLM，FR-028 不猜测）——低血/夜晚休整、notable 物件查看、近距物品拾取、首访区域提醒、玩家倒地高优告警、兜底观察；三重不可执行防护：目标 ID 必须在快照、类型在白名单、距离在上限内（FR-025/FR-040）。
- **跨域仲裁**（T052）：`arbiter.py`——六级优先级（危险自保 > 战斗战术 > 玩家指令 > 剧情事件 > 关系事件 > 日常自主）来自 YAML；同级比 priority 数值再比稳定序；被压制候选保留在 `suppressed` 供可解释。
- **节流去重禁打断**（T053）：`throttle.py` 进程内（不落盘：语义窗口 300s 远小于进程生命周期，丢失最坏是重复一次行为且 UE 有最终否决权）；键 = (角色, 行为, 目标, 触发源)——同目标不同触发原因不算重复；OrderedDict + Lock + 有界缓存，与心跳限流同款模式。
- **主入口编排接入**（T054）：`POST /v1/agent/step` 纯心跳路径串联「禁打断 → 候选生成（注入关系阶段）→ 目录校验 → 仲裁 → 节流 → 指令输出」；输出 `DirectiveEnvelope`（source=autonomy，presentation 带 `gaze_target_id`，人设读取失败降级为简短 reply_text）；`policy_revision` 改读策略 YAML。文本指令路径与心跳限流 429 不变；v0.1/v0.2 契约测试零改动全绿。
- **演示**（T056）：`scripts/mock_ue_flow.py` 新增 US3 分支——营地夜晚休整（directive）、同触发源重复（THROTTLED/DEDUP_WINDOW 静止）、探索查看物件（directive + 注视目标）、剧情演出中（INTERRUPT_FORBIDDEN 静止）。
- **测试**：新增 44 例（agency 五组 41 + 主入口编排 3，原心跳用例升级为 directive 期望并新增禁打断/节流用例）。**355 通过 + 3 冒烟跳过**。

## 2026-09-14 — SDD Phase 4 US2 关系体系（关系数值/阶段/防刷/阶段化行为差异）

- **测试先行**：先写四组失败测试再实现（章程原则 IV）——`test_relationship_state.py`（阶段边界/钳制/持久化/角色分区）、`test_relationship_rules.py`（增减/冷却防刷/日上限/跨日重置/未知事件忽略）、`test_relationship_effect.py`（同一指令 × ≥3 阶段可区分）、`test_relationship_degradation.py`（损坏隔离/备份恢复/回退初值后服务可用）。
- **关系状态模型与持久化**（T036/T037）：`app/schemas/relationship.py` + `app/services/relationship/state.py`——按角色分区落盘 `data/relationship/<npc_id>/relationship.json`，原子写入 + `.bak` 单版本备份 + 损坏隔离（`.corrupt`），主文件损坏先恢复备份再回退初值（FR-018），全程服务不中断。
- **事件驱动规则**（T038）：`rules.py` 从 `data/policy/relationship_policy.yaml` 读事件表（8 类事实事件）；防刷 = 同类事件冷却窗口（`AESIR_RELATIONSHIP_EVENT_COOLDOWN_SECONDS`）+ 每日正向净变化上限（`AESIR_RELATIONSHIP_DAILY_CAP`，负向不受限）；数值钳制边界内。
- **阶段化行为差异**（T034/T039）：`effect.py` 对战术决策做阶段调制——distant（conservative）维持保守拒绝并追加关系原因码；close（devoted）低蓝下仍为玩家重建护盾动作；close（obedience=low）对危险指令追加抗议码但执行权归 UE。全部差异落在 `reason_codes`（可解释）。v0.2 契约端点（`/v1/tactical/*`）**行为不变**——关系调制以可选参数接入 resolver，完整编排在 Phase 5 主入口（T054）接入。
- **对话层接线**（T040/T041/T042）：`primary_companion.yaml` 新增 `relationship_stage_personas`（四阶段称呼与语气偏移）；LLM 系统提示注入当前阶段；`/v1/companion/chat` 响应与 `/v1/agent/step` observability 均回带 `relationship_stage`（关系故障降级为空字符串，对话不中断）。
- **演示**（T043）：`scripts/demo_relationship.py`——同一指令「护住我！」× 4 阶段决策对比；`--events` 附事件计分/防刷/日上限演示。
- **测试**：新增 25 例（US2 四组 21 + 对话接线 4）。**311 通过 + 3 冒烟跳过**。

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
