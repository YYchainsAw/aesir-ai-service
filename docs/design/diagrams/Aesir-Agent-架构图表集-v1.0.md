# Aesir Agent — 架构图表集（流程图 · 时序图 · UML 图）

> **文档性质**：项目需求规格（[`docs/planning/aesir-agent-sdd-v1.0.md`](../../planning/aesir-agent-sdd-v1.0.md)）的可视化配套产物。
>
> **版本**：v1.0　**日期**：2026-09-14　**状态**：待评审
> **项目**：Aesir（UE5 第三人称 ARPG）— NPC 人格与行为代理系统
> **分工**：dyh（Python Agent 服务、协议与策略）／yjx（UE 战斗与 NPC 行为、指令组件、表现层）
>
> **制图工具**：Mermaid（GitHub 技能 `diagram-creator`，MIT）。
>
> **事实来源与约束**：本图表集所有字段名、枚举值、阶段划分、阈值均取自仓库当前真实代码与配置
> （`app/schemas/*`、`app/api/v1/*`、`data/policy/*.yaml`、`data/companions/*.yaml`），
> **不含任何虚构内容**；"待实现/占位"部分已明确标注。

## 目录

| 编号 | 图名 | 类型 | 主要依据 |
| --- | --- | --- | --- |
| 图 1 | 系统总体架构图 | 流程图 | SDD 第三部分 结构决策 |
| 图 2 | 主入口决策主链路 | 流程图 | FR-021 / FR-024 / FR-025 / FR-028 |
| 图 3 | 自主行为心跳引擎 | 流程图 | FR-020 / FR-022 / FR-023 |
| 图 4 | 记忆体系（分级·淘汰·降级） | 流程图 | FR-006 ~ FR-012 |
| 图 5 | 关系体系（事件驱动·防刷·阶段） | 流程图 | FR-013 ~ FR-018 |
| 图 6 | 玩家指令链路 | 时序图 | US4 / 章程 III |
| 图 7 | 自发行为心跳链路 | 时序图 | US3 / FR-021 |
| 图 8 | 世界事件幂等链路 | 时序图 | US5 / FR-032 ~ FR-034 |
| 图 9 | 核心数据模型 | UML 类图 | Key Entities |
| 图 10 | 关系阶段状态机 | UML 状态图 | FR-016 · relationship_policy.yaml |
| 图 11 | 活动场景状态机 | UML 状态图 | FR-019 |
| 图 12 | 部署拓扑图 | UML 部署图 | 技术约束·运行与部署 |
| 图 13 | 实体关系图（ER） | ER 图 | Key Entities |

---

# 一、流程图（Flowchart）

## 图 1　系统总体架构图

**类型**：Architecture Flowchart　**方向**：TB（上→下）
**用途**：给评审/新成员一张图看懂「谁负责什么、数据怎么流、什么是可选依赖」。
**要点**：UE5 客户端（yjx）是唯一权威端；Python 服务（dyh）只产出受限指令；持久化用本地文件，不引入数据库。

```mermaid
flowchart TB
    subgraph UE["UE5 客户端（yjx）— 唯一权威端"]
        U1["世界状态采集<br/>WorldContext 快照"]
        U2["文本 / 语音输入"]
        U3["指令执行 + 二次校验<br/>目标 / 距离 / 资源 / 冷却 / 可达性"]
        U4["表现层<br/>表情 · 动作 · 台词 · 镜头"]
    end

    subgraph SVC["Python Agent 服务（dyh）· FastAPI + Pydantic v2 · 仅监听回环"]
        subgraph API["API 层　app/api/v1"]
            A1["agent.py<br/>心跳 + 指令统一入口"]
            A2["world.py<br/>世界事件入口"]
            A3["console.py<br/>调试 / 记忆重置"]
            A4["companion · tactical · voice · speech<br/>既有端点（保留兼容）"]
        end
        subgraph SCHEMA["协议层　app/schemas"]
            S1["directives/common.py<br/>统一指令信封"]
            S2["world_context.py<br/>世界状态快照"]
            S3["world_event.py<br/>世界事件"]
            S4["agent_step.py<br/>主入口请求/响应"]
        end
        subgraph DOMAIN["服务层　app/services"]
            D1["agency/<br/>场景判定 · 仲裁 · 节流"]
            D2["memory/<br/>分级存储 · 摘要 · 检索"]
            D3["relationship/<br/>数值 · 阶段 · 规则"]
            D4["skills/<br/>能力注册 · 只读查证"]
            D5["companion/<br/>人格注册 · 对话编排"]
            D6["tactical/<br/>意图解析 · 决策 · 幂等"]
        end
    end

    subgraph DATA["本地数据资产（无数据库 / 无中间件）"]
        F1["data/companions/*.yaml<br/>人格 + 表现 ID 白名单"]
        F2["data/policy/*.yaml<br/>关系 / 活动域 / 战斗策略"]
        F3["data/lore/aesir/lore.yaml<br/>世界观知识库"]
        F4["data/memory/ 按 npc_id 分区<br/>持久化记忆与关系（运行期生成）"]
    end

    LLM{{"可选依赖<br/>LLM / 语音模型<br/>不可用时规则降级"}}

    U1 -->|"HTTP 回环　/v1/agent/step"| A1
    U2 -->|"/v1/world/events"| A2
    API --> DOMAIN
    DOMAIN --> DATA
    D1 --> F2
    D2 --> F4
    D3 --> F4
    D4 --> F3
    D5 --> F1
    D6 --> F2
    D5 -.->|"可选"| LLM
    A1 -->|"受限 DirectiveEnvelope"| U3
    U3 --> U4
    U3 -.->|"执行回执<br/>仅观测，不回改事实"| A3

    classDef client fill:#e3f2fd,stroke:#1565c0,color:#0d47a1
    classDef svc fill:#fff8e1,stroke:#f9a825,color:#e65100
    classDef data fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef opt fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    class U1,U2,U3,U4 client
    class A1,A2,A3,A4,S1,S2,S3,S4,D1,D2,D3,D4,D5,D6 svc
    class F1,F2,F3,F4 data
    class LLM opt
```

**读图提示**：`solid 边` 为必需链路，`dotted 边` 为可选/旁路（模型降级、回执观测）。
**依据**：章程原则 III（UE 权威）、VII（简单优先）；SDD §第三部分「Structure Decision」。

---

## 图 2　主入口决策主链路

**类型**：Process Flowchart　**方向**：TD
**用途**：说明一次 `/v1/agent/step` 请求从进来到出去的完整判定顺序与失败出口。
**要点**：心跳与指令**共用同一入口**（单一指令体系，FR-045）；任何条件不满足都返回**明确说明而非虚构动作**（FR-025）。

```mermaid
flowchart TD
    Start(["UE 调用 /v1/agent/step"]) --> Chk{"companion_id 已登记？"}
    Chk -->|"否"| E404["404 明确拒绝<br/>不回退默认角色人格 (FR-044)"]
    Chk -->|"是"| Kind{"请求携带 text？"}

    Kind -->|"否 · 纯心跳"| Rate{"距上次心跳 ≥ 最小间隔？"}
    Rate -->|"否"| E429["429 心跳过频 (FR-022)"]
    Rate -->|"是"| Dom["场景判定 agency/domain.py<br/>combat / exploration / camp / conversation / idle"]

    Kind -->|"是 · 玩家指令"| Parse["意图解析 intent_parser<br/>规则优先 → 失败降级模型 (FR-027)"]
    Parse --> Clar{"意图可确定？"}
    Clar -->|"否"| Ask["以角色口吻请求澄清<br/>不猜测执行 (FR-028)"]
    Clar -->|"是"| Dom

    Dom --> Cand["汇集候选行为<br/>自主候选 + 玩家指令 + 事件候选"]
    Cand --> Arb["跨域仲裁 agency/arbiter.py<br/>危险自保 &gt; 战斗战术 &gt; 玩家指令 &gt; 剧情 &gt; 关系 &gt; 日常 (FR-024)"]
    Arb --> Cat{"行为在白名单内<br/>且目标 / 资源满足？"}
    Cat -->|"否"| NoAct["返回不可执行说明<br/>不虚构行为 (FR-025 / FR-030)"]
    Cat -->|"是"| Out["产出 DirectiveEnvelope<br/>含 reason_codes · policy_revision"]

    NoAct --> Resp(["AgentStepResponse<br/>action = none / directive"])
    Out --> Resp
    Ask --> Resp
    E404 --> Resp
    E429 --> Resp
    Resp --> UE2["UE 二次校验并执行<br/>保有最终否决权（章程 III）"]

    classDef ok fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef warn fill:#fff9c4,stroke:#f9a825,color:#e65100
    classDef bad fill:#ffcdd2,stroke:#c62828,color:#b71c1c
    class Out,UE2 ok
    class Arb,Cand,Dom warn
    class E404,E429,NoAct,Ask bad
```

---

## 图 3　自主行为心跳引擎

**类型**：Process Flowchart　**方向**：TD
**用途**：说明"她为什么会在没有命令时动一下"，以及为什么会**不动**。
**要点**：服务**不主动推送**，只在心跳响应里返回（FR-021）；节流 + 去重 + 禁打断三重护栏（FR-022 / FR-023）。

```mermaid
flowchart TD
    HB(["心跳：UE 上报 WorldContext"]) --> Th{"距上次同触发源<br/>小于去重窗口 300s？"}
    Th -->|"是"| Silent["抑制：不产出（去重）(FR-022)"]
    Th -->|"否"| NI{"命中禁打断情形？<br/>剧情演出 / 玩家说话 / NPC 施法 / 界面弹窗"}
    NI -->|"是"| Silent
    NI -->|"否"| Src["匹配触发源<br/>notable 物件 / 世界时间 / 天气 / 区域首次进入"]
    Src --> Any{"存在候选行为？"}
    Any -->|"否"| Empty["空动作轻量返回<br/>NO_AUTONOMOUS_CANDIDATE"]
    Any -->|"是"| Pri["按优先级取行为<br/>behavior_catalog 白名单 (FR-020)"]
    Pri --> Cnt{"本周期触发次数<br/>&lt; max_per_window = 3？"}
    Cnt -->|"否"| Silent
    Cnt -->|"是"| Dedup["写入去重窗口 + 计数"]
    Dedup --> Out["DirectiveEnvelope<br/>source = autonomy"]
    Silent --> R(["action = none"])
    Empty --> R
    Out --> R2(["action = directive<br/>交 UE 二次校验"])

    classDef ok fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef gate fill:#fff8e1,stroke:#f9a825,color:#e65100
    classDef stop fill:#eceff1,stroke:#78909c,color:#37474f
    class Out,R2 ok
    class Th,NI,Any,Cnt,Pri gate
    class Silent,Empty stop
```

**配置锚点**：`data/policy/agency_policy.yaml` → `throttle.dedup_window_seconds=300`、`max_per_window=3`、`no_interrupt_when=[cutscene_playing, player_speaking, npc_casting, ui_popup]`。

---

## 图 4　记忆体系（分级 · 淘汰 · 降级）

**类型**：Process Flowchart　**方向**：TD
**用途**：说明"她记得我"在实现上如何分层、何时落盘、满了怎么办、坏了怎么办。
**要点**：承诺类/重大事件**优先级高于容量淘汰**（FR-008）；存储不可用时降级为无长期记忆但**流程不中断**（FR-011）。

```mermaid
flowchart TD
    In(["对话 / 事件输入"]) --> Write["事件触发式落盘<br/>（非逐条写盘）"]
    Write --> L1["L1 会话窗口<br/>当前会话短期上下文"]
    Write --> L2["L2 经历摘要<br/>跨会话摘要"]
    Write --> L3["L3 长期档案<br/>关系事实 / 承诺"]

    L3 --> Guard{"承诺类 / 重大事件？"}
    Guard -->|"是"| Keep["优先保留<br/>不参与淘汰 (FR-008)"]
    Guard -->|"否"| Cap{"达到容量上限？"}
    L2 --> Cap
    Cap -->|"是"| Evict["按重要度 + 时间淘汰低价值条目"]
    Cap -->|"否"| Hold["保留"]
    Keep --> Persist[("data/memory/&lt;npc_id&gt;/<br/>原子写入 + 单版本备份")]
    Evict --> Persist
    Hold --> Persist

    Q(["生成回应"]) --> Ret["检索 retrieval.py<br/>按重要度排序 + 预算截断 (FR-009)"]
    Persist --> Ret
    Ret --> Inj["注入对话上下文（可控预算）"]
    Inj --> Out(["回应 + 记忆引用"])

    Fail{"存储不可用 / 文件损坏？"} -->|"是"| Deg["降级：仅用 L1 会话窗口<br/>响应标记 degraded = true (FR-011)"]
    Deg --> Out
    Reset(["玩家执行记忆重置"]) --> Clear["清空该 NPC 记忆<br/>回到初始人格 (FR-010)"]
    Clear --> Persist

    classDef store fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef ok fill:#e3f2fd,stroke:#1565c0,color:#0d47a1
    classDef warn fill:#fff9c4,stroke:#f9a825,color:#e65100
    class Persist store
    class Inj,Out,Ret ok
    class Deg,Evict warn
```

---

## 图 5　关系体系（事件驱动 · 防刷 · 阶段）

**类型**：Process Flowchart　**方向**：TD
**用途**：说明好感度如何由**事实事件**驱动、如何防刷、如何转化为可观察的行为差异。
**要点**：事件表与幅度**全部在 YAML**（章程 I）；同类重复触发数值变化为 **0**（SC-004）。

```mermaid
flowchart TD
    Ev(["UE 上报事实事件"]) --> Known{"事件在<br/>relationship_policy.events 中？"}
    Known -->|"否"| Ignore["忽略 · 不计分"]
    Known -->|"是"| Cool{"冷却窗口内同类重复？(FR-015)"}
    Cool -->|"是"| Zero["数值变化 = 0（防刷）"]
    Cool -->|"否"| Day{"超出当日净变化上限？"}
    Day -->|"是"| Clamp["截断至上限"]
    Day -->|"否"| Apply["按 delta 增减<br/>promise_kept +8 / promise_broken -8 / gift_given +3 …"]
    Clamp --> Bound["钳制到 [0, 100] (FR-018)"]
    Apply --> Bound
    Bound --> Stage["映射关系阶段<br/>distant · neutral · friendly · close"]
    Stage --> Effect["阶段化可观察差异 (FR-016)<br/>称呼语气 / 主动度 / 资源投入意愿 / 服从度"]
    Effect --> Persist[("持久化<br/>data/memory/&lt;npc_id&gt;/ (FR-013)")]
    Effect --> Decision["作为决策输入<br/>resolver / dialogue_service"]
    zero(["数值异常 / 文件损坏"]) -.-> Fallback["以初始关系继续运行 (FR-018)"]

    classDef ok fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef stop fill:#eceff1,stroke:#78909c,color:#37474f
    classDef warn fill:#fff9c4,stroke:#f9a825,color:#e65100
    class Stage,Effect,Decision ok
    class Ignore,Zero stop
    class Clamp,Fallback warn
```

**事件表锚点**：`data/policy/relationship_policy.yaml` → `events`（8 类），`stages`（4 段），`bounds = [0,100], initial=20`。

---

# 二、时序图（Sequence Diagram）

## 图 6　玩家指令链路（文本 / 语音统一）

**类型**：Sequence Diagram
**用途**：答辩主线——一句话指令如何变成 NPC 的行为，以及**为什么**。
**要点**：同一句指令在不同战况/关系阶段产出不同结果（FR-029）；语音转写后与文本走**同一条**后续处理（FR-026）。

```mermaid
sequenceDiagram
    autonumber
    participant P as 玩家
    participant UE as UE5 客户端（yjx）
    participant AG as /v1/agent/step
    participant MEM as memory + relationship
    participant IP as intent_parser
    participant RS as resolver / 仲裁

    P->>UE: 文本 或 语音下达战术意图
    UE->>AG: POST /v1/agent/step（world_context + text）
    AG->>AG: 角色登记校验（未登记 → 404）
    AG->>MEM: 读取关系阶段 + 预算内记忆
    MEM-->>AG: 关系阶段 / 记忆摘要
    AG->>IP: 解析意图（规则优先，失败降级模型）
    alt 意图不可确定
        IP-->>AG: 未识别
        AG-->>UE: 请求澄清（不猜测执行, FR-028）
    else 意图明确
        IP-->>AG: 受白名单约束的语义意图
        AG->>RS: 结合战况 / NPC 状态 / 关系阶段决策
        RS-->>AG: 决策 + reason_codes
        AG-->>UE: DirectiveEnvelope（受限指令 + 表现块）
    end
    UE->>UE: 二次校验（目标 / 距离 / 资源 / 冷却 / 可达性）
    alt 校验通过
        UE-->>P: 执行行为并播放表现
        UE->>AG: 执行回执（仅观测，不回改事实）
    else 校验否决
        UE-->>P: 拒绝执行（UE 为唯一权威端）
    end
```

---

## 图 7　自发行为心跳链路

**类型**：Sequence Diagram
**用途**：说明非战斗时 NPC 的自主行为**由 UE 心跳驱动、服务被动响应**，绝不主动推送。
**要点**：`loop` 表示固定间隔心跳；每条心跳都可能以 `action=none` 快速返回（性能目标：无产出 < 100ms）。

```mermaid
sequenceDiagram
    autonumber
    participant UE as UE5 客户端（yjx）
    participant AG as /v1/agent/step
    participant DM as agency/domain
    participant TH as agency/throttle
    participant AR as agency/arbiter

    loop 固定间隔心跳（受最小间隔限流）
        UE->>AG: 心跳 WorldContext（无 text）
        AG->>AG: 心跳限流校验（过频 → 429）
        AG->>DM: 依据快照判定活动场景
        DM-->>AG: combat / exploration / camp / conversation / idle
        AG->>TH: 禁打断 & 去重 & 次数检查
        alt 禁打断 或 窗口内已触发
            TH-->>AG: 抑制
            AG-->>UE: action = none（空动作轻量返回）
        else 放行且存在候选
            TH-->>AG: 放行
            AG->>AR: 候选按六级优先级仲裁
            AR-->>AG: 最高优先级行为（如 alert_player）
            AG-->>UE: DirectiveEnvelope（source = autonomy）
        end
    end
    UE->>UE: 二次校验并执行表现
```

---

## 图 8　世界事件幂等链路

**类型**：Sequence Diagram
**用途**：说明"同一次事件因网络重试被重复上报时**不会复读**"。
**要点**：幂等键 = `companion_id + event_id`（FR-033）；能力不可用时**动作置空但台词与建议照常返回**（FR-037 / FR-025）。

```mermaid
sequenceDiagram
    autonumber
    participant UE as UE5 客户端（yjx）
    participant WD as /v1/world/events
    participant EP as event_policy（幂等）
    participant REL as relationship/rules
    participant PR as 人格表现白名单

    UE->>WD: 上报事件（event_id, type, sequence, world_context）
    WD->>WD: 事件类型白名单校验（未知类型 → 422）
    WD->>EP: 查询幂等键 companion_id + event_id
    alt 重复上报（网络重试）
        EP-->>WD: 命中首次结果
        WD-->>UE: duplicate = true，回放首次反应，不产生新行为
    else 首次处理
        EP->>REL: 联动关系事件（如 gift_given +3）
        REL-->>EP: 关系数值更新
        EP->>PR: 取角色化反应（ID 须在白名单内）
        PR-->>EP: reply_text / emotion_id / gesture_id
        Note over EP: 能力不可用时动作置空，<br/>仍返回台词与建议（不虚构, FR-025）
        EP-->>WD: 反应 + 可选建议
        WD-->>UE: WorldEventResponse（duplicate = false）
    end
```

---

# 三、UML 图

## 图 9　核心数据模型（UML 类图）

**类型**：UML Class Diagram
**用途**：开发者的字段级参照，等价于协议 v0.3 的数据契约速查表。
**要点**：字段名与类型与 `app/schemas/` 真实代码一一对应；`&lt;&lt;union&gt;&gt;` 为判别联合。

```mermaid
classDiagram
    class AgentStepRequest {
        +str protocol_version
        +UUID request_id
        +str companion_id
        +WorldContext world_context
        +str text
        +str session_id
    }
    class AgentStepResponse {
        +str protocol_version
        +UUID request_id
        +str companion_id
        +str action
        +DirectiveEnvelope directive
        +str reply_text
        +AgentStepObservability observability
    }
    class AgentStepObservability {
        +str source
        +list~str~ reason_codes
        +str policy_revision
        +str used_snapshot_id
        +bool degraded
    }
    class DirectiveEnvelope {
        +UUID directive_id
        +str agent_id
        +DirectiveDomain domain
        +str action_type
        +int priority
        +DirectiveExpires expires
        +str source
        +list~str~ reason_codes
        +str policy_revision
        +dict payload
        +DirectivePresentation presentation
    }
    class DirectivePresentation {
        +str reply_text
        +str emotion_id
        +str gesture_id
        +str facial_expression_id
        +bool interruptible
        +str gaze_target_id
    }
    class DirectiveExpires {
        <<union>>
        +str type
        +float remaining_seconds
    }
    class WorldContext {
        +str snapshot_id
        +str captured_at
        +Scene scene
        +WorldTime world_time
        +WorldRegion region
        +WorldPlayerState player
        +WorldCompanionState companion
        +list~WorldInteractable~ interactables
        +bool ui_popup
        +bool cutscene_playing
        +bool player_speaking
        +CombatContext combat
    }
    class WorldTime {
        +str game_clock
        +str time_of_day
        +str weather
    }
    class WorldRegion {
        +str region_id
        +bool first_visit
    }
    class WorldPlayerState {
        +str id
        +float hp_percent
        +bool is_downed
    }
    class WorldCompanionState {
        +str id
        +float hp_percent
        +float mp_percent
        +str current_behavior
        +bool is_casting
    }
    class WorldInteractable {
        +str object_id
        +str kind
        +float distance_m
        +bool notable
    }
    class WorldEvent {
        +str event_id
        +str event_type
        +str occurred_at
        +int sequence
        +dict details
    }
    class WorldEventRequest {
        +str protocol_version
        +str request_id
        +str companion_id
        +WorldEvent event
        +WorldContext world_context
    }
    class WorldEventResponse {
        +str protocol_version
        +str request_id
        +str companion_id
        +str event_id
        +bool duplicate
        +WorldEventReaction reaction
        +str recommendation_text
        +WorldEventObservability observability
    }
    class WorldEventReaction {
        +str reply_text
        +str emotion_id
        +str gesture_id
        +str facial_expression_id
    }
    class MemoryEntry {
        +str entry_id
        +str content
        +int importance
        +str occurred_at
        +str source
        +list~str~ tags
    }
    class RelationshipState {
        +str npc_id
        +str player_id
        +int value
        +str stage
        +list~str~ recent_events
        +int daily_net_change
    }
    class NPCProfile {
        +str profile_version
        +str id
        +str display_name
        +dict persona
        +dict relationship_to_player
        +list~str~ expression_whitelist
    }

    AgentStepRequest --> WorldContext
    AgentStepResponse --> DirectiveEnvelope
    AgentStepResponse --> AgentStepObservability
    DirectiveEnvelope --> DirectivePresentation
    DirectiveEnvelope --> DirectiveExpires
    WorldContext --> WorldTime
    WorldContext --> WorldRegion
    WorldContext --> WorldPlayerState
    WorldContext --> WorldCompanionState
    WorldContext --> WorldInteractable
    WorldEventRequest --> WorldEvent
    WorldEventRequest --> WorldContext
    WorldEventResponse --> WorldEventReaction
    DirectiveEnvelope ..> RelationshipState : 决策参考
    DirectiveEnvelope ..> MemoryEntry : 决策参考
    RelationshipState ..> NPCProfile : 阶段偏移配置
```

> 说明：`Scene` / `DirectiveDomain` 为同一枚举的两处别名
> （`Literal["combat","exploration","camp","conversation","idle"]`）。
> 图中省略了 `CombatContext`（v0.2 既有契约，未做语义改动）的内部字段。

---

## 图 10　关系阶段状态机（UML 状态图）

**类型**：UML State Machine Diagram
**用途**：说明好感度的状态跃迁与**每阶段的可观察差异**（用于 US2 的独立验收）。
**要点**：阶段命名与区间来自 `relationship_policy.yaml` 真实配置；数值钳制在 `[0,100]`。

```mermaid
stateDiagram-v2
    direction LR
    [*] --> distant : 初值 20（区间 0–24）
    distant --> neutral : 累计 ≥ 25
    neutral --> friendly : 累计 ≥ 50
    friendly --> close : 累计 ≥ 75
    close --> friendly : 负向事件回落
    friendly --> neutral : 负向事件回落
    neutral --> distant : 负向事件回落
    distant --> distant : 钳制 [0,100]

    note right of distant
        疏远 distant
        称呼「旅行者」
        主动度 low · 资源投入 conservative · 服从度 high
    end note
    note right of close
        亲密 close
        称呼「指挥官」
        主动度 high · 资源投入 devoted · 服从度 low
        （有权以角色口吻反对送死指令）
    end note
```

---

## 图 11　活动场景状态机（UML 状态图）

**类型**：UML State Machine Diagram
**用途**：说明五类活动域的切换关系与"战斗域排除生活类行为"的边界。
**要点**：场景由 UE 上报的快照判定（`agency/domain.py`），非法取值 422。

```mermaid
stateDiagram-v2
    direction LR
    [*] --> idle : 初始 / 无活动
    idle --> exploration : 玩家移动 / 进入区域
    exploration --> combat : 遭遇敌人
    combat --> exploration : 战斗结束且仍在探索
    combat --> idle : 战斗结束且无其他活动
    exploration --> camp : 进入营地
    camp --> exploration : 离开营地
    camp --> idle : 休整结束
    idle --> conversation : 玩家发起对话
    exploration --> conversation : 玩家发起对话
    conversation --> idle : 对话结束
    conversation --> exploration : 对话结束且仍在探索

    note right of combat
        战斗域：仅产出战斗相关行为
        排除生活类自主行为（FR-019 / T050）
    end note
```

---

## 图 12　部署拓扑图（UML 部署图）

**类型**：UML Deployment Diagram
**用途**：说明"单机回环、无外网也能跑通规则链路"的部署形态。
**要点**：服务仅监听回环地址；持久化用本地文件；模型/语音为**可选**依赖。

```mermaid
flowchart LR
    subgraph HOST["开发者本机 · Windows 11（单机部署）"]
        subgraph CP["UE5 运行时进程（yjx）"]
            C1["Game Client<br/>世界采集 · 指令执行 · 表现"]
        end
        subgraph SP["Python 服务进程（dyh）"]
            S1["Uvicorn + FastAPI<br/>仅监听 127.0.0.1"]
            S2["本地文件持久化<br/>JSON / JSONL"]
        end
        subgraph FSR["本地文件系统"]
            F1["data/companions · data/policy · data/world"]
            F2["data/memory（运行期生成）"]
            F3["data/rl/executions（回执）"]
        end
    end
    EXT{{"可选外部依赖<br/>LLM API / 语音模型<br/>缺失时规则链路完整可用"}}

    C1 -->|"HTTP 回环 /v1/agent/step · /v1/world/events"| S1
    S1 --> S2
    S2 --> FSR
    S1 -.->|"可选"| EXT

    classDef client fill:#e3f2fd,stroke:#1565c0,color:#0d47a1
    classDef svc fill:#fff8e1,stroke:#f9a825,color:#e65100
    classDef data fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef opt fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    class C1 client
    class S1,S2 svc
    class F1,F2,F3 data
    class EXT opt
```

---

## 图 13　实体关系图（ER）

**类型**：ER Diagram
**用途**：Key Entities 之间"谁约束谁、谁生成谁"的数据关系一目了然。
**要点**：无数据库，实体以文件/内存对象落地；`MEMORY_ENTRY` 与 `RELATIONSHIP_STATE` 按 `npc_id` 分区隔离（US8）。

```mermaid
erDiagram
    NPC_PROFILE ||--o{ MEMORY_ARCHIVE : "定义人格边界"
    NPC_PROFILE ||--o{ RELATIONSHIP_STATE : "提供阶段偏移配置"
    MEMORY_ARCHIVE ||--o{ MEMORY_ENTRY : "聚合"
    RELATIONSHIP_STATE ||--o{ MEMORY_ENTRY : "写入长期事实"
    WORLD_CONTEXT ||--o{ DIRECTIVE : "约束可引用 ID"
    WORLD_EVENT ||--o{ DIRECTIVE : "触发候选行为"
    DIRECTIVE ||--o| EXECUTION_RECEIPT : "UE 回执"

    NPC_PROFILE {
        string profile_version
        string id PK
        string display_name
        string persona
        string expression_whitelist
    }
    MEMORY_ARCHIVE {
        string npc_id PK
        string tier
        int capacity
    }
    MEMORY_ENTRY {
        string entry_id PK
        string npc_id FK
        string content
        int importance
        string occurred_at
        string source
    }
    RELATIONSHIP_STATE {
        string npc_id PK
        string player_id PK
        int value
        string stage
        string recent_events
    }
    WORLD_CONTEXT {
        string snapshot_id PK
        string scene
        string captured_at
    }
    WORLD_EVENT {
        string event_id PK
        string event_type
        int sequence
    }
    DIRECTIVE {
        string directive_id PK
        string agent_id FK
        string domain
        string action_type
        int priority
        string source
    }
    EXECUTION_RECEIPT {
        string directive_id FK
        string status
        string reason
    }
```

---

# 附录　与需求文档的对应关系

| 图表 | 对应 SDD 章节 |
| --- | --- |
| 图 1 / 图 12 | 第三部分 实施计划 · 结构决策 · 技术上下文 |
| 图 2 | 第二部分 FR-021 / FR-024 / FR-025 / FR-028 / FR-044 |
| 图 3 | 第二部分 FR-020 / FR-022 / FR-023 · US3 |
| 图 4 | 第二部分 FR-006 ~ FR-012 · US1 |
| 图 5 | 第二部分 FR-013 ~ FR-018 · US2 |
| 图 6 | US4 · 章程原则 III |
| 图 7 | US3 · FR-021 |
| 图 8 | US5 · FR-032 ~ FR-034 |
| 图 9 / 图 13 | 第二部分 Key Entities |
| 图 10 | FR-016 · `relationship_policy.yaml` |
| 图 11 | FR-019 · `agency_policy.yaml` |
