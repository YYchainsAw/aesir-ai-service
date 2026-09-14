# 待完成 / 待优化清单

尚未排期的功能补全与体验优化。完成后移入 [CHANGELOG](../../CHANGELOG.md)
并从这里删除；排期与优先级讨论见 SDD（`aesir-agent-sdd-v1.0.md`）。

## 待优化

### P1 — 陪伴对话流式输出（2026-09-14 记录）

**现象**：`/v1/companion/chat` 走 LLM 后端时，回复是**一整条**返回的——用户要等
完整生成结束才能看到第一个字，感知响应时间长（DeepSeek 完整生成一条回复通常
数秒）。`scripts/chat_console.py` 终端调试台同样整条打印。

**优化方向**：

- 服务端：`LLMClient` 支持 OpenAI 兼容 `stream=true`，`/v1/companion/chat`
  增加流式变体（SSE），人设/情绪等结构化字段如何与流式共存需设计
  （参考方案：文本增量走 SSE，最终 `emotion_id` 等元数据放在结束帧）。
- 客户端：`chat_console.py` 按增量打字机式输出；UE 侧同理（协议改动需同步
  v0.1 契约文档并升版本号）。
- 验收标准：终端调试台**首字延迟**从「整条生成时长」降到「首 token 时长」
  （目标 <1s 量级）；非流式路径保持不变不破坏现有契约测试。

**涉及文件**：`app/services/llm/client.py`、`app/api/v1/companion.py`、
`scripts/chat_console.py`、`docs/protocols/ue-protocol-contract-v0.1.md`。
