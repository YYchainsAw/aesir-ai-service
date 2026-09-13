# WBP_LockOnIndicator 分析

> 核验日期：2026-09-12  
> 证据：Widget Tree 截图、`EventGraph.txt`、既有 `BP_AesirEnemyCharacter.EventGraph.txt`

## 1. Widget 自身

```text
SizeBox
└─ Border
```

`EventGraph` 已核验为空。本 Widget 当前只承载锁定标记的视觉结构，没有自行监听锁定状态的事件节点。

## 2. 外部可见性控制

```text
BP_AesirEnemyCharacter.SetLockOnIndicatorVisible(bVisible)
└─ LockOnIndicator.SetVisibility(bVisible)
```

| 节点 | Node GUID |
| --- | --- |
| Override `SetLockOnIndicatorVisible` | `1AC6C45A429003E0DB8E89B2D4EC9366` |
| Get `LockOnIndicator` | `662334A84FC8F87C9CC2DCA00F101A24` |
| `SceneComponent.SetVisibility` | `E31D812B42B7B28118B1AAA80492BD3E` |

`bVisible` 原样传给 Widget Component 的 `SetVisibility`。锁定目标如何选择不在本 Widget 内完成，而属于玩家 `TargetingComponent` 和敌人接口/角色逻辑的职责。

## 3. 证据边界

- 已证明：Widget Tree 为 `SizeBox → Border`。
- 已证明：EventGraph 为空。
- 已证明：敌人 Blueprint override 控制 `LockOnIndicator` Widget Component 可见性。
- 已确认：不存在其他 Function/Macro Graph。
- 尚未核验：Border 样式、尺寸和默认可见性。
