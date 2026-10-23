# Boss本地发行与冻结评估指南

2026-10-23，适用于 `feature/boss-local-release`。范围与验收见[第五步计划](../planning/step-05-boss-local-release-plan.md)，模型来源见[RL说明](../../rl/README.md)，实际包、测试与实验结果见[验证记录](../logs/verification-records.md#boss-release-20261023)。本页维护可执行步骤，不把本地服务通过写成UE实战通过。

## 1. 发行内容与适用环境

Boss包运行在玩家Windows设备，通过回环HTTP提供Schema4的高层动作建议；NPC服务继续在服务器运行。当前候选固定为schema4/sim005/reward003/seed1，`rl/boss/deployment.json` 固定ZIP及两份原材料的SHA。加载前验证字节和语义，随后检查实际26维Box、9动作Discrete空间；改文件名或sidecar自报SHA不能替换候选。

本轮Windows运行时为64位Python3.11.9，CPU Torch2.7.1、SB3/SB3-Contrib2.7.1、Gymnasium1.2.3及实际固定依赖；它与原训练环境一致，随独立EXE目录交付。NPC项目继续Python3.12+，不会因Boss包调整服务器解释器或安装RL训练依赖。

交付必须保留完整目录：EXE、`_internal`运行依赖、模型/selection/training材料、`release-manifest.json`及第三方许可。不能只拷贝EXE，也不能从源码运行成功推断玩家设备无需Python已通过。

## 2. 原生Windows构建

构建在Windows原生环境进行。构建工具使用独立venv，按 `packaging/boss/requirements-build.txt` 安装PyInstaller；已有可信RL环境可通过只读site-packages复用，不向其安装或升级包。构建器不联网取模型或依赖，不包含NPC的app、.env或供应商密钥。

在项目根使用已配置的独立构建解释器：

```powershell
& <构建环境python.exe> -m scripts.rl.boss.build_release `
  --plan --model-dir <原模型和两份sidecar所在目录> `
  --output <全新发行目录> --runtime-site-packages <已验证RL环境的Lib/site-packages> `
  --source-commit <实际源码完整40位提交>
```

预检通过后移除 `--plan` 执行原生构建。输出目录必须不存在，不覆盖已验证发行。路径含空格时使用PowerShell引号；命令由参数数组传给PyInstaller。清单记录调用者声明的提交及实际源文件SHA，发布者仍需逐项核对源SHA与该提交一致，不能仅相信传入的版本字符串。

构建后运行 `--verify` 与 `--self-test`，再移动到独立路径验证启动；发生缺模块或DLL时保留构建日志并修复收集规则，不把旧源码环境的成功结果代替EXE。PyInstaller onedir与依赖收集参数参见[官方用法](https://pyinstaller.org/en/stable/usage.html)。

## 3. 玩家设备上的独立入口

以下命令在发行目录执行，无需pip、云端API key或源码工作区：

```powershell
.\aesir-boss-policy.exe --verify
.\aesir-boss-policy.exe --self-test
.\aesir-boss-policy.exe --host 127.0.0.1 --port 8012
```

`--verify`只核对发行文件树、模型字节及固定材料，不反序列化模型；`--self-test`在验证后加载CPU模型，检查锁态及九个单动作mask并复验确定性。默认服务只允许127.0.0.1；源码serve仅允许literal loopback。冻结包拒绝 `AESIR_BOSS_POLICY_MODEL` 覆盖，不通过外部环境偷偷切换模型。

`GET /health`应显示loaded、model_id、model_sha256、release_id、Schema/特征数、sim/reward与材料来源。`POST /v1/boss/policy/decide`继续protocol1.0/Schema4的原信封，保留request_id/sequence；新增内容身份供UE后续核对，不代表UE当前已经核验。

观察必须为26个有限[0,1]值。预测必须是mask允许的整数动作；全锁态合法返回 `actionable=false, reason=state_locked`，不算通信失败。坏输入422，模型/预测不可用503，不刷新游戏动作有效期。GAS仍在实际执行时核对目标、距离、冷却、资源与动作锁。

SHA文件清单用于发现损坏/变化，不是发布签名；应从受信游戏发行渠道获得完整包及预期清单。当前没有联网更新、签名清单下载或热替换。人工换版在菜单/无战斗阶段先停止旧进程，使用另一已核对完整目录，启动验证后再由UE接入；失败保留原目录或走本地BT，不删除唯一可用版本。

## 4. 无重训冻结评估

使用有完整RL依赖的独立解释器，从源码根运行：

```powershell
& <RL环境python.exe> -m scripts.rl.boss.eval `
  --policy compare --model <固定ZIP路径> `
  --episodes 300 --seed 200000 --out <全新实验目录>
```

每画像每策略300局，三画像、两策略总1800条记录。`--policy frozen`只评估冻结PPO；默认rule保留既有规则评估入口。frozen/compare强制新输出目录并排除选模seed50000～50299。PPO与Rule从相同画像/seed开始，但不同动作可能改变随机数消耗；原训练reset覆盖广域，因此不宣称与全部训练种子数学上无交集。

输出 `episodes.jsonl`、`summary.json`、`manifest.json`及原selection/training材料副本。manifest记录模型/材料SHA、源文件SHA、模拟器/奖励/画像配置、依赖和种子协议；只有完整manifest与工件hash核对通过才当作完整实验。中途失败可能留有部分JSONL，没有完成manifest不能冒充通过，不覆盖该目录重跑。

Rule是Python模拟器基线，和UE的 `BT_AesirBoss` 不同。新结果不覆盖900局选模材料，不自动换模型、重训或改为新候选；论文/正式报告必须同时说明样本、环境及UE待验边界。

## 5. UE接入与第五步待验

| 责任 | 后续实际检查 |
| --- | --- |
| 本地进程生命周期 | UE负责菜单阶段启动、就绪、端口占用识别、退出及残留进程回收；本轮独立EXE退出成功不代表UE已管理 |
| 模型身份 | 按预期release_id/model_sha256核health与响应，拒绝未知候选；当前客户端只要求model_id非空，尚未完成强身份核验 |
| 连续错误切BT | 修复KI-01：完整合法动作/合法无动作通过校验后才清零；连续三次通信/协议/非法动作错误切BT并保持本场 |
| 终局与晚到响应 | 修复KI-06：结束/退出时停止推理、取消在途请求，拒绝旧局回包；现有Stop/request对象身份提供部分保护，不能省略终局接入 |
| 整体实战 | 断开公网后Boss仍运行；缺/错模型、未就绪、进程异常、退出、回退及同条件BT/PPO必须在游戏记录真实证据 |

本轮用户继续将UE连接测试后置，既有UE工作区不改。服务侧发行与评估材料完成后仍保留以上门槛，不能提前关闭游戏整体验收。既有KI和实战协议由UE仓 `Docs/06_Test_Doc/02_KnownIssues.md` 与 `Docs/08_RL_Research/01_BossRLContract.md` / `03_EvaluationProtocol.md`维护。
