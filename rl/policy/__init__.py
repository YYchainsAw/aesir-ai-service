"""RL 策略抽象：环境层 ``ActingPolicy`` 与服务层 ``TacticalPolicy``。

- ``ActingPolicy``：obs/状态 → 动作索引。规则基线适配器与 PPO 模型都实现
  它，``scripts/rl_eval.py`` 可互换 A/B。
- ``TacticalPolicy``：服务层接口（CombatContext → TacticalDecision），是
  RL 未来接入 ``/v1/tactical/resolve`` 的占位。本阶段不接入，仅定义。
"""
