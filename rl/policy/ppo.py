"""sb3 PPO 模型 → ActingPolicy 适配器（训练脚本的进度评测与 A/B 评测共用）。"""

from rl.policy.base import ActingPolicy


class PPOPolicyAdapter:
    """包装 ``stable_baselines3.PPO``，实现环境层策略协议（确定性推理）。"""

    def __init__(self, model):
        self._model = model

    def select_action(self, obs, state) -> int:
        action, _ = self._model.predict(obs, deterministic=True)
        return int(action)
