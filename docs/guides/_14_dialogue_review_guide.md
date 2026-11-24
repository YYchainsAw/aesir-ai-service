# 自然交互采集与人工评测

本流程采集真实参与者的正常交互，不生成自然对话或人工评分。当前历史日志经来源筛选可导出 0 条，并不满足训练门槛。自然来源标记仅说明服务采集配置，不能独立证明参与者身份、同意或标注正确。

## 采集

使用独立本机测试实例和参与者各自的身份/存档，不用同一固定开发身份只更换 session 来冒充多个玩家。沿用[作用域接入](./_04_scoped_development_guide.md)与[存储模式](./_06_persistence_guide.md)，不在本轮开启目标服务器或训练。

参与者知悉会保存完整对话并同意评测后，在独立进程设置：

```powershell
$env:AESIR_DIALOGUE_DATA_ORIGIN='natural'
$env:AESIR_DIALOGUE_DATA_RUN_ID='pilot-a'
$env:AESIR_DIALOGUE_SIGNAL_TEXT_MODE='full'
$env:AESIR_DIALOGUE_SIGNALS_DIR='data/runtime/natural-pilot/signals'
```

让参与者正常聊天、回忆、纠正、拒绝、切换话题；不把种子复述、故障注入、模型互聊计作自然样本。测试另用 seed/fault/evaluation 实例；结束原文采集后恢复 metadata。默认日志模式仍是 metadata，没有因导出工具自动打开原文收集。

## 导出与评分

导出文件含私人原文，只放在忽略目录或其他受控本地目录，不提交 Git、不上传聊天：

```powershell
.\.venv\Scripts\python.exe -B -m scripts.dialogue_review export --root data/runtime/natural-pilot/signals --output data/runtime/review/reference.json
Copy-Item data/runtime/review/reference.json data/runtime/review/reviewed.json
```

仅导出服务端标记的 natural/full、身份与 logical request 齐全、完整 llm 轮次；排除已知种子和元数据记录，重复逻辑请求不重复计数。输出存在时拒绝覆盖，保护已做标注。

人工修改 reviewed.json 的 reviewer（本地别名）、notes 和四个 ratings：memory_accuracy、naturalness、refusal_quality、execution_honesty。允许 pass/fail/unknown/not_applicable，未评分保持 null；需要证据但看不到时填 unknown，不猜 pass。除 reviewer/ratings/notes 外保留原内容及 sample_id，不把 NPC 自称执行当作 GAS/回执证据。

```powershell
.\.venv\Scripts\python.exe -B -m scripts.dialogue_review summary --reference data/runtime/review/reference.json --reviewed data/runtime/review/reviewed.json
```

汇总仅打印人数/数量与评分分布，不打印原文、身份或审阅者别名。未知/未评分不算通过；未知 ID、重复样本、原文与参考不一致、无署名评分被拒绝。参考文件应保留为原始只读副本；哈希与比对不是可信身份认证或不可伪造签名。标注者和参考文件仍需项目负责人管理。

≥300 条自然交互、≥30 条有效 reward 是后续既定数量门槛，不是自动训练许可。还需检查不同玩家/角色/话题覆盖、错误类型与标注一致性，保存负例，复核涉及隐私的导出与保留策略。
