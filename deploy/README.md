# NPC 服务发布准备

本目录提供可审查的 Linux/systemd/Nginx 模板，尚未安装或运行。真实 LLM 配置、服务器 OS/权限、域名证书、数据库、Redis 和目标机器 ASR 性能均待部署阶段确认。沿用[部署需求](../docs/guides/deployment.md)，不另建任务状态看板。

## 文件与路径

| 文件 | 作用 |
| --- | --- |
| `aesir-ai.service` | 单 worker、环回 8011、启动前配置门禁、进程守护 |
| `service.env.example` | Bearer/SQL/Redis 与 CPU/int8 ASR 配置；实际凭据填在服务器私有文件 |
| `nginx-aesir.conf` | HTTPS 反向代理、上传限制、长请求预算，保留应用 JSON 错误 |

模板采用以下路径，可由部署者整体调整，不代表目标服务器已有这些目录：

| 路径 | 归属与内容 |
| --- | --- |
| `/opt/aesir-ai/releases/<release-id>/` | 固定提交的源码与该版本独立 venv，服务用户只读 |
| `/opt/aesir-ai/current` | 指向当前发布目录的符号链接 |
| `/opt/aesir-ai/models/whisper-small` | 预置完整模型目录，服务用户可读，首次启动不联网下载 |
| `/etc/aesir-ai/service.env` | 实际环境配置，建议 root 所有、0600，由 systemd 读取 |
| `/etc/aesir-ai/database.url` | 数据库连接串，aesir 服务用户必须可读；目录 0750、文件 0640 或更严格 |
| `/var/lib/aesir-ai/` | aesir 用户可写的运行数据与缓存，目录 0700 |
| `/var/backups/aesir-ai/` | 应用目录外的私有备份，备份执行账号独立持有，目录 0700 |

应用目录不作为静态站点。部署只复制固定提交的源码，不复制开发 `.env`、测试音频、运行日志或真实开发记忆。

## 部署者的执行顺序

1. 确认 Linux 发行版、Python 3.12+、可用 CPU/内存、磁盘、域名及证书；准备 aesir 系统用户和上述目录。若已有宝塔进程管理器，应选择一种守护方式，避免重复启动。
2. 从固定提交创建独立发布副本。安装项目、核心依赖及 `requirements-ml.txt` 的语音依赖，记录实际锁定版本；不安装 Boss 训练依赖作为 NPC 启动条件。
3. 预置 Whisper 模型并核对模型文件/来源/版本。模板设 `HF_HUB_OFFLINE=1`，因此模型缺失会失败，不会在演示时自动下载。`ProtectHome=true` 下不能引用 `/root/.cache` 或个人 home 中的模型。
4. 将模板复制到私有 `service.env` 后填写可用通用 LLM 或自部署 LLM 的地址、模型和凭据。当前无有效 Coding Plan 订阅，不填写假凭据来绕过门禁，也不自动改动计费路径。
5. 准备受支持的 MySQL 专用库、最小权限运行账号和 Redis；初始化/迁移使用独立管理配置，按[持久化指南](../docs/guides/persistent-development.md)操作。该 systemd 服务不会自动建表、迁移或发放玩家凭据。
6. 在与 systemd 相同的环境下运行只读门禁；只有填写配置不等于供应商、SQL 或 Redis 连通性已验证。
7. 安装 unit 后在目标服务器检查 `systemd-analyze verify`；替换 Nginx 域名/证书并执行 `nginx -t`。这些命令本轮未执行。确认配置通过后再启动与开放网络。
8. 进入后置验收：健康、Bearer/存档授权、真实文本/指令/语音、服务重启、备份恢复、回滚、UE 录音与打包运行。每次记录发布 SHA、模型快照、设备及原始证据。

配置门禁命令（需由部署者先加载实际私有环境）：

```bash
/opt/aesir-ai/current/.venv/bin/python -m scripts.release_preflight --mode production --json
```

预检不连接模型、数据库或 Redis；实际 SQL 结构在应用启动时另检查。空模板应阻止发布。Web 代理 130 秒超时不代表应用预算增加：请求仍受客户端 timing 与服务端 120 秒上限约束，语音也要计入 ASR 和后续生成耗时。

## 运行与回滚记录

systemd 标准输出进入 journal，查看时使用 `journalctl -u aesir-ai`。`/var/lib/aesir-ai/signals` 保存业务信号/回执，不要按普通访问日志随意清空；保留和清理沿用项目数据规则。

发布记录至少包含：代码 SHA、发布路径、语音模型来源/快照/哈希、依赖版本、配置版本（不含密钥）、数据库结构版本、备份位置、原 current 目标和验收证据。

回滚先判断数据库结构是否兼容旧代码。兼容时可在维护窗口将 current 指回已验版本并重启；有结构/数据迁移时先按备份恢复流程审查，不能仅回退代码。旧实例的 binding、epoch 与在途请求不得在 UE 复用，必须重新 context/bind。
