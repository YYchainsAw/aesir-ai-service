# Boss 强化学习

`rl/boss/` 训练、评估和部署 Boss 高层动作策略，使用 MaskablePPO；NPC 服务 `app/` 不导入它。模拟器规则基线 `RuleBossPolicy` 与 UE 的 `BT_AesirBoss` 是不同实现，模拟器成绩不能直接代表 UE 实战。

部署目标见[15 项能力分工](../docs/planning/ai-capability-placement.md)（`placement-v1`，AI-DEP-01/02/14/15）及[六步方案第五步](../docs/planning/local-boss-cloud-companion-roadmap.md)：源码可在服务器开发，冻结推理发行到玩家电脑；训练/正式评估与在线 NPC 服务隔离。第五步实现与验收见[实施计划](../docs/planning/step-05-boss-local-release-plan.md)、[本地发行指南](../docs/guides/boss-local-release.md)及[验证记录](../docs/logs/verification-records.md#boss-release-20261023)；包构建、独立模拟评估与UE实战分别记录，自动更新不在本次实现。

## 运行入口

以下命令在仓库根目录执行。安装 RL 依赖后，可运行规则基线评估；`--episodes` 是每种玩家画像的局数，三种画像各 20 局即总计 60 局。

```powershell
.\.venv\Scripts\python -m pip install -r requirements-rl.txt
.\.venv\Scripts\python scripts\rl\boss\eval.py --episodes 20 --seed 0 --json
```

默认 `eval.py` 仍只评估规则基线。第五步新增 `--policy frozen|compare --model <固定ZIP> --out <全新目录>`，通过生产运行时加载原冻结候选且不训练；compare使用同画像/seed比较PPO与模拟器Rule并保留逐局JSONL、summary和实验manifest。命令和种子边界见[发行指南](../docs/guides/boss-local-release.md#4-无重训冻结评估)，不能把默认rule命令写成PPO测试或UE BT成绩。

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

`models/` 被 Git 忽略，新克隆没有默认 ZIP。当前没有仓库内公开模型下载入口；第五步已把原ZIP、selection、训练manifest及依赖随受控Windows运行包交付，本机和服务器私有制品位置、包SHA及取用边界见[本轮验证](../docs/logs/verification-records.md#boss-release-20261023)。Git clone仍只得到源码，模型原件不入Git。不要用同名空文件或新训练结果替代原候选。获取后在仓库根核对：

```powershell
Get-FileHash -LiteralPath models/rl/boss/deployment/boss_policy_schema_v4_sim005.zip -Algorithm SHA256
```

## 本地交付与版本发布

2026-10-21用户采纳Boss冻结推理在玩家本机运行：初始程序、依赖、模型和材料随游戏交付，服务器提供可信版本清单和可选更新，训练与在线NPC服务分开调度。首期复用下述独立HTTP服务；ONNX/NNE为后续候选，第五步新增Windows原生onedir构建和独立EXE校验/自测入口；自动下载和UE进程管理仍待各自实现。清单需包含SHA、Schema/动作和游戏/推理运行时兼容性；签名验证、菜单阶段切换、失败回滚及断网行为只在[UE部署说明](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/02_Design_Doc/TDD/06_Deployment.md)维护，服务端要求见[部署指南](../docs/guides/deployment.md)。正式研究固定模型并关闭自动更新。

## 冻结策略 HTTP 服务

独立推理接口已经存在，默认端口 `8012`，与 NPC 服务 `8011` 分开。模型到位且依赖齐全后启动：

```powershell
.\.venv\Scripts\python scripts\rl\boss\serve.py
```

可用 `--model <实际ZIP路径>` 指定文件。`GET /health` 返回服务信息；`POST /v1/boss/policy/decide` 接受 Schema 4 观察，返回一个高层动作或 `actionable=false` 的合法暂时无动作。GAS 动作可用性和真实启动、命中、伤害仍由 UE 复核。

第五步加载器先按版本库中的 `rl/boss/deployment.json` 验证原ZIP/selection/training三份固定SHA，再核对Schema、sim/reward、seed、原模型来源、26项有序特征和9动作映射，加载后验证实际模型空间；只接受该受信候选，CPU线程为1/1，不训练。health/响应保留model_id并增加model_sha256/release_id，health提供材料来源，不暴露本机模型路径。观察拒绝NaN/Inf，预测必须为mask允许的整数动作；全锁态合法暂时无动作。源码CLI仅允许literal loopback，冻结EXE只允许127.0.0.1。当前UE尚未验证新增强身份字段，因此服务门禁通过不等于UE接入完成。

UE 已确认目标为连续 3 次通信、协议或非法动作错误后切 BT，保持到本场遭遇结束；仅完整合法响应清零，合法暂时无动作不算故障。UE 当前 PolicyClient 在动作字段校验前清零，存在连续非法动作累积失效的已知缺陷；模型身份完整核验、终局取消与同遭遇策略段关联也需联调，参见 [UE RL 契约](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/08_RL_Research/01_BossRLContract.md)、[已知问题](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/06_Test_Doc/02_KnownIssues.md)。这些 UE 目标不表示 Python 或两端已验收。

NPC LLM 使用独立的默认 **5 次失败 / 60 秒恢复窗口**熔断机制，不采用 Boss 的“本场保持 BT”规则。正式对照、故障与时延统计见 [UE 评估方案](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/08_RL_Research/03_EvaluationProtocol.md)；本仓实施缺口见[未决清单](../docs/planning/todo.md)，模型视图见 [UML 入口](../docs/design/uml/README.md)。
