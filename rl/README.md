# Boss 强化学习

`rl/boss/` 训练、评估和部署 Boss 高层动作策略，使用 MaskablePPO；NPC 服务 `app/` 不导入它。模拟器规则基线 `RuleBossPolicy` 与 UE 的 `BT_AesirBoss` 是不同实现，模拟器成绩不能直接代表 UE 实战。

部署目标见[15 项能力分工](../docs/planning/ai-capability-placement.md)（`placement-v1`，AI-DEP-01/02/14/15）及[六步方案第五步](../docs/planning/local-boss-cloud-companion-roadmap.md)：源码可在服务器开发，冻结推理发行到玩家电脑；训练/正式评估与在线 NPC 服务隔离。本页既有模型身份/接口说明不表示 Windows 包、自动模型更新、独立 PPO 评估或 UE 验收已经完成。

## 先清点交付材料

```powershell
.\.venv\Scripts\python.exe -m scripts.rl.boss.inventory
```

该命令只读取文件、SHA-256、ZIP 中有限大小的 JSON 元数据与已安装分发版本，不导入训练依赖、不反序列化模型、不训练、不启动推理服务。输出 `data/runtime/boss-delivery/inventory.json`；`materials_state=blocked` 是材料/依赖缺失，`present_but_not_runtime_verified` 也不是运行通过。

默认清点 `models/rl`，其中当前候选目录为 `boss/deployment`。若模型库在其他已知位置，可显式传 `--model-root <模型库根目录>`，候选仍按其 `boss/deployment` 子目录定位；不自动搜索磁盘、不移动或改名模型。

2026-11-11 本机清点：当前候选 ZIP、selection 和 training manifest 缺失；`models/rl` 中的 6 个旧 ZIP 的 JSON 元数据声明 17 维观测、7 动作，与当前 26/9 契约不同，不能因文件名相近或同为 seed1 就替代。正确模型的保管位置仍需交付者提供。元数据本身不证明真实张量或推理行为兼容。

独立 Boss HTTP 推理所需分发版本见 [requirements-boss-inference.txt](../requirements-boss-inference.txt)；它不包含 NPC、ASR、SQL/Redis 或 TensorBoard。训练继续使用 `requirements-rl.txt`。依赖安装、CPU 构建选择及 Windows 实机验证后置，不因本次清点修改当前 venv。

## 运行入口

以下命令在仓库根目录执行。安装 RL 依赖后，可运行规则基线评估；`--episodes` 是每种玩家画像的局数，三种画像各 20 局即总计 60 局。

```powershell
.\.venv\Scripts\python -m pip install -r requirements-rl.txt
.\.venv\Scripts\python scripts\rl\boss\eval.py --episodes 20 --seed 0 --json
```

`eval.py` **只评估规则基线**，没有加载冻结 PPO 的参数。冻结候选到位后，使用无需重训的独立入口：

```powershell
.\.venv\Scripts\python.exe -m scripts.rl.boss.eval_frozen `
  --episodes 100 --seed 200000 `
  --output data/runtime/boss-delivery/frozen-200000
```

可传 `--model <ZIP路径>`；评估与 HTTP 现在共用 `rl/boss/model_loader.py`，在同一内存快照上核对冻结 SHA，核对同目录 `.training.manifest.json` 的 Schema/字段/动作/修订，再检查实际观测及动作空间。训练、评估与 HTTP 共用确定性掩码预测适配器。此命令不训练、不启动 HTTP，也不导入训练入口；只对可信来源的模型执行反序列化。

每种玩家画像各运行指定局数，规则基线和 PPO 共用 `seed + 局序号`。默认每个策略 300 局，合计 600 局；拒绝与已记录选模区间 `[50000, 50300)` 重叠。该保护只证明避开这份选模记录，**尚不证明与全部训练/历史调参数据独立**，后续须结合训练材料核定正式测试集。

输出目录必须是新目录，以免覆盖证据。`episodes.jsonl` 保留两策略的逐局种子、画像、结果、奖励、伤害和动作统计；两策略全部完成后才生成 `summary.json`，包含分画像汇总、模型及源码/原始输出 SHA、依赖版本和可复评参数 `reproduce_argv`。若中途失败，可能保留部分逐局数据，但没有完成汇总。模拟器结果不能当作 UE 的 BT 对照成绩。

2026-11-12：入口及失败保护已通过自动化测试；本机冻结模型和 `sb3-contrib` 仍缺失，真实 PPO 评估未运行，详见[验证记录](../docs/logs/verification-records.md#boss-frozen-eval-20261112)。

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

`selection_evaluation` 使用 `base_seed=50000`，aggressive、defensive、evasive 各 300 局，共 900 局；Boss 胜率为 0.8433，分画像 0.553 / 0.977 / 1.0。**这是选模汇总，不能再次充当独立测试集或 UE 成绩。** 未找到对应 900 局逐局原始输出；训练曲线、原选模复现材料和真实独立测试数据仍需整理。2026-09-10 的“3 种子、2/3 达标、眩晕窗口施爆裂”属于旧队友实验，不能作为此 Boss 模型的上线依据，详见[验证记录](../docs/logs/verification-records.md)。

`models/` 被 Git 忽略，新克隆没有默认 ZIP。当前没有仓库内可核验的公开下载入口；交付者需提供以上 ZIP、selection、训练 manifest 及依赖记录，并记录实际保管或获取位置。不要用同名空文件或新训练结果替代原候选。获取后在仓库根核对：

```powershell
Get-FileHash -LiteralPath models/rl/boss/deployment/boss_policy_schema_v4_sim005.zip -Algorithm SHA256
```

## 本地交付与版本发布

2026-10-21用户采纳Boss冻结推理在玩家本机运行：初始程序、依赖、模型和材料随游戏交付，服务器提供可信版本清单和可选更新，训练与在线NPC服务分开调度。首期复用下述独立HTTP服务；ONNX/NNE为后续候选，当前无自动打包/下载/进程管理实现。清单需包含SHA、Schema/动作和游戏/推理运行时兼容性；签名验证、菜单阶段切换、失败回滚及断网行为只在[UE部署说明](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/02_Design_Doc/TDD/06_Deployment.md)维护，服务端要求见[部署指南](../docs/guides/deployment.md)。正式研究固定模型并关闭自动更新。

## 冻结策略 HTTP 服务

独立推理接口已经存在，默认端口 `8012`，与 NPC 服务 `8011` 分开。模型到位且依赖齐全后启动：

```powershell
.\.venv\Scripts\python scripts\rl\boss\serve.py
```

可用 `--model <实际ZIP路径>` 指定文件，优先于 `AESIR_BOSS_POLICY_MODEL`；默认查找 ZIP 同目录下的 `<ZIP文件名去掉.zip>.training.manifest.json`，也可用 `--manifest <训练manifest路径>` 指定。`GET /health` 返回服务信息；`POST /v1/boss/policy/decide` 接受 Schema 4 观察，返回一个高层动作或 `actionable=false` 的合法暂时无动作。GAS 动作可用性和真实启动、命中、伤害仍由 UE 复核。

2026-11-12 起，服务启动必须通过以下校验；缺文件、依赖缺失或任何不一致都会使 lifespan 失败并退出，不会启动可接收推理的服务：

- ZIP SHA 必须匹配代码中登记的上述冻结 SHA，不提供忽略校验或任意 SHA 的启动参数。校验和反序列化使用同一份内存快照，避免加载另一次读取的文件内容。
- 训练 manifest 必须是至多 1 MiB 的 JSON 对象，`schema_version` 为整数 4，`feature_names` 与当前 26 字段顺序完全一致，`actions` 与 9 个枚举名称及整数 ID 完全一致，`simulation_revision` / `reward_revision` 为 `boss-sim-005` / `boss-reward-003`。字段格式沿用训练入口生成的 manifest；不是从 ZIP 文件名推断 Schema。
- CPU 加载成功后，模型观测空间必须是形状 `(26,)`、float32、范围 `[0,1]` 的 Box，动作空间必须是从 0 开始的 Discrete(9)。全部通过才发布模型为 ready；合法暂时无动作也不能绕过加载校验。

`model_id` 使用登记的候选身份，不随文件改名。健康接口只有已加载且校验通过才返回 HTTP 200 / `status=ok`；未就绪返回 HTTP 503。新增 `ready` 和 `model_validation`：后者包含 `state`（`not_checked/checking/passed/failed`）、稳定 `error_code`、预期值 `expected` 及实测值 `actual`。`actual.sha256` 是加载快照的 SHA，Schema/模拟器/奖励版本来自已核对的 manifest，观测形状和动作数量来自加载后的模型；未检查的值保留 null。顶层 Schema、观测维度和模拟器版本仍表示服务契约。启动失败时进程已经退出，须查看启动错误码，不能再通过该进程的 HTTP 健康接口查询。

该门禁不读取 selection 的评分，也未实现发行清单签名；manifest SHA 作为本次读取证据报告。当前真实冻结 ZIP/manifest 仍缺失，成功路径仅用合成文件和模型加载替身验证，不代表真实模型启动或 UE 已验收。详见[验证记录](../docs/logs/verification-records.md#boss-runtime-gate-20261112)。

UE 已确认目标为连续 3 次通信、协议或非法动作错误后切 BT，保持到本场遭遇结束；仅完整合法响应清零，合法暂时无动作不算故障。2026-11-09 UE 提交 `06f2415` 已修复动作字段校验前清零的源码顺序；连续非法动作注入、BT 接管及结算仍待运行验证。模型身份完整核验、终局取消与同遭遇策略段关联也需联调，参见 [UE RL 契约](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/08_RL_Research/BossRL_Contract.md)、[已知问题](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/06_Test_Doc/KnownIssues.md)。这些 UE 目标不表示 Python 或两端已验收。

NPC LLM 使用独立的默认 **5 次失败 / 60 秒恢复窗口**熔断机制，不采用 Boss 的“本场保持 BT”规则。正式对照、故障与时延统计见 [UE 评估方案](https://github.com/YYchainsAw/AesirWarden/blob/main/Docs/08_RL_Research/03_EvaluationProtocol.md)；本仓实施缺口见[未决清单](../docs/planning/todo.md)，模型视图见 [UML 入口](../docs/design/uml/README.md)。
