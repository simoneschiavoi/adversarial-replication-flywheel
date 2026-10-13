# EXP-005-R07 — flywheel round 7 (flywheel arm)

ONE mutation vs the incumbent: {"family": "shots_alloc", "value": "easy10khard30k"}

Incumbent config: {"name": "r0-baseline", "device": "mps.cpu", "chi_alloc": "uniform64", "permutation_seed": null, "shots_alloc": "uniform20k"}
Candidate config: {"name": "shots-easy10khard30k", "device": "mps.cpu", "chi_alloc": "uniform64", "permutation_seed": null, "shots_alloc": "easy10khard30k"}

Decision rule (frozen in EXP-003): paired per-circuit normalized-XEB deltas on
the 12 val circuits; bootstrap 95% CI of the mean must exclude zero AND mean
delta > min_delta; cost (sum of queue+run minutes over val jobs, L-005)
noninferior within 2%. Enforced by ledger gates: {"fidelity_min": 0.980136, "score_max": 36.0656, "ci_excludes_null": true, "usd_max": 0.5, "jobs_max": 40}

Train-circuit evaluation is selection feedback only; never part of the gate.
