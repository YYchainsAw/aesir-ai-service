# Reinforcement Learning

This directory is isolated from the Unreal command service in `app/`.

## `rl/boss/`

Boss-as-agent research for the semester defense. It mirrors Unreal observation
schema v3 and `EAesirBossAction`, contains the deterministic training simulator,
reward terms, Behavior Tree-style baseline, Gymnasium environment, and metrics.
Training uses `sb3-contrib` MaskablePPO so GAS-unavailable actions are excluded.

Commands:

```powershell
.\.venv\Scripts\python scripts\rl\boss\eval.py --episodes 20
.\.venv\Scripts\python scripts\rl\boss\train.py --timesteps 20000
```

The command service in `app/` never imports this package.
