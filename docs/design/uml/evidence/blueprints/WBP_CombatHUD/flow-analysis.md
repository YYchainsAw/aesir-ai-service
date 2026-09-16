# WBP_CombatHUD EventGraph 分析

> 核验日期：2026-09-12  
> 原始证据：`EventGraph.txt`（12 个节点）

## 1. 初始化与生命委托绑定

```text
Construct
└─ GetOwningPlayerPawn
   └─ Cast AAesirPlayerCharacter
      └─ Get HealthComponent
         └─ Assign OnHealthChanged → OnHealthChanged_Event
            └─ SetPlayerHealth(
                 GetCurrentHealth(HealthComponent),
                 GetMaxHealth(HealthComponent)
               )
```

| 节点 | Node GUID |
| --- | --- |
| `Construct` | `3EDDDA874AA9FE2146317F9D42D390DE` |
| `GetOwningPlayerPawn` | `2D9F0A8248F493BB080D169F9FF36C4D` |
| Cast `AAesirPlayerCharacter` | `EC23D9CF4DF14B79C1EE0E8582381E08` |
| Get `HealthComponent` | `3FB47FF14A3E26322B19BD9DFDA09FAC` |
| Assign `OnHealthChanged` | `22FFB5784188FD5075365FA436D04DDE` |
| 初始调用 `SetPlayerHealth` | `21C5B4E74EC9EC876D53A19105CB0097` |
| `GetCurrentHealth` | `4E3F73074C08C9D3588948B6D0EEDB94` |
| `GetMaxHealth` | `7D6AA5AD48C6FF013E7ED48CEB500EEE` |

## 2. 生命变化更新

```text
OnHealthChanged_Event(CurrentHealth, MaxHealth, HealthDelta)
└─ SetPlayerHealth(CurrentHealth, MaxHealth)
```

| 节点 | Node GUID |
| --- | --- |
| `OnHealthChanged_Event` | `99EC91654686E9B79C2192A1BF74F503` |
| 调用 `SetPlayerHealth` | `3FDA74A242E29FA563D4878CF8862C42` |

`HealthDelta` 在当前 EventGraph 中没有继续传给其他节点。

## 3. 未参与运行的事件

| 节点 | Node GUID | 状态 |
| --- | --- | --- |
| `PreConstruct` | `1EDE404A4B3F73305906748F795AC093` | Disabled；无业务连线 |
| `Tick` | `103CF2A744E8E123C5CAAE8D126E6A21` | Disabled；无业务连线 |

因此当前 HUD 更新方式是“构造时初始化 + 生命委托驱动”，不是每帧轮询。

## 4. SetPlayerHealth 函数

```text
SetPlayerHealth(CurrentHealth, MaxHealth)
├─ SafeMaxHealth = Max(MaxHealth, 1.0)
├─ RawPercent = CurrentHealth / SafeMaxHealth
├─ DisplayPercent = Clamp(RawPercent, 0.0, 1.0)
└─ PB_PlayerHealth.SetPercent(DisplayPercent)
```

| 节点 | Node GUID |
| --- | --- |
| Function Entry `SetPlayerHealth` | `674F59704BD7D74890C29CA8FD15B97E` |
| `FMax(MaxHealth, 1.0)` | `192415AA4933D76D8EA4D981D8385C03` |
| `Divide_DoubleDouble` | `742BF0D945214616450FEB9F9EC946AA` |
| `FClamp(0.0, 1.0)` | `346F88B0496D547D5BC916B3518BBA78` |
| Get `PB_PlayerHealth` | `C7CD609649753B8400039788A363FB10` |
| `ProgressBar.SetPercent` | `188E5650416C503E16ECA692EA275BB3` |

该函数同时具备分母下限保护和最终显示范围限制。

## 5. 证据边界

- 已证明：HUD 监听玩家 `HealthComponent.OnHealthChanged`。
- 已证明：初始化和生命变化都进入 `SetPlayerHealth(CurrentHealth, MaxHealth)`。
- 已证明：Widget Tree 含根 `CanvasPanel` 与 `PB_PlayerHealth: ProgressBar`。
- 已证明：`SetPlayerHealth` 执行安全分母、除法、Clamp，并调用 `PB_PlayerHealth.SetPercent`。
- 尚未核验：Designer 中 ProgressBar 的颜色、样式、动画等纯表现默认值。
