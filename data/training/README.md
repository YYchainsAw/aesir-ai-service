# 人格训练语料（B1 路线）

NPC 人格训练采用**语料 + few-shot 优先**（B1）路线：先把高质量对话语料攒起来，
直接注入 LLM prompt（`data/personas/aesir/companion.alice/examples.yaml` 的 `dialogue_examples`，
当前 60+ 组）；语料攒到 500+ 组后再评估上微调（B2 火山方舟 / B3 本地 LoRA）。

## 目录约定

```
data/training/
  README.md               本说明
  corpus_raw/             LLM 批量生成的候选语料（未过滤，允许粗糙）
  corpus_checked/         人工过滤后的合格语料（入库候选）
  filter_checklist.md     人工过滤红线清单
```

## 语料格式

每条语料即一个 few-shot 样例（与 `dialogue_examples` 同构）：

```yaml
- category: smalltalk        # 见下方分类表
  player: "玩家输入"
  reply_text: "艾莉的回复"
  emotion_id: emotion.bright # 必须在角色 YAML 的三个白名单内
  gesture_id: gesture.small_wave
  facial_expression_id: face.bright_smile
```

## 分类表

`greeting / farewell / smalltalk / question / lore_question / praised / cared_for /
comfort / tactical_redirect / battle_chat / memory_recall / promise / boundary / gift`

新增分类需同步更新 `dialogue_examples` 与 `fallback_dialogue_responses` 的类别注释。

## 人工过滤红线（不合格直接丢弃）

1. 出戏术语：回复中出现「指令」「接口」「频道」「协议」「系统」「模型」等元语言。
2. 战斗请求失格：非战斗状态下玩家请求战斗，回复未以角色口吻婉拒（详见 filter_checklist.md）。
3. 表现 ID 越界：emotion/gesture/face 不在角色 YAML 白名单内。
4. 人设崩坏：情感勒索、贬低玩家、占有控制式表达、宣称不存在的记忆或能力。
5. 长度超标：回复超过三句或明显不适合字幕/气泡显示。

## 流程

1. 批量生成：用 DeepSeek 等按分类批量生成候选 → 存 `corpus_raw/<日期>_<分类>.yaml`。
2. 人工过滤：逐条对照红线 → 合格移入 `corpus_checked/`（可按 `filter_checklist.md` 打勾）。
3. 入库：定期把 `corpus_checked` 精选进 `data/personas/aesir/companion.alice/examples.yaml` 的 `dialogue_examples`
   （注意 prompt 全量注入，条数过多时需评估 token 预算）。
4. 评测：`start.bat chat` 终端对话人工过一遍；语料 500+ 后评估 B2 微调。
