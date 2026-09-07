# Aesir AI Service — LLM 联调指南

本文说明如何把命令解析从规则后端（`rule`）切换到 **LLM 后端（OpenAI 兼容，默认 DeepSeek）**，并做真实联调。联调通过后，任意自然语言指令都能解析为 UE 可校验的 `TacticalOrder`。

> 与规则后端的关键区别：规则只认固定 5 句；LLM 后端能接住任意说法，识别不了或出错时**自动回退到规则解析器**，UE 永不收到非法 order。

---

## 0. 前置条件

- 已安装服务依赖：`.\.venv\Scripts\python -m pip install -r requirements.txt`
- 已有一个有效的 DeepSeek API key（在 [platform.deepseek.com](https://platform.deepseek.com) 申请）

---

## 1. 配置 `.env`

项目根目录新建 `.env`（该文件已被 `.gitignore` 忽略，**不会进版本库**）：

```ini
# 命令解析后端切到 LLM
AESIR_PARSER_BACKEND=llm

# DeepSeek（OpenAI 兼容）。换 Qwen/Ark 只需改下面两项
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=30

# 你的真实 key（必填）
LLM_API_KEY=sk-xxxxxx
```

> 初次可先 `copy .env.example .env`，再按上面补 `LLM_API_KEY`。

---

## 2. 快速联调脚本

用一行 Python 验证（终端中文显示若有乱码是编码问题，数据本身正确）：

```python
# 文件：scripts/llm_smoke.py 或直接 python -c
from app.services.command_parser import parse_command

for text in [
    "艾莉，等 Boss 血量低于一半就开大",   # 规则里没有的新指令
    "艾莉，敌人超过三个就先撤",           # 规则里没有的新指令
    "艾莉，撤退并优先保命",               # 已知指令
]:
    r = parse_command(text)
    print(text, "=>", r.recognized, "|", r.order.intent if r.order else r.message)
```

---

## 3. 通过 HTTP 接口联调

先起服务（保持窗口运行）：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

用 `Invoke-RestMethod` 调（PowerShell 里 `curl` 是别名，勿用）。正式接口为契约 v0.1 的 `/v1/commands/parse`（携带能力目录；目录缺省时新指令可能因 ID 越界被拒）：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/commands/parse `
  -ContentType "application/json" `
  -Body '{"protocol_version":"0.1","request_id":"1fad2e69-4a2d-4308-ad4f-2f8abb338b89","text":"艾莉，等 Boss 血量低于一半就开大","context":{"catalog_revision":"dev-001","locale":"zh-CN","agents":[{"id":"companion.alice","ability_ids":["ability.alice.explosion","ability.alice.basic_attack"]}],"target_selectors":["encounter.primary_hostile","party.player"],"state_tags":["state.stunned","state.phase_two"]}}'
```

> 新指令能返回合法 `order`（如 `conditional_cast`）即联调通过。
>
> 遗留别名 `POST /parse-command` 只传 `text`，服务端回填默认能力目录，也可用于快速自测：
>
> ```powershell
> Invoke-RestMethod -Method Post http://127.0.0.1:8000/parse-command `
>   -ContentType "application/json" `
>   -Body '{"text":"艾莉，等 Boss 血量低于一半就开大"}'
> ```

---

## 4. 预期结果（本次实测）

| 输入 | intent | 说明 |
| --- | --- | --- |
| 艾莉，等 Boss 血量低于一半就开大 | `conditional_cast` | 规则认不出，LLM 成功解析 |
| 艾莉，敌人超过三个就先撤 | `retreat` | 新指令成功 |
| 艾莉，撤退并优先保命 | `retreat` | 已知指令 |

延迟约 0.6–1.4s/次（取决于网络与模型）。

---

## 5. 回退与安全行为

- **LLM 输出不合法 / 网络失败 / 未配置 key** → facade 捕获后回退到规则解析器，指令不会被丢弃。
- `recognized=false`（LLM 也不确定）→ 规则解析器最终兜底。
- 所有输出经 `TacticalOrder` 白名单校验（`TypeAdapter`），越界字段一律拒绝，UE 校验不会崩。

---

## 6. 常见问题

- **`curl : 无法绑定参数 Headers`**：PowerShell 里 `curl` 是 `Invoke-WebRequest`，请改用 `Invoke-RestMethod` 或 `curl.exe`。
- **服务连不上**：确认先启动了 `uvicorn`；`/parse-command` 只接受 POST，浏览器直接访问会 405。
- **一直 `recognized=false`**：检查 `.env` 里 `AESIR_PARSER_BACKEND=llm` 且 `LLM_API_KEY` 已填；服务需重启（`--reload` 会自动）。
- **换厂商**：改 `LLM_BASE_URL` / `LLM_MODEL` 即可，代码无需变动。

---

## 7. 密钥安全

- `LLM_API_KEY` 只写进被 `.gitignore` 忽略的 `.env`，**绝不提交到仓库、不写进文档/测试**。
- 若密钥曾在不可信环境（录屏/转发）出现过，建议在 DeepSeek 控制台轮换一次。