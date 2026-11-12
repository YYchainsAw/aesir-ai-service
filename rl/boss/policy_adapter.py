"""Shared masked, deterministic prediction. No training or SB3 imports."""
from rl.boss.contract import ACTION_COUNT, OBSERVATION_DIM, BossAction, make_observation, make_action_mask

def predict_action(model, observation) -> BossAction:
    import numpy as np
    observation = make_observation(observation)
    mask = np.asarray(make_action_mask(observation), dtype=np.bool_)
    action, _ = model.predict(np.asarray(observation, dtype=np.float32), deterministic=True, action_masks=mask)
    value = np.asarray(action)
    if value.size != 1 or value.dtype.kind not in "iu":
        raise ValueError("Boss policy must return one integer action")
    selected = BossAction(int(value.item()))
    if not mask[selected]:
        raise ValueError("Boss policy selected an unavailable action")
    return selected

class PPOBossPolicy:
    def __init__(self, model):
        if tuple(model.observation_space.shape) != (OBSERVATION_DIM,):
            raise ValueError("model observation space does not match schema 4")
        if model.action_space.n != ACTION_COUNT:
            raise ValueError("model action space does not match schema 4")
        self.model = model

    def select_action(self, observation, state) -> BossAction:
        return predict_action(self.model, observation)
