# RL 可行性分析与框架设计

> 版本：v0.1（2026-09-07）
> 依据：`AI队友系统总策划书_v0.1.md` §8（Phase 4 可选 RL）、
> `战斗事件与上下文感知战术协议_v0.2-草案.md` §7（executions 回执）、
> `开发记录_2026-09-02.md`（RL 缺件清单：Boss 状态、动作空间、奖励事件、可复现训练场）。
> 本文回答两个问题：**哪些部分可以 RL？现在搭了什么？**

---

## 1. 背景与定位

总策划书对 RL 的定位是明确的：

- Phase 4（可选）：「将 RL 仅接入艾莉的**高层走位/输出时机**实验，与规则策略 A/B 比较」；
- 「规则系统始终保留，RL 失败或置信不足时可回退」；
- 「RL 可先做 Python 侧模拟器」；
- 非目标：「在首个闭环中训练并上线强化学习策略」。

即：RL 是**旁路实验**，不是主路径；指令理解与上下文战术落地（规则策略）可独立完整交付。

## 2. 组件可训练性评级（分析核心）

| 组件 | 可训练性 | 奖励信号可得性 | 现状 | 建议阶段 |
| --- | --- | --- | --- | --- |
| **决策阈值调优**（`PLAYER_HP_LOW`/`PLAYER_HP_CRITICAL`/`COMPANION_MP_LOW`） | ★★★ 上下文赌博机（contextual bandit） | ★★★ 回执 `accepted/executed` 比例 + 事后玩家存活 | 阈值硬编码于 `resolver.py` | 近期；等 executions 真实数据积累 |
| **爆发时机**（眩晕窗口内放大招） | ★★★ 本模拟器主攻项 | ★★★ sim 内可精确计算；真数据=眩晕窗口伤害 | 规则固定「ready 即放」 | 当前；模拟器训练 |
| **资源管理**（MP/CD 分配、低蓝保守） | ★★☆ 模拟器可覆盖 | ★★☆ sim 可算 MP 效率；真数据难归因 | 规则硬阈值（<20 保守） | 当前；模拟器训练 |
| **高层走位/站位**（总策划书指定的 RL 目标） | ★★☆ 需 UE 集成位置观测 | ★★☆ 生存+距离维度可算，但需 UE 数据 | 无（协议明确高频位置数据留 UE） | 远期；需新低频观测接口 |
| **ASR 纠错/词典优化** | ★☆☆ CER 可作奖励但样本难集 | ★☆☆ 真人调优已取消（无录音样本） | `asr_eval.py` 脚手架保留 | 不排期 |
| **人设对话优化** | ✗ 设计上排除 | ✗ 主观体验无可靠奖励 | 模板+ID 白名单，刻意人工化 | 永不（架构决策） |
| **逐帧微操** | ✗ 设计上排除 | ✗ 协议明确高频数据留 UE | UE 行为树 | 永不（架构决策） |

**结论**：最可训且最值得先做的是「爆发时机 + 资源管理」（模拟器闭环已搭好）；
其次是「决策阈值调优」（bandit，等真实回执数据）；走位是总策划书指定的终局目标但依赖 UE。

## 3. 已搭建的框架（本次落地）

### 3.1 架构与依赖隔离

```
app/（服务运行时，零 RL 依赖）
  ├─ /v1/tactical/executions   UE 回执 → data/rl/executions/*.jsonl
  └─ resolver.py 规则策略（A/B 基线，生产代码）
rl/（顶层包，服务进程物理上不会 import）
  ├─ sim/core.py      BossSim 模拟器内核（纯 Python，无三方依赖）
  ├─ sim/constants.py 全部数值一处集中（治疗阈值直接引用 resolver 常量，保证同源）
  ├─ policy/base.py   ActingPolicy（环境层）/ TacticalPolicy（服务层接入占位）
  ├─ policy/rule.py   RulePolicyAdapter：包装生产 resolve_intent 作为基线
  ├─ rewards.py       纯函数奖励
  ├─ features.py      CombatContext → 17 维观测（L2）
  ├─ env.py           AliceBossEnv（Gymnasium，L2）
  └─ eval_utils.py    跑 N 局 + 指标聚合
scripts/rl_train.py  PPO 训练（L3）
scripts/rl_eval.py   A/B 评测（L3）
```

依赖四层：L0 服务（requirements.txt）→ L1 模拟器+规则适配（纯标准库）→
L2 Gymnasium（requirements-rl.txt 前两项）→ L3 训练（sb3+torch CPU）。
**不装 requirements-rl.txt 时全量测试仍然全绿**（RL 用例自动 skip）。

### 3.2 模拟器（BossSim）

> ⚠️ **粗略近似声明**：所有数值是编造的，仅供策略间**相对比较**（A/B），
> 不代表 UE 实际数值；结论不可直接外推到真实战斗。

- **tick = 1s，单 Boss 单遭遇，max 300 tick**；全程 `random.Random(seed)` 确定性，同 seed 逐 tick 可复现。
- **眩晕循环**（复刻 `prepare_burst_on_stun` 语义）：玩家普攻 +3/甲弹 +4/爆裂 +40 眩晕值；
  ≥100 → 眩晕 6s，期间 Boss 不攻击、受伤害 ×2.5；结束清零重新积累。**这就是核心奖励区**。
- **Boss**：HP 100；hp≤50 → phase2（伤害 ×1.5），hp≤20 → phase3 狂暴（×2）；
  每 tick 对玩家 3 伤；8% 概率 AOE 波及同伴（8~15 伤）。
- **同伴**：MP 100，回 2/tick；爆裂 35 蓝/30s CD/-15 HP；快疗 15/8s/+25；强疗 40/25s/+60；
  护盾 20/15s/3 tick 减伤 80%；甲弹 0/1s/-2。
- **动作 Discrete(7)**：0 noop / 1 甲弹 / 2 爆裂 / 3 快疗 / 4 强疗 / 5 护盾 / 6 撤退
  （follow 在单 Boss sim 中无意义，省略；撤退=4 tick 玩家减伤 50% 且停止输出）。

### 3.3 奖励函数（`rl/rewards.py`，权重扫描只动常量）

| 信号 | 公式 | 意图 |
| --- | --- | --- |
| Boss 伤害 | `+0.05/点` 全部来源；同伴主动技能在眩晕窗口内的部分**额外** ×2.5 计权 | 奖励「等窗口再爆发」（玩家自动输出不计权，避免奖励不可控输出） |
| 玩家存活 | 每 tick `+0.05` | 生存导向 |
| 浪费治疗 | 玩家 HP>70 时施疗 `-1.0` | 惩治无效施法 |
| 无效施法 | 蓝不足/CD 中 `-0.5` | 资源纪律 |
| 终局 | Boss 死 `+10`；玩家倒 `-10`；同伴倒 `-5` | 强信号 |
| 步惩罚 | 每 tick `-0.01` | 防 noop 刷生存奖励 |

### 3.4 A/B 基线与公平性

`RulePolicyAdapter` 直接调用**生产** `resolve_intent()`——基线就是线上同一份代码。
它需要一个「sim 状态 → 意图」的启发式映射（危急→治疗、眩晕→爆发、临近 80%→等爆发、
低血+护盾 ready→保护、其余→集火）。因此 A/B 度量的是「意图映射 + 决策表」的合计行为，
与线上架构（LLM/规则出意图 → resolver 决策）一致。**映射规则固定为当前一版，
A/B 结论对它敏感**（信息不对称：规则基线知道的东西和线上意图来源不完全等价）。

### 3.5 当前基线数据（2026-09-07，30 局，种子 0 起）

> 表内 rule 行已随「奖励计权只作用于同伴主动技能」的修正重算；ppo 行仍为修正前
> 的 20k 步冒烟值，正式 A/B 需待 100 万步训练后统一重跑。

| agent | mean_reward | win_rate | mean_ticks | stun_burst_rate |
| --- | --- | --- | --- | --- |
| rule | 17.62 | 1.00 | 15.0 | **0.00** |
| ppo(20k 步冒烟) | 18.98（修正前） | 1.00 | 22.0 | 0.00 |

注意 `stun_burst_rate=0.00`：规则基线的意图映射在非眩晕期也走 `focus_fire`→
`_burst`，把爆裂浪费在窗口外，真眩晕来临时技能在 CD。**这正是 RL 应该能学到的空间**；
也是 evaluation 里最需要盯防的指标。20k 步 PPO 尚欠训练（击杀更慢），
正式结论需 100 万步 + 多种子。

## 4. 8GB VRAM / 硬件预算

- MLP 策略 PPO：显存 <100MB，**默认 CPU 训练**（`device="cpu"`）——MLP 上 GPU 收益极小，
  且避免与 faster-whisper（8GB 显存主力）冲突。两者不同时驻留即无任何冲突。
- 100 万步 PPO（n_envs=8，CPU）预计 20~40 分钟（i7 级笔记本 CPU）。
- torch 与 faster-whisper 的 numpy 兼容：torch≥2.3 支持 numpy 2，实测共存无冲突。

## 5. 数据通道

| 通道 | 归属 | 格式 | 用途 |
| --- | --- | --- | --- |
| `POST /v1/tactical/executions` | 服务侧（UE 真实数据） | `data/rl/executions/{YYYYMMDD}.jsonl` | 未来 bandit/离线 RL 的原始信号；**不自动用于训练**（草案 §7） |

回执数据使用纪律（继承草案 §7）：必须经**筛选和人工评测**才能进训练集；
`policy_revision` 字段贯穿决策与回执，可区分 rule/rl 来源。

## 6. Sim-to-real 差距风险清单

1. **数值是编造的**：伤害/CD/耗蓝均为猜测值，策略学到的「时机」结构（等窗口、省蓝）
   比具体数值更可迁移；上线前必须用 UE 真实数值重训或至少重评。
2. **规则基线的信息不对称**：适配器的意图映射是额外的高层决策器，规则「总分」
   含映射贡献；A/B 对映射版本敏感（已固定一版并注明）。
3. **模拟器没有走位**：总策划书指定的 RL 主目标（走位/输出时机）在本 sim 中只覆盖
   「时机」一半；走位需要 UE 低频观测接口（协议已预留：「另建低频观测接口，不污染该协议」）。
4. **reward hacking**：noop 拖时间刷生存奖励——靠步惩罚 + `stun_burst_rate`/胜率
   联合判定盯防（见 §8）。

## 7. 迁移路径（每步都有规则回退）

```
① 离线模拟训练（当前）          scripts/rl_train.py / rl_eval.py，sim 内 A/B
      ↓
② 回执数据集积累（UE 接入后）    /v1/tactical/executions 落 JSONL，人工筛选
      ↓
③ 阈值 bandit（近期可做）        用回执 accepted/executed 比例离线调 resolver 阈值
      ↓
④ UE 走位实验（远期，可选）      低频观测接口 + AESIR_TACTICAL_POLICY=rl 灰度
```

服务接入点已预留：`AESIR_TACTICAL_POLICY`（`app/config.py`）；
`rl/policy/base.py::TacticalPolicy` 协议（`CombatContext → TacticalDecision`）；
设为 `rl` 但未接入时降级走规则并在 `policy_revision` 保留 `rl-pending` 标记
（「规则系统始终保留」原则的代码化）。

## 8. A/B 方法论与 RL 上线判定

`scripts/rl_eval.py --episodes N --agents rule,models/rl/xxx`，各 agent 用**同一
种子序列**保证可比。指标：mean_reward、win_rate（Boss 击杀率）、player_survival、
mean_ticks、**stun_burst_rate**（眩晕窗口内爆裂施放占比）。

**上线判定标准**（全部满足才考虑）：

1. win_rate ≥ 规则基线（不牺牲胜率）；
2. stun_burst_rate 显著高于规则基线（学到「等窗口」）；
3. 多种子（≥3）重复成立，非单种子幸运；
4. 真实 UE 数值复训/重评后仍成立。

任一不满足 → 继续留在规则策略（这也符合总策划书「RL 失败可回退」的预期）。

## 9. 复现命令

```powershell
# 全量测试（不装 RL 依赖也全绿）
.\.venv\Scripts\python -m pytest tests/ -q
# 装 RL 依赖 + 冒烟训练（~1-2 分钟）
.\.venv\Scripts\python -m pip install -r requirements-rl.txt
.\.venv\Scripts\python scripts\rl_train.py --timesteps 20000 --seed 0
# A/B 评测
.\.venv\Scripts\python scripts\rl_eval.py --episodes 50 --agents rule,models/rl/ppo_bossfight
# 训练冒烟测试
$env:AESIR_RL_SMOKE = "1"; .\.venv\Scripts\python -m pytest tests/test_rl_train_smoke.py -q
```
