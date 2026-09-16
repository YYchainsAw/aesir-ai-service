# Reinforcement Learning

This directory is isolated from the Unreal command service in `app/`.

## `rl/boss/`

Boss-as-agent research for the semester defense. It mirrors Unreal observation
schema v4 and `EAesirBossAction`, contains the deterministic training simulator,
reward terms, Behavior Tree-style baseline, Gymnasium environment, and metrics.
Training uses `sb3-contrib` MaskablePPO so GAS-unavailable actions are excluded.

Commands:

```powershell
.\.venv\Scripts\python scripts\rl\boss\eval.py --episodes 20
.\.venv\Scripts\python scripts\rl\boss\train.py --timesteps 20000
```

Formal training writes the final model and manifest plus periodic checkpoints,
balanced per-profile evaluation metrics, a best periodic-evaluation model, and
TensorBoard event files. Example:

```powershell
.\.venv\Scripts\python scripts\rl\boss\train.py `
  --timesteps 1000000 --seed 0 --n-envs 8 --eval-episodes 100 `
  --checkpoint-freq 100000 --periodic-eval-freq 100000 `
  --periodic-eval-episodes 30 --name ppo_boss_schema_v4_sim004_seed_0

.\.venv\Scripts\python -m tensorboard.main --logdir models\rl\boss\tensorboard
```

`boss-sim-004` clamps damage to remaining health and calibrates defensive and
evasive player profiles so evaluation is not dominated by ceiling results.
The observation/action contract remains schema v4.
`boss-reward-003` adds an explicit penalty when the player perfect-guards a
Boss attack.

Use `--resume <checkpoint.zip>` to continue an interrupted run. PPO
hyperparameters are explicit CLI options and are copied into the manifest.
`--disable-tensorboard` exists only for lightweight smoke tests; keep event
logging enabled for formal runs.

The command service in `app/` never imports this package.
