# NPC开发闭环增量契约v0.4

> 2026-10-22，`loop-contract-v1`，随[第三步计划](../planning/step-03-execution-loop-plan.md)开发。基线 `main@e96151b`；新增支持以分支回归记录为准。本页是[v0.4作用域契约](npc-scope-contract-v0.4-draft.md)的增量，不改变既有chat/agent请求或既有回执枚举；字段以`app/schemas/loop.py`及对应golden为准。

## 1. 请求生命周期

chat和agent文本共享完整NPC/run/session队列，按服务接收并登记的顺序处理；网络重试仍由原request_id及作用域确定。规则心跳可登记状态但不占生成队列或生成并发；事件、回执和控制入口沿用自身协调器。request_id不是上游尝试ID，每次实际上游调用另有内部尝试UUID及计数。

状态为`queued/running/completed/cancelled/expired/failed/unknown`。completed表示该服务请求已完成，不表示UE动作完成。unknown表示开始提交后的结果不确定，不能换ID重做。状态键不加入epoch/binding作为绕过去重的新维度；原session、instance、binding、epoch和encounter仍逐项核对。

同会话默认最多4个等待项、全局最多16个等待项、同时2个生成请求；默认请求状态上限1024项、正常终态保留300秒。未到期项不因满额被静默淘汰。不确定提交保持占位至显式清理或进程退出。进程重启后旧绑定失效；此处不提供跨重启事务和永久查询。

| 入口 | 模型与结果 |
| --- | --- |
| POST `/v1/scoped/requests/cancel` | 原v0.4 NPC写信封加`target_request_id`、`operation=chat/agent-step`、`reason_code=USER_CANCELLED/SUPERSEDED`；响应带目标状态及`cancel_requested` |
| GET `/v1/scoped/requests/{target_request_id}` | 带`operation`和现有console相同的scope/binding/epoch查询参数；返回目标状态、原因、queue/processing/total毫秒和实际upstream_attempts |
| GET `/v1/scoped/directives/{directive_id}` | 带现有console同样的作用域参数；返回原request_id、状态、sequence及有效回执数量，不返回可执行payload或刷新有效期 |

取消未知目标可创建有界cancelled占位，阻止稍后同ID到达后继续生成。取消排队/运行中且尚未最终提交的目标生效；最终完整对话写入或指令发布开始后取消未生效，`cancel_requested=false`，不撤销已提交事实。客户端仍需独立丢弃其已取消回调。

LLM计算不持NPC/运行控制锁；最终提交在原绑定/epoch/预算及取消检查后线性化。同步供应商HTTP不保证在控制请求到来时被强制中断；返回后拒绝旧结果，并在每次后续上游尝试前重新检查。已到期/取消不按一般供应商错误回退重试或计入供应商熔断。若初次处理在最终提交后、外层校验/缓存阶段才失败，响应和生命周期改为unknown；后续读取已完成结果时遇到旧绑定或过期则拒绝回放，不把已提交事实撤销。

## 2. 最小执行反馈账本

现有`accepted/executed/rejected/expired/cancelled`不变。状态由`issued`开始，accepted仅记录收到；执行、拒绝、过期或取消是该最小账本的终态。executed只表示UE自报已执行，不推断技能命中、伤害或完整动画完成。`unknown`仅用于已知原指令的不确定写入，保留原request_id；不存在的ID不构造虚假的unknown对象。

所有回执先验证原scope/run/binding/epoch/encounter与指令关联。sequence存在时同一指令同序号不得换语义；无序号时同语义回执也去重。received_at不参与语义指纹；reported_at保留为自报记录，不用于改变处理顺序。终态后迟到accepted忽略，冲突终态拒绝；不能用重连、换HTTP请求ID或较晚reported_at倒退已记录状态。

同批回执先完整验证并在副本上演算，再一次追加成功后采纳状态。追加/flush/fsync失败后将可能受影响的订单标unknown，后续请求不得自动重做；并封锁该完整NPC/run的新指令注册和回执追加，防止后续成功记录接到损坏的JSONL尾部。封锁由unknown槽位承载，仍受总容量限制；其他run不受该封锁影响。显式clear或重启不会修复磁盘残片，重新使用日志前需人工核对。状态与日志仍不是数据库事务，跨重启恢复在第四步。

指令关联默认上限4096项、正常保留300秒，同ID同内容注册不续期；不同内容冲突。每单最多64个回执身份，超过容量明确拒绝。unknown占位保留到显式清理或进程退出，不能通过容量淘汰后自动重做。

## 3. 错误与兼容

| HTTP / 原因码 | 处理 |
| --- | --- |
| 409 REQUEST_CANCELLED | 原逻辑请求已取消；新意图需新ID，不能重用旧ID恢复旧结果 |
| 404 REQUEST_UNKNOWN / DIRECTIVE_UNKNOWN | 当前实例没有可查询记录；不伪造完成状态 |
| 503 REQUEST_QUEUE_FULL | 队列、生成准入或状态容量未开始处理时拒绝；不承诺更多并发 |
| 409 RECEIPT_SEQUENCE_CONFLICT / RECEIPT_STATE_CONFLICT / DIRECTIVE_ID_CONFLICT | 同序号/终态/已发布身份冲突，不追加或覆盖原事实 |
| 503 STATE_UNAVAILABLE / REQUEST_OUTCOME_UNKNOWN | 容量/存储不可用或提交不确定；后者不换ID重做 |

回执写入未知指令仍沿用既有409 `DIRECTIVE_UNKNOWN`，只读查询未知ID用404。原身份、绑定、epoch、预算与载荷冲突等错误继续遵循v0.4主契约。新请求/响应显式0.4、UUID和extra=forbid；旧协议及scoped SSE/语音支持状态不变。

已有跟随/等待和战术能力只修复已声明目录的映射与原能力关联；未实现的条件执行不能下发伪动作。完整started/hit/completed、UE条件监听及执行去重需后续跨端协议和真实验收。
