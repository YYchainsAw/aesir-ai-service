# 人格包与游戏档案 Canonical Schema（v0.2）

> 本文是 S3（T028）发布的**规范契约**：人格包目录结构、游戏档案（capability/directives）
> 的字段口径与版本规则。实现对照：`app/services/companion/persona_pack_loader.py`、
> `persona_pack_validator.py`、`profile_repository.py`。
>
> **版本纪律**：字段的新增/重命名/语义变化属于破坏性变更，必须升级
> `manifest_version` / `profile_version` / `revision` 并在本文件登记变更记录。

---

## 1. 目录布局（一进程一游戏）

```
data/
  games/
    <game_id>/
      capability.yaml      # 游戏能力档案（必填）
      directives.yaml      # 指令行为档案（按域声明 action_type 白名单）
  personas/
    <game_id>/
      <companion_id>/      # 一个人格包 = 一个目录，目录名即 companion_id
        manifest.yaml      # 必填
        persona.yaml       # 必填
        rules.yaml         # 必填
        examples.yaml      # 必填
        reactions.yaml     # 必填
        fallbacks.yaml     # 必填
        presentation.yaml  # 必填
        abilities.yaml     # 可选
```

- 进程通过环境变量 `AESIR_GAME_ID` 选择当前游戏（默认 `aesir`）；
  注册表只扫描 `data/personas/<当前 game_id>/`，跨游戏 `companion_id` 返回 404，**不回退默认角色**。
- 多游戏并存 = 每游戏一个服务实例 + 独立端口（`AESIR_SERVICE_PORT`）。
- 兼容期：旧单文件 `data/companions/*.yaml` 仍可被注册表兜底扫描；
  同一 `companion_id` 同时存在目录包与旧 YAML 时，**目录包优先**。

## 2. manifest.yaml

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `manifest_version` | str | 是 | 清单结构版本，当前 `"0.1"` |
| `profile_version` | str | 是 | 人格数据契约版本，目录包为 `"0.2"`（旧单文件为 `"0.1"`） |
| `companion_id` | str | 是 | 角色标识，须与目录名一致 |
| `game_id` | str | 是 | 归属游戏；必须与当前游戏档案 `game_id` 完全一致，否则拒绝加载 |
| `requires_capability` | str | 是 | 最低能力档 `L0`/`L3`；高于游戏档案 `capability_level` 时拒绝加载（未知等级按 -1 处理同样拒绝） |
| `checksum` | str \| null | 否 | S5 资产守卫占位；非 null 时必须是字符串 |

## 3. 数据文件 → 顶层字段映射

加载器把各文件合并为与旧单文件兼容的字典，映射关系固定：

| 文件 | 展开到顶层的键 |
|------|----------------|
| persona.yaml | `identity` / `persona` / `relationship_stage_personas` / `speaking_style` |
| rules.yaml | `conversation_rules` / `combat_expression_rules` / `tactical_acknowledgements` |
| examples.yaml | `dialogue_examples` |
| reactions.yaml | `combat_event_reactions` / `world_event_reactions` |
| fallbacks.yaml | `fallback_dialogue_responses` / `default_dialogue_response` |
| presentation.yaml | `allowed_emotion_ids` / `allowed_gesture_ids` / `allowed_facial_expression_ids` / `ue_mapping_contract` |
| abilities.yaml | 不展开，放入 `abilities`（`ability_ids` / `behavior_ids`） |

各键的内部结构与旧单文件 YAML（profile_version 0.1）一致，见 SDD v1.0 与人格配置注释。
注意：`identity.game_name` 已废弃，游戏名以 `manifest.game_id` 为准。

## 4. capability.yaml（游戏能力档案）

```yaml
game_id: aesir
revision: capability-001          # 破坏性变更必须升级
provides:
  capability_level: L3            # L0=仅对话/记忆/关系；L3=完整链路
  scenes: [combat, exploration, camp, conversation, idle]
  events:
    combat: [player_hp_critical, ...]
    world: [region_first_entered, ...]
  presentation_ids: [emotion.bright, gesture.nod, face.neutral, ...]
  abilities: [ability.alice.basic_attack, ...]
  behaviors: [follow, move_to, ...]
```

归属校验（`PersonaPackValidator`，加载即执行，失败一次性返回全部冲突）：

1. `manifest.game_id` == 档案 `game_id`
2. `manifest.requires_capability` ≤ 档案 `capability_level`
3. `conversation_rules.allowed_game_states` ⊆ 档案 `scenes`
4. 两类 reactions 的事件键 ⊆ 档案 `events`
5. 三个表现 ID 白名单 ⊆ 档案 `presentation_ids`
6. `abilities.ability_ids` / `behavior_ids` ⊆ 档案 `abilities` / `behaviors`
7. `checksum` 非 null 时必须是字符串（S5 前不验值）
8. `(game_id, companion_id)` 唯一性由目录结构保证

**声明 ≠ 实现**：档案声明的能力只表示游戏「能提供」，不被自动记为服务已实现。

## 5. directives.yaml（指令行为档案）

```yaml
game_id: aesir
revision: directives-001
schema_version: "0.3"             # 对应 app/schemas/directives DIRECTIVE_PROTOCOL_VERSION
domains:
  combat: [major_heal, quick_heal, shield, burst, retreat]
  movement: [follow, move_to, wait, retreat_move]
  interaction: [inspect, interact, pickup, observe, alert_player]
  social: [express, self_talk]
  routine: [rest, eat, repair_gear]
```

- 取值是 `app/schemas/directives/` 各域 Literal 白名单的**子集**（固定枚举 + 每游戏子集）。

## 5.1 L0/L3 运行后门控（S4/T029，已落地）

路由层按当前游戏档案 `capability_level` 门控（`app/services/games/capability_gate.py`）：

| 链路 | L0 | L3 |
|------|----|----|
| 对话（`/v1/companion/*`）、记忆、关系、调试台 | ✅ 可用 | ✅ 可用 |
| 世界事件 `/v1/world/events` | 仅放行档案 `events` 声明的事件类型 | ✅ 全量 |
| `/v1/commands/parse`、`/parse-command` | ⛔ 403 | ✅ |
| `/v1/tactical/resolve` / `/command` / `/executions` | ⛔ 403 | ✅ |
| `/v1/combat/events`、`/v1/agent/step` | ⛔ 403 | ✅ |

- 拒绝为显式 403，响应体带结构化原因：`reason_code`（`CAPABILITY_LEVEL_INSUFFICIENT` /
  `EVENT_NOT_DECLARED`）、`feature`、`game_id`、`capability_level`、`required`/`event_type`；
  不静默降级、不产生越界下发。未知能力等级按 -1 处理，门控功能同样拒绝。
- 行为级（directives.yaml 逐 action_type）门控仍在后续迭代；当前门控粒度为端点链路。

## 6. 现有档案实例

| game_id | level | 人格包 | 用途 |
|---------|-------|--------|------|
| `aesir` | L3 | companion.alice、companion.bruno | 主游戏 |
| `demo-vn` | L0 | companion.narrator | 自有第二游戏最小样例（跨游戏隔离/L0 语义验证） |

## 7. 变更记录

- **0.2（2026-10-08）**：首版发布。S2 目录化结构定稿；`game_name` 由 `identity` 上移 `manifest.game_id`；新增游戏档案选择（`AESIR_GAME_ID`）与 demo-vn 样例。
