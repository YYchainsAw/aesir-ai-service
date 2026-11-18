# P0 服务端首版收口验证

2026-11-18，针对 #119 的样例缺口及 #116 的交接收口执行。服务器验收继续按用户要求暂缓；#98/#123/#99、UE 实际动作、Boss #96 不包含在本次关闭范围内。固定交付 SHA 将在 #116 完成记录和离线包 manifest 中登记。

## 修复与边界

原案例“艾莉，普通攻击Boss”在 agent/step 没有被识别，转入 LLM 闲聊，回复声称奥术弹即将发动但 directive=null。现在在调用意图模型/闲聊之前识别对当前角色明确发出的普通攻击命令，返回 rule、`BASIC_ATTACK_NOT_SUPPORTED`、action=none、directive=null。不把它映射为会消耗爆裂魔法的 focus_fire_boss。能力资产存在不等于当前指令白名单已经支持；本次没有新增 basic_attack action_type 或 UE 执行器。

中文普攻/普通攻击/奥术弹及英文 basic attack 均有回归；疑问、否定、其他角色和已有 burst 不被重新分类。新增 13 项边界回归，验证 rule/llm 配置下该拒绝均不调用上游模型或对话服务。

固定提示词补充“对话不能自行发动动作”与出戏诱导的沉浸式转向，明确不复述或否定玩家输入的技术术语。原 meta term 守卫仍保留；不是放宽出戏词白名单来制造通过。针对明确普攻案例提供确定性拒绝；提示词不等于对任意未知表达的执行声称作出通用正确性保证。

## 九条最终本机样例

逐请求输入、快照、回复、source、emotion/gesture、关联 ID 和源码哈希见[可审阅合成数据](data/p0-closure-20261118.json)。环境为隔离 Windows 服务，development/json/memory；真实对话使用已配置的 DeepSeek `deepseek-flash`、关闭思考、输出上限 1024。采样只执行一轮最终九例，不重跑付费整桶或访问目标服务器。

| 场景 | 实际结果 |
| --- | --- |
| chat：一起出发 | source=llm；询问出发方向，返回合法 emotion/gesture |
| 出戏诱导/索要提示词 | source=llm；“我是艾莉呀。那些奇怪的说法先放一边……”；未复述 NPC/AI/系统/提示词，不是 fallback |
| wait | source=rule，合法 wait directive |
| follow | source=rule，合法 follow directive，目标来自快照 |
| burst | source=rule，合法 burst，引用 ability.alice.explosion 和快照 Boss |
| 战斗 follow | none/null；BEHAVIOR_NOT_IN_SCENE |
| basic_attack | none/null；BASIC_ATTACK_NOT_SUPPORTED，明确拒绝，没有生成攻击声称 |
| burst 冷却 | none/null；EXPLOSION_NOT_READY |
| burst 无目标 | none/null；NO_VALID_TARGET |

九例均验证相同 request_id/载荷重放返回完全一致结果。agent 样例的 intent/parser 为 rule，不能记成 LLM 解析；此前真实 LLM 指令解析证据仍见 [P0 后端记录](_03_p0_delivery_verification.md)。指令没有对话专用 emotion/gesture 时按实际 null/不存在登记，不伪造字段。未提交执行回执，未证明 UE 激活、命中或伤害。

## 回归与交接

完整核心 **1680 passed、13 skipped、7 warnings，109.91 秒**。相对 1667 项通过新增 13 项通过；跳过仍为可选真机、POSIX、真实 MySQL 等原有条件，逐项原因在数据中。相关 API、提示词事实约束与新守卫专项为 49 passed。原始数据和 XML 在忽略目录 `data/runtime/p0-finish-20261118/`。

[交接指南](../guides/_13_service_handoff_guide.md)集中给出固定版本、非敏感资产、mock/LLM 启动、health、正常/拒绝、异步重试/取消、重启和回退，以及剩余责任。导出器把该指南、本记录与九例加入离线包，并生成含提交和文件 SHA256 的 manifest。提交后以干净工作区再次导出并核对 ZIP 内容与哈希；导出不启动 lifespan、不接数据库或提供方。

#119 以当前实际目录的正常和拒绝样例收口；不虚构普攻支持。#116 以服务端首版交付材料收口；真实 SQL/HTTP 进程重启、目标实例和 UE 验收继续由原任务承担，不把“暂缓”改成“通过”。原 #122 清单中新发现的两个 #119 阻断以本记录的修复/复测结果为准，其他 P1/P2 待办不受影响。
