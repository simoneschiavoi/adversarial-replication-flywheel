# EXP-006-R03 — flywheel round 3 (no-memory CONTROL arm)

ONE mutation vs the incumbent: {"family": "chi_alloc", "value": "easy32hard256"}

Incumbent config: {"name": "chi-easy32hard128", "device": "mps.cpu", "chi_alloc": "easy32hard128", "permutation_seed": null, "shots_alloc": "uniform20k"}
Candidate config: {"name": "chi-easy32hard256", "device": "mps.cpu", "chi_alloc": "easy32hard256", "permutation_seed": null, "shots_alloc": "uniform20k"}

Decision rule (frozen in EXP-003): paired per-circuit normalized-XEB deltas on
the 12 val circuits; bootstrap 95% CI of the mean must exclude zero AND mean
delta > min_delta; cost (sum of queue+run minutes over val jobs, L-005)
noninferior within 2%. Enforced by ledger gates: {"fidelity_min": 1.014533, "score_max": 29.5426, "ci_excludes_null": true, "usd_max": 0.5, "jobs_max": 40}

Train-circuit evaluation is selection feedback only; never part of the gate.
