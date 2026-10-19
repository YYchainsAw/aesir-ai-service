# 从文本建议到UE执行

> 源码导读，2026-10-19基线`a2dd426`。本页只解释分工和排查入口；字段分别由[v0.1订单](../protocols/ue-protocol-contract-v0.1.md)、[v0.2战术](../protocols/combat-tactical-protocol-v0.2.md)、[v0.3代理](../protocols/npc-contract-v0.3.md)维护，不另复制一套。

## 先辨认三条文本路径

| 路径 | 产物 | 主要实现 |
| --- | --- | --- |
| commands/parse | v0.1 TacticalOrder判别联合；context是当前能力目录 | app/api/v1/commands.py → services/parsers/command_parser.py → rule/llm解析 |
| tactical/command | v0.2 TacticalDecision/DecisionAction；combat_context只读战斗快照 | app/api/v1/tactical.py → tactical/llm_intent.py → resolver.py |
| agent/step带text | v0.3统一DirectiveEnvelope或none；按场景分流 | app/api/v1/agent.py → 意图解析 → 战斗resolver或非战斗agency目录 |

旧parse的输出是TacticalOrder，不是resolve输入的TacticalIntent。想省往返可用tactical/command；分步调用必须自行形成合法意图，不能把两个不同模型直接连起来。闲聊走companion/chat，语音闲聊走chat/voice；voice/command只做音频转写后订单解析。

## 战斗组合端点如何工作

1. tactical.py执行当前游戏L3端点门控，解析请求结构和战斗快照。当前v0.2模型没有全面forbid，也没有统一完整的角色注册/逐能力授权入口，不把端点门控当全部安全条件。
2. parse_intent_with_source依据AESIR_INTENT_BACKEND选择规则或LLM。LLM失败回退规则；仍不理解时返回recognized=false、decision=null和澄清，不猜动作。
3. resolver读取快照和tactical_policy.yaml，检查目标/能力ready及策略条件，返回actionable或不能行动原因；它不修改UE世界。v0.2路径不接关系调制，关系编排在agent/step。
4. acknowledgement_service读取目标角色已登记的短确认语句；缺配置可回退默认文案。确认回复不证明身份已在所有旧路径完整验证，也不证明技能已经执行。
5. UE接收候选后，按**当前**角色/目标/能力/距离/冷却/忙碌/有效期和游玩/遭遇身份再次验证，走已有执行器/GAS。HTTP200、actionable或“收到”不等于能力启动、命中或胜利。
6. UE反馈真实拒绝、过期、取消或适用执行结果到tactical/executions。当前服务按天追加JSONL，202只表示记录受理，不维护完整执行状态机。

普通非施法行为可无技能；需要技能的动作必须引用当前获准能力，数量未冻结。既有DecisionAction.ability_id是旧接口字段，不能拿它推导整个领域永久只有单技能指令。

## 自主行为与世界事件

agent/step不带text才是纯心跳，按最小间隔限频，然后“禁打断→候选→目录→仲裁→节流”返回一个directive或none。服务没有后台主动推送，也不因快照存在就替UE作世界更新。

world/events是可信事实入口，先验证角色和游戏事件声明，再按角色/遭遇/event_id处理。与combat/events共享1024项进程内缓存；缓存命中回放不等于UE动作已去重。重启或淘汰后不能承诺永久幂等，执行端仍要按稳定指令ID和旧局有效性拒绝重演。

## 回执能说明什么

当前result只有accepted/executed/rejected/expired/cancelled。accepted是登记，不是完成；executed的具体事件边界需双方定义，不能由它自动推导每条都有命中阶段。单回执只陈述收到的事实，当前JSONL追加器不校验重复、乱序、终态或动作真伪。

“真实接收、启动、命中/完成”的分阶段模型属于需求目标；directive_id/order_id映射和新枚举/终态需协议设计，不能只改文档说已实现。请求game_id尚可自行指定，回执没有强制角色注册，当前按目录分区不等于已绑定当前游戏；详见[v0.3差距](../protocols/npc-contract-v0.3.md#7-当前实现差距)。

## 排查与配置生效

| 看到的现象 | 先查哪里 |
| --- | --- |
| 不能识别或被拒绝 | 请求所用端点/版本、当前场景、目录、意图source与reason_codes |
| 服务建议合法但没动作 | UE真实执行结果、目标/冷却/距离、过期与旧局身份；不只查服务日志 |
| 重复事件或回执 | 事实幂等键、1024缓存范围、执行去重键，分别定位 |
| 改.env没有变化 | 重启服务；config只在import时load_dotenv，get_settings重读的是进程环境 |
| 改策略YAML没有变化 | tactical.policy有进程缓存；重启或按正式更新流程处理，不宣传全链路热更新 |
| 配置/磁盘错误 | 实际HTTP状态与日志；解析LLM回退不能保证所有I/O永不500 |

运行记录和性能范围见[复现与验收](repro.md)，数据流与存储见[LLM指南](llm-integration.md)。Boss RL属于独立工作流，见[RL入口](../../rl/README.md)，不把NPC tactical_policy的rl占位当冻结Boss部署。
