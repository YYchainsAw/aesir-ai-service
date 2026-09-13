# WBP_EnemyHealthBar 分析

> 核验日期：2026-09-12  
> 原始证据：`EventGraph.txt`、`Functions/SetEnemyHealth.txt`、Widget Tree 截图

## 1. Widget 自身事件图

`EventGraph` 已由用户确认为空，记录为 `EMPTY_GRAPH_VERIFIED`。因此生命更新不是由本 Widget 自己绑定事件完成的。

## 2. SetEnemyHealth 函数

```text
SetEnemyHealth(CurrentHealth, MaxHealth)
├─ RawPercent = CurrentHealth / MaxHealth
├─ DisplayPercent = Clamp(RawPercent, 0.0, 1.0)
└─ PB_EnemyHealth.SetPercent(DisplayPercent)
```

| 节点 | Node GUID |
| --- | --- |
| Function Entry `SetEnemyHealth` | `F50A8F9C449EAC7161D15F8EEE372C02` |
| Get `PB_EnemyHealth` | `EE6C2C8549CA1CEF04147B97B350DCC6` |
| `ProgressBar.SetPercent` | `26092B2A492D05F831BAD1B71A9FE51C` |
| `Divide_DoubleDouble` | `B8A76C644BDAE5260C8803BBEC66634A` |
| `FClamp(0.0, 1.0)` | `93C7C7314FBF9145DFFB88ADA555172F` |

函数有最终 `[0.0, 1.0]` Clamp，但没有在除法前保护 `MaxHealth` 分母。

## 3. 外部驱动关系

已有 `BP_AesirEnemyCharacter.EventGraph` 原文提供跨资产调用证据：

```text
BP_AesirEnemyCharacter.BeginPlay
├─ 获取 EnemyHealthBarWidget.UserWidgetObject
├─ Cast WBP_EnemyHealthBar
├─ 保存 EnemyHealthBarRef
├─ SetEnemyHealth(CurrentHealth, MaxHealth)
└─ Bind HealthComponent.OnHealthChanged → OnEnemyHealthChanged

OnEnemyHealthChanged(CurrentHealth, MaxHealth, HealthDelta)
└─ EnemyHealthBarRef.SetEnemyHealth(CurrentHealth, MaxHealth)
```

| 跨资产节点 | Node GUID |
| --- | --- |
| `BP_AesirEnemyCharacter.ReceiveBeginPlay` | `8656EDC447044BA53E0438AA1CA92D9B` |
| 初始调用 `SetEnemyHealth` | `A2AE9A6841BB8B1EF337E1A4131150C5` |
| Bind `OnHealthChanged` | `3D01D9F5451D20EBE81BB5A743674482` |
| `OnEnemyHealthChanged` | `73EBDA1C47F444BBFAD02CB0258F1895` |
| 变化时调用 `SetEnemyHealth` | `553D24CA4B9D550CC4055BAC3DB38F4D` |

因此该敌人生命条同样采用“初始化 + 委托驱动”，不是 Widget Tick 轮询。
