# Aesir AI Service

为 **Aesir Combat Prototype** 提供本地 AI 服务。第一阶段负责把玩家的文本战术指令转换为 UE 可校验的 `TacticalOrder` JSON；后续扩展语音识别、LLM 指令解析和强化学习走位策略。

## 启动

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

服务启动后访问：

- `http://127.0.0.1:8000/health`：健康检查
- `http://127.0.0.1:8000/docs`：交互式接口文档

## 当前接口

`POST /parse-command`

请求：

```json
{
  "text": "艾琳，等 Boss 眩晕时使用爆裂魔法"
}
```

响应中的 `order` 是传给 UE 的受限战术命令。当前为规则解析器，支持以下 5 条指令：

| 指令 | intent | 动作 |
| --- | --- | --- |
| 艾琳，等 Boss 眩晕时使用爆裂魔法 | `conditional_cast` | `CastAbility(Explosion)` |
| 艾琳，保留爆裂魔法 | `hold_ability` | `HoldAbility(Explosion)` |
| 艾琳，撤退并优先保命 | `retreat` | `Retreat` |
| 艾琳，跟随我并保持距离 | `follow_keep_distance` | `Follow(Player)` |
| 艾琳，优先普通攻击 | `prioritize_attack` | `Attack` |

不识别的文本会明确返回 `recognized: false` 且 `order: null`。未来只替换 `app/services/command_parser.py`，不改变 UE 通信协议。

## 测试

```powershell
.\.venv\Scripts\python -m pytest
```
