# Command Service

This package is the production HTTP command service used by Unreal.

- Entry point: `app.main:app`
- Owns: HTTP routes, command/tactical schemas, parsing, ASR, companion dialogue,
  execution receipts, and deterministic tactical resolution.
- Dependencies: `requirements.txt`; optional ASR dependencies live in
  `requirements-ml.txt`.
- Boundary: `app` must never import `rl`. The service remains usable when
  Gymnasium, Stable-Baselines3, and Torch are not installed.

RL inference will later enter through an explicit adapter at the Boss policy
boundary. Training code does not belong in this package.
