# 第五步：Boss本地发行与冻结评估实施计划

> 2026-10-22，`boss-release-plan-v1`。用户授权继续第五步；第四步PR #90已合入 `main@b641b2f`，本步分支 `feature/boss-local-release`。本页维护目标、依赖与验收定义，实际结果另记[验证记录](../logs/verification-records.md)。

主线以[六步方案](local-boss-cloud-companion-roadmap.md)为准，对应AI-DEP-01/02/05/11/14/15及部署指南的模型身份/本地发行要求。工作状态由[DEP5里程碑](https://github.com/YYchainsAw/aesir-ai-service/milestone/9)与[#91](https://github.com/YYchainsAw/aesir-ai-service/issues/91)～[#94](https://github.com/YYchainsAw/aesir-ai-service/issues/94)维护；模型背景见[RL说明](../../rl/README.md)，不复制平行任务勾选。

## 1. 目标与边界

| 目标 | 本步交付 |
| --- | --- |
| 可信冻结身份 | 固定当前候选及原selection/training材料的SHA；加载前验证身份/Schema/特征与动作，加载后核对模型空间；不因改文件名冒充原候选 |
| 纯本地CPU推理 | 保持独立localhost HTTP、Schema4/26维/9动作；有限数输入、mask/输出复核、合法暂时无动作；不依赖云端NPC或供应商key |
| Windows原生发行 | 单独构建自带Python/CPU依赖的运行目录、EXE、模型、材料及校验清单；完整目录随游戏分发，不要求玩家临时pip或下载模型 |
| 可复核独立评估 | 无重训加载冻结候选，与模拟器Rule在相同画像/持出seed逐局比较；原始JSONL、summary和实验manifest保留模型/源码/依赖身份 |
| 发行验证与交接 | 正常启动/校验/动作、锁态、缺失或篡改文件、端口占用、退出/重启分别留证；游戏实际表现与UE回退另行验收 |

本轮在服务器开发源与适用核心测试，在本机Windows原生构建/运行Boss包。不在云端NPC环境安装Torch或执行训练；不替换候选，也不把Python模拟器Rule称为UE BT。用户此前将UE连接测试后置，该边界继续适用；本地UE工作区已有大量未提交修改，本轮不修改其C++/资产或执行游戏连接测试。

UE仍需完成进程启动/就绪/退出管理、预期模型身份校验、KI-01连续非法动作计数和KI-06终局停止/晚到回包失效，再验证断网战斗与同条件BT/PPO。服务EXE独立通过不能关闭第五步游戏侧整体验收。

## 2. 冻结候选与环境决策

| 项目 | 固定基线 |
| --- | --- |
| 模型 | `boss_policy_schema_v4_sim005.zip`，源seed1，原训练候选不变 |
| 模型SHA256 | `dd79ceca0e0f079634364754d1959212b0cdb357439ab9ef8e36d3ba4ed64add` |
| 观察/动作 | Schema4，26项有序FEATURE_NAMES，9项BossAction整数映射；变化须另升级schema并重新评估 |
| 模拟器/奖励 | `boss-sim-005` / `boss-reward-003` |
| 选模材料 | 同stem `.selection.json`，SHA256 `06ac233ea7998017c22cdf7aef9923607b62cb20174afe6223750c7312acfd33` |
| 原训练材料 | 同stem `.training.manifest.json`，SHA256 `9698eacaadad72b31f34b438719beb22467e6899fc2f337103dcc263bc6b6cff` |
| Boss原生运行环境 | 本机已有且与原训练一致的Python3.11.9；Torch2.7.1+cpu、SB3/SB3-Contrib2.7.1、Gymnasium1.2.3；实际完整依赖随构建清单记录 |
| NPC服务器 | 继续原Python3.12.15/独立venv；Boss冻结包采用自己的嵌入运行时，不改变NPC项目解释器要求 |

模型与两份sidecar按原字节复制，换行也影响SHA。原件来自本机既有部署目录，校验后复制到服务器忽略的models目录供材料核对；模型不混入Git源码，随Windows受控交付包提供。可信descriptor在版本库维护，先验证ZIP哈希再让Torch反序列化；可修改的sidecar不能自行宣称可信。此处是受信游戏发行内的固定候选完整性，不声称已经实现联网签名更新。

原生构建采用PyInstaller onedir，构建工具单独venv，现有RL依赖只读复用。包记录真实Windows架构、Python/依赖/源码与逐文件SHA；不包含app、.env、云端token或训练输出。首版保持人工固定目录切换；自动下载、热替换、ONNX/NNE和代码签名更新不在本次实现。

## 3. 工作包

| 工作包 | 交付与验收重点 |
| --- | --- |
| DEP5-01 | 可信descriptor与先验SHA/材料校验，模型空间、有限数及mask输出校验，回环CLI及可核对health身份 |
| DEP5-02 | Windows构建工具、独立运行入口、文件树校验、版本/依赖清单、第三方许可和禁止覆盖输出 |
| DEP5-03 | rule/frozen/compare评估入口、持出seed策略、同画像逐局原始结果、summary/manifest；保留旧训练调用兼容 |
| DEP5-04 | 真模型Windows EXE与发行故障验证、服务器适用核心回归、文档及UE后续操作/阻断清单 |

## 4. 独立评估与结果含义

当前900局、base_seed50000的材料属于选模，不能再次作独立测试。本轮固定持出base_seed200000开始的种子，每画像局数显式记录；PPO与Rule使用相同画像/seed配对。拒绝与选模范围重叠，不宣称训练随机reset可能取到的所有种子数学上均不相交。独立评估结果不回流选模或重新训练；不满意也如实保留当前候选结果。

逐局记录画像、seed、胜负/超时、奖励、伤害、决策数、动作分布和拒绝/锁态等既有指标；汇总保留画像层与置信区间，实验清单保留来源与版本。输出目录必须新建，避免覆盖已有实验；失败不得留下被误认为完整成功的报告。论文正式统计、UE真实BT/PPO对照与延迟仍以其评估协议单独验收。

## 5. 验收定义

| 编号 | 通过条件 |
| --- | --- |
| AT-BOSS-01 | 正确候选及原材料通过；缺失、篡改、错Schema/有序特征/动作/模拟器版本在加载前拒绝，模型空间不符加载后拒绝 |
| AT-BOSS-02 | 26维有限[0,1]输入；预测必须为可用整数动作；全锁态合法无动作；非法输出不通过int截断后放行 |
| AT-BOSS-03 | Windows原生目录含EXE/依赖/模型/材料/逐文件清单；移到含空格新路径、清理Python环境变量后可运行，未依赖源码工作区或运行时pip |
| AT-BOSS-04 | 离线本地verify/selftest/health/decide可复现；错误模型、端口占用、退出与重启有明确结果，CLI拒绝公网监听 |
| AT-BOSS-05 | frozen独立评估不训练；与Rule同画像/持出seed，逐局数量及summary一致，模型/源码/依赖身份可核对，选模结果不冒充新实验 |
| AT-BOSS-06 | 无模型时原NPC适用核心仍通过，NPC不导入RL；模型/运行包不夹带.env或API key；本轮有实际原生包与原始验证记录 |
| AT-BOSS-UE | UE修复已知计数/终局问题、校验预期身份并管理本地进程；断网Boss/BT回退、迟到/重复响应、真实执行与同条件对照有游戏证据；本轮继续待验 |

构建与实际运行步骤由后续Boss交付指南维护，数值结果、路径、SHA和未验范围只在验证记录登记。本计划本身不作为通过证据。

参考：[PyInstaller官方用法](https://pyinstaller.org/en/stable/usage.html)；原生依赖与Windows兼容性以本轮构建/运行环境实测为准，不用Linux导出充当Windows包。
