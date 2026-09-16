# UML 证据目录

该目录保存生成和核验 UML 所使用的结构化事实，不保存主观设计描述。

计划生成的证据：

- `cpp-inventory.json`：Unreal C++ 类型、组件、委托和 Blueprint API；
- `blueprint-graphs.json`：蓝图 Graph、Node GUID、Pin 与连线；
- `behavior-trees.json`：行为树节点、层次和 Blackboard Key；
- `fastapi-openapi.json`：后端当前 OpenAPI Schema；
- `python-inventory.json`：路由、Schema、Service 依赖；
- `traceability.csv`：UML 元素到上述证据的追踪矩阵。

蓝图相关事实在导出前一律使用 `pending_blueprint_verification` 状态，不能标记为已实现闭环。

当前人工填写入口：

- [Unreal 业务资产导入清单](asset-inventory.md)
- [蓝图核验证据](blueprints/README.md)
- [当前核验清单](blueprints/verification-checklist.md)
- [行为树与 Blackboard 证据](behavior-trees/README.md)
- [Enhanced Input 证据](input/README.md)
- [动画资产证据](animations/README.md)
- [测试关卡证据](levels/L_AesirCombatTest/metadata.md)
