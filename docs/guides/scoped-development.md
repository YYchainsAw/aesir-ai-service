# v0.4 作用域服务开发与交接

2026-10-21，适用于 `feature/npc-scope-v04`。字段以[v0.4契约](../protocols/npc-scope-contract-v0.4-draft.md)、`app/schemas/scoped.py` 和运行实例 `/docs` 为准；本页只维护操作、实现限制与UE后续接入顺序。

## 1. 配置与入口

继续使用项目 `.venv` 与单个 Uvicorn worker。核心依赖不变，无需安装数据库、Redis、Torch或真实ASR。

| 配置 | 默认与开发用法 |
| --- | --- |
| `AESIR_SCOPE_IDENTITY_BACKEND` | 默认 `disabled`，新版请求返回401；环回开发可设 `development` |
| `AESIR_SCOPE_DEV_PLAYER_ID` | 服务端预先登记的玩家UUID；请求体及自报header均不能覆盖 |
| `AESIR_SCOPE_DEV_SAVE_IDS` | 已授权存档UUID的JSON数组；未登记存档返回403 |
| `AESIR_SCOPE_LEGACY_ENABLED` | 默认 `false`；设为 `true` 才可运行旧协议开发客户端 |

服务器现有开发 `.env` 已显式启用固定开发身份与旧协议兼容，仍只监听 `127.0.0.1:18011`。身份和存档UUID在服务器配置内查看；它们不是密钥，也不是生产凭据。`.env` 不入库。正式认证与调试接口权限在第四步完成前，不将该开发实例公开。

严格模式只允许 `/health`、文档/OpenAPI和已实现的 `/v1/scoped/` 入口。旧chat、commands、tactical、combat、SSE、语音、console及其UI均返回403。新版SSE/语音尚无实现，返回明确的404错误，不落入旧入口。

## 2. 调用顺序

1. `GET /v1/scoped/context?save_id=...&companion_id=...` 获取服务实例、控制revision和记忆epoch。`run_id`为空时仅表示尚未绑定，普通业务请求不能隐式激活。
2. `POST /v1/scoped/runs/bind` 提交新的逻辑run、当前服务实例、预期revision与预期旧run（可为null）。后续使用返回的绑定UUID。同档所有NPC共享一个活动run。
3. 战斗前用 `POST /v1/scoped/encounters/control` 显式begin，结束时显式end；双方使用预期遭遇revision/ID，防止旧控制请求重新激活已结束遭遇。
4. 通过 `/agent/step`、`/companion/chat` 或 `/world/events` 提交同版完整信封；`/combat/events` 是世界事件模型的别名。字段与完整样例见 `data/golden/scoped/`。
5. 建议产生后，用 `/tactical/executions` 报告同归属、同绑定、同遭遇的已发布指令。202和`stored`只表示回执已记录，不表示技能启动或完成。
6. 离开时调用 `/runs/end`。服务重启后重新发现并显式绑定，不重放旧实例的业务请求。

console只读查询需要 `save_id`、`companion_id`、`service_instance_id`、`run_id`、`run_binding_id`、`memory_epoch`，可附session/encounter。清理走 `/console/memory/reset` 的完整写请求。reset响应包含新epoch；同一reset请求可回放其结果，但只在该结果epoch仍为当前值时有效。另一reset发生后旧reset回放也拒绝。

## 3. 数据、重试与有效期

| 状态 | 新版分区及保留规则 |
| --- | --- |
| 长期记忆 | `memory_root/game/player/save/companion/memory.json`，epoch和四层快照同文件原子替换 |
| 关系 | `relationship_root/game/player/save/companion/relationship.json`，同档换run保留 |
| 对话历史 | 进程内完整NPC/run/session键；UUID不截断；reset清目标NPC所有run的历史 |
| 心跳、自主抑制、观测、事件 | 完整NPC/run键；遭遇事件额外匹配当前encounter |
| 信号与回执 | 各配置根目录下的 `game/player/save/companion/run/`，记录归属、实例、绑定和epoch |
| 旧协议数据 | 保持历史 `root/game/companion` 的独立legacy命名空间；新版不读取、不认领、不自动迁移 |

去重保留窗口默认300秒，请求和事件各1024项，控制请求单独1024项；活动存档控制状态上限4096。处理中的项和窗口内结果不因容量不足被淘汰，满额拒绝503。已开始处理但持久化结果不确定时占位为`REQUEST_OUTCOME_UNKNOWN`，不自动重做。内存去重、回执关联和短期历史随进程退出丢失；当前不提供跨重启事务或永久恰好一次保证。

相同逻辑请求重试复用原request_id和语义载荷，只增加两项age；快照在首次发送前的年龄差和预算保持不变。响应`timing.valid_for_ms`从客户端首次发送起算，缓存不刷新；UE用同一首次发送单调时钟扣除已用时间。时效预算上限120000毫秒，0预算立即过期。UTC只供记录，不用UE与服务器墙钟相减。

同一event经两个新版通道、使用同一request_id重试会复用原结果与指令ID。若相同event_id使用另一个request_id重报，原事实/反应可以重放，但返回`duplicate=true`、`action=none`和空directive，避免把旧动作关联到新的首次发送时钟；原捕获基准或语义冲突仍拒绝409。receipt需引用实际收到的原指令ID，不能用新请求人为补发旧动作。

LLM计算期间不持提交锁；写入前同时检查当前run/encounter、epoch和单调预算。reset仅清记忆与会话，保留关系、人格和历史日志。元数据损坏返回503，不从旧epoch备份恢复。多文件副作用不是数据库事务，磁盘部分失败可能已经留下部分记录，因此UNKNOWN需要人工核对或第四步持久化方案处理。

## 4. 验证与UE后续交接

本轮只使用服务器pytest/TestClient、临时目录、mock业务和受控时钟。命令及实测结果见[验证记录](../logs/verification-records.md#scope-20261021)。不调用付费LLM、不安装可选ASR/RL、不修改UE或测试UE连接。

UE接入时须完成：保存可信会话与save/run/encounter关联；换局取消在途请求并使旧回调失效；重试保留原request_id、快照及首次发送时钟；复核instance/binding/epoch/encounter和预算；在Action/GAS启动前检查能力、目标、资源、距离及动作锁；按实际执行事实回执。同档重进保留长期状态不等于完整SaveGame检查点回滚。第三步另行实现执行阶段闭环与真实端到端采样。
