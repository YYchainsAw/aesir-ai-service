# Boss 强化学习

`rl/boss/` 训练、评估和部署 Boss 高层动作策略，使用 MaskablePPO；NPC 服务 `app/` 不导入它。模拟器规则基线 `RuleBossPolicy` 与 UE 的 `BT_AesirBoss` 是不同实现，模拟器成绩不能直接代表 UE 实战。

## 运行入口

以下命令在仓库根目录执行。安装 RL 依赖后，可运行规则基线评估；`--episodes` 是每种玩家画像的局数，三种画像各 20 局即总计 60 局。

```powershell
.\.venv\Scripts\python -m pip install -r requirements-rl.txt
.\.venv\Scripts\python scripts\rl\boss\eval.py --episodes 20 --seed 0 --json
```

当前 `eval.py` **只评估规则基线**，没有加载冻结 PPO 的参数。无需重训的冻结模型独立评估入口、逐局原始输出及精确复评命令仍待实现，不能把此命令写成 PPO 测试。

训练冒烟命令与正式训练示例如下；它们会写入 `models/rl/boss/`，本轮文档整理没有执行训练。

```powershell
.\.venv\Scripts\python scripts\rl\boss\train.py --timesteps 20000 --name boss_smoke

.\.venv\Scripts\python scripts\rl\boss\train.py `
  --timesteps 1000000 --seed 0 --n-envs 8 --eval-episodes 100 `
  --checkpoint-freq 100000 --periodic-eval-freq 100000 `
  --periodic-eval-episodes 30 --name ppo_boss_schema_v4_sim005_seed_0

.\.venv\Scripts\python -m tensorboard.main --logdir models\rl\boss\tensorboard
```

训练生成最终 ZIP、配置与指标 manifest、周期 checkpoint、周期评估的最佳模型和 TensorBoard 日志。`--resume <checkpoint.zip>` 续训；`--disable-tensorboard` 仅用于轻量冒烟。训练结束的评估使用最终模型，不能自动算作对部署候选的独立测试，也不能把 `best_model.zip` 与最终 ZIP 混用。

## 当前部署候选

以下为 2026-10-19 对本机现存文件的核对，模型身份与选模数字沿用原始记录。本机文件不等于公开仓库已交付模型。

| 项目 | 当前记录 |
| --- | --- |
| 观察与动作 | Schema 4，26 维观察、9 种 Boss 高层动作 |
| 模拟器 / 奖励 | `boss-sim-005` / `boss-reward-003` |
| 冻结候选 | `models/rl/boss/deployment/boss_policy_schema_v4_sim005.zip` |
| 原训练模型 | `models/rl/boss/ppo_boss_schema_v4_sim005_seed_1.zip`，seed 1 |
| 训练记录 | 同目录 `ppo_boss_schema_v4_sim005_seed_1.manifest.json`；部署目录附同内容 `boss_policy_schema_v4_sim005.training.manifest.json` |
| 选模记录 | `models/rl/boss/deployment/boss_policy_schema_v4_sim005.selection.json` |
| ZIP SHA-256 | `dd79ceca0e0f079634364754d1959212b0cdb357439ab9ef8e36d3ba4ed64add` |

`selection_evaluation` 使用 `base_seed=50000`，aggressive、defensive、evasive 各 300 局，共 900 局；Boss 胜率为 0.8433，分画像 0.553 / 0.977 / 1.0。**这是选模汇总，不能再次充当独立测试集或 UE 成绩。** 未找到对应 900 局逐局原始输出；训练曲线、完整复现命令和独立测试数据仍需整理。2026-09-10 的“3 种子、2/3 达标、眩晕窗口施爆裂”属于旧队友实验，不能作为此 Boss 模型的上线依据，详见[验证记录](../docs/logs/verification-records.md)。

`models/` 被 Git 忽略，新克隆没有默认 ZIP。当前没有仓库内可核验的公开下载入口；交付者需提供以上 ZIP、selection、训练 manifest 及依赖记录，并记录实际保管或获取位置。不要用同名空文件或新训练结果替代原候选。获取后在仓库根核对：

```powershell
Get-FileHash -LiteralPath models/rl/boss/deployment/boss_policy_schema_v4_sim005.zip -Algorithm SHA256
```

## 冻结策略 HTTP 服务

独立推理接口已经存在，默认端口 `8012`，与 NPC 服务 `8011` 分开。模型到位且依赖齐全后启动：

```powershell
.\.venv\Scripts\python scripts\rl\boss\serve.py
```

可用 `--model <实际ZIP路径>` 指定文件。`GET /health` 返回服务信息；`POST /v1/boss/policy/decide` 接受 Schema 4 观察，返回一个高层动作或 `actionable=false` 的合法暂时无动作。GAS 动作可用性和真实启动、命中、伤害仍由 UE 复核。

当前加载器只检查文件存在并加载，**不会自动核对 selection SHA、训练版本和部署身份**；`model_id` 来自文件名，health 中模拟器修订来自当前源码。人工核对文件的结果不能写成运行时已完成身份校验。

UE 已确认目标为连续 3 次通信、协议或非法动作错误后切 BT，保持到本场遭遇结束；仅完整合法响应清零，合法暂时无动作不算故障。UE 当前 PolicyClient 在动作字段校验前清零，存在连续非法动作累积失效的已知缺陷；模型身份完整核验、终局取消与同遭遇策略段关联也需联调，参见 [UE RL 契约](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/08_RL_Research/01_BossRLContract.md)、[已知问题](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/06_Test_Doc/02_KnownIssues.md)。这些 UE 目标不表示 Python 或两端已验收。

NPC LLM 使用独立的默认 **5 次失败 / 60 秒恢复窗口**熔断机制，不采用 Boss 的“本场保持 BT”规则。正式对照、故障与时延统计见 [UE 评估方案](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/08_RL_Research/03_EvaluationProtocol.md)；本仓实施缺口见[未决清单](../docs/planning/todo.md)，模型视图见 [UML 入口](../docs/design/uml/README.md)。