"""Aesir RL 实验包（Phase 4，可选依赖）。

顶层包，与 ``app/`` 平级：服务进程只加载 ``app.main:app``，物理上不会
import 本包，torch/sb3/gymnasium 等重依赖因此被隔离在服务运行时之外。
依赖方向单向 ``rl -> app``（复用 schemas 与规则策略），``app`` 绝不
import ``rl``。
"""
