# EXP-005-CANARY10 — noise canary at flywheel round 10

Re-evaluates the CURRENT incumbent on the 12 val circuits (identical config,
fresh sampling noise). Decision rule (frozen): |mean paired delta| >
2 x noise_sd (from G3) sets state.drift_flag, which tightens round gates by
1.5x min_delta. No promotion, no mutation, no insight written.

Gates: caps only (jobs_max=14, usd_max=0.50).
