# WBP_CombatResult 分析

> 核验日期：2026-09-12  
> 原始证据：`EventGraph.txt`（9 个节点）、`Functions/SetCombatResult.txt`（6 个节点）、Widget Tree 截图

## 1. 结果文本映射

```text
SetCombatResult(Result: EAesirMatchResult)
└─ Switch Result
   ├─ None    → TXT_Result.Text = "DEFEAT"
   ├─ Victory → TXT_Result.Text = "VICTORY"
   └─ Defeat  → TXT_Result.Text = "DEFEAT"
```

| 节点 | Node GUID |
| --- | --- |
| Function Entry `SetCombatResult` | `8306DF7746EE8707FF8B6AAE0B39E901` |
| Switch `EAesirMatchResult` | `33433A8D43DC67A57E50678FD165EA26` |
| Get `TXT_Result` | `CCE49BD948F6A69C7B29128ABB2DFAAA` |
| Victory 文本 | `0F60DCD540C742E3CE7018BB4B7CFD45` |
| Defeat 文本 | `83E95632485DA5F678FD54B69D0A666F` |
| None 文本 | `B1EA7A9F473DC9471AFDC98F010DA863` |

`None` 当前与 `Defeat` 使用相同文本。这是实际 Blueprint 行为，不改写为“无结果”或空文本。

## 2. 重新开始流程

```text
BTN_Restart.OnClicked
├─ SetGamePaused(false)
├─ SetInputMode_GameOnly(GetOwningPlayer())
├─ GetOwningPlayer().bShowMouseCursor = false
└─ OpenLevel("L_AesirCombatTest", Absolute=true)
```

| 节点 | Node GUID |
| --- | --- |
| `BTN_Restart.OnClicked` | `90E739CE4E7FA026196483BBB2229153` |
| `SetGamePaused(false)` | `D316ADB14D9F8ACD1B3C1EB2FC028FC2` |
| `GetOwningPlayer` | `7DE51AC74E08E3941D5C4C9578C3A50F` |
| `SetInputMode_GameOnly` | `076F38984EEAB083436A03BD268A5453` |
| `bShowMouseCursor=false` | `B6BFBA2F4779FC58099094B875F8FE6F` |
| `OpenLevel(L_AesirCombatTest)` | `DF83528B416C78544F0C61A65A012804` |

## 3. 未参与运行的事件

| 节点 | Node GUID | 状态 |
| --- | --- | --- |
| `PreConstruct` | `3DCD4D14491A87192733BA8213D48900` | Disabled；无业务连线 |
| `Construct` | `65B0106A41451E5EAD632F89B5B72499` | Disabled；无业务连线 |
| `Tick` | `9924887C42416BF996545098741A5F62` | Disabled；无业务连线 |

## 4. GameMode 外部驱动

已有 `BP_AesirGameMode.EventGraph` 证明：战斗结束后创建 `WBP_CombatResult`，传入比赛结果，调用 `SetCombatResult`，添加到 Viewport，并切换鼠标与 UI 输入状态、暂停游戏。

关键跨资产节点：

| 节点 | Node GUID |
| --- | --- |
| `OnCombatEnded` | `1A19B35A4D1B24683DE5459418CA4500` |
| Create `WBP_CombatResult` | `003172024556C2146EEFAD9AB9B00B51` |
| 调用 `SetCombatResult` | `01EAAA6741DC0C2504A72FA19DD6CAC1` |
| `AddToViewport` | 见 `BP_AesirGameMode.EventGraph.txt` |
| `SetInputMode_UIOnlyEx` | `C77EAA2F4D61DC5BBFC43B95AE0E77FC` |
| `SetGamePaused(true)` | `A391746640FCF1958480078CDA8E3131` |

GameMode 中负责显示鼠标的变量设置节点导出时带有 `ErrorType=1`；用户已于 2026-09-12 在 UE 编辑器中重新 Compile，并确认编译成功。因此该标记不再视为当前阻塞风险。
