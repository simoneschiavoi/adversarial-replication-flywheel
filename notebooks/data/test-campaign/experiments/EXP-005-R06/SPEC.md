# EXP-005-R06 — flywheel round 6 (flywheel arm)

ONE mutation vs the incumbent: {"family": "permutation", "value": 37}

Incumbent config: {"name": "r0-baseline", "device": "mps.cpu", "chi_alloc": "uniform64", "permutation_seed": null, "shots_alloc": "uniform20k"}
Candidate config: {"name": "perm37", "device": "mps.cpu", "chi_alloc": "uniform64", "permutation_seed": 37, "shots_alloc": "uniform20k"}

Decision rule (frozen in EXP-003): paired per-circuit normalized-XEB deltas on
the 12 val circuits; bootstrap 95% CI of the mean must exclude zero AND mean
delta > min_delta; cost (sum of queue+run minutes over val jobs, L-005)
noninferior within 2%. Enforced by ledger gates: {"fidelity_min": 0.980136, "score_max": 36.0656, "ci_excludes_null": true, "usd_max": 0.5, "jobs_max": 40}

Train-circuit evaluation is selection feedback only; never part of the gate.
