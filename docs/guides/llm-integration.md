# LLM、语音与数据流

> 2026-10-19按`a2dd426`整理。本页说明如何选择后端、哪些内容会发送/保存和失败如何反馈；不承诺任意自然语言都能正确执行。启动方式见[本机启动](getting-started.md)，类型见[契约入口](../protocols/npc-contract-v0.3.md)。

未来部署位置与当前后端能力分开看：[15 项分工对照](../planning/ai-capability-placement.md)规定队友语义/对话/检索/长期状态运行在服务器，Boss 和即时控制在游戏本地。当前 ASR 仍只有 `mock`／`faster_whisper`；初期优先外部 ASR 是后续适配目标，届时需补音频发送、保留和超时说明。本页“本机”指运行 Python 的机器，不固定指玩家电脑。

## 选择要切换的后端

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| AESIR_PARSER_BACKEND | rule | v0.1订单解析；llm失败回退规则，无法识别仍可recognized=false |
| AESIR_INTENT_BACKEND | rule | tactical/command及agent文本意图；只解释想做什么，具体动作仍由规则/目录与UE校验 |
| AESIR_COMPANION_BACKEND | mock | 非战斗人格对话；llm失败可回退角色候选回复，source=fallback |
| AESIR_ASR_BACKEND | mock | mock或本机faster_whisper；与LLM后端不是一个开关 |
| AESIR_TACTICAL_POLICY | rule | rl仅占位；选择rl不代表NPC战术已经接入Boss PPO |

.env仅放本机配置，不提交真实密钥。复制.env.example后填写实际使用的后端。支持OpenAI兼容接口，但默认Settings的LLM地址/模型/密钥为空，需要显式配置，不把DeepSeek示例说成代码内置后端。

```ini
AESIR_PARSER_BACKEND=llm
AESIR_INTENT_BACKEND=llm
AESIR_COMPANION_BACKEND=llm
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=<仅在本机填写，不提交>
LLM_TIMEOUT_SECONDS=15
```

以上DeepSeek仅为兼容后端配置示例，不代表本轮已联网验证。替换后端仍需核对URL、模型、凭据、结构化输出和超时。改.env后重启`python -m scripts.run_server`；get_settings不缓存进程环境不等于.env文件即时重载。

## 失败与可判定结果

- 解析LLM返回不合法结构/未授权ID、超时或配置缺失时回退规则；规则也不理解时返回澄清或recognized=false，不能据“有回退”保证玩家命令必执行。
- 对话LLM经人格/表达和事实检查；非流式可重试后回退mock候选。流式在首delta前失败可回退；已输出后中断以error结束，不把半段当完整回复，具体见[v0.1 SSE](../protocols/ue-protocol-contract-v0.1.md#附录-a-陪伴对话-sse-流式端点v01-附加扩展2026-09-15)。
- 共享LLM熔断默认连续失败5次、恢复窗口60秒；这是LLM配置，不是Boss三错切BT。当前熔断状态与各调用路径降级要按实际响应/观测核对。
- 服务只给建议，UE仍检查角色、目标、能力、当前游玩、冷却、距离、忙碌及有效期。合法结构不是实际启动/命中/完成；磁盘、策略或配置等错误也不因解析层回退而全部被保证消除。

## 实际数据发送与保存

| 数据 | 当前实现路径 | 保留/清理边界 |
| --- | --- | --- |
| 指令文本和当前目录 | LLM订单解析把玩家文本、角色/能力/目标/状态目录放入配置后端的chat/completions请求；意图解析也发送文本与适用角色约束 | 不因服务监听127.0.0.1就认定未外发；实际后端及允许字段在启用时列明 |
| 对话文本与人格 | LLM对话发送当前输入、人格/表达/能力约束，及实际检索到的长期记忆、印象、近期会话和适用工具结果 | 不把服务本地reset当后端数据删除；远端保留规则需按实际部署确认 |
| 会话窗口 | 传session_id时内存维护近期轮次与情绪 | 不传仅关闭该窗口，不关闭长期记忆/关系/信号；目标角色reset清会话 |
| 长期记忆/印象 | 正常对话提取主题/有依据事实；显著声明可逐字入档案，世界事实可写经历 | 按game/角色持久化；reset清目标记忆但不清人格/关系。持久失败可能部分完成 |
| 对话信号 | 正常完成轮次默认尝试追加完整player_text/reply_text和观测字段到data/runtime/dialogue_signals/<game>/<角色>.jsonl | 当前没有专门启用开关或自动保留期限；写失败不阻塞回复；memory/reset不清这些日志 |
| 执行回执 | 按game/UTC天追加JSONL，用于排查和后续数据筛选 | 当前只追加、不验证阶段真伪；不自动用于训练，memory/reset也不清回执 |
| 音频 | 现有入口读入内存，mock或本机faster_whisper处理；该路径未显式保存原始音频文件 | 不把“未写音频”扩张成“转写文本也未保存”；新增远端ASR时需重新说明发送与保留 |

本地存储/信号可能包含个人对话，不能把“默认只摘要”当现实现状。当前没有自动脱敏、用户级删除或远端清除保证；允许上下文、后端和保留策略未决定时保留未决项，不凭文档整理新增已获授权的承诺。人格包及游戏作用域也不是面向公网的完整账户/鉴权方案。

本表依据dialogue_service、dialogue_signals、llm_dialogue_service和共享client的静态数据流；本轮未读取密钥、抓取真实出站请求或核实任何后端供应商政策。

## 联调时留什么

先在无私密输入下检查规则/mock，再显式启用所需真实后端。记录服务commit、配置项名称（密钥隐藏）、输入/目录、source、原因码、是否降级和实际UE结果，按[复现手册](repro.md)区分API样本与完整执行证据。分享前检查文本、记忆与日志；凭据若已暴露，应由持有人处理撤销或轮换，不把轮换操作写成已完成。
