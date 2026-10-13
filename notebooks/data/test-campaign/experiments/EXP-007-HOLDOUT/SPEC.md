# EXP-007-HOLDOUT — G6 one-shot locked-holdout evaluation

The 12 holdout circuits of the frozen suite (suite_sha256
bee1e97245f2cabf…) are evaluated EXACTLY ONCE, after every round of
both arms is closed. Three configs, one unlock window each for copying
circuits+truths only (jobs run after re-lock):

  flywheel_final = {"name": "r0-baseline", "device": "mps.cpu", "chi_alloc": "uniform64", "permutation_seed": null, "shots_alloc": "uniform20k"}
  baseline_r0    = {"name": "r0-baseline", "device": "mps.cpu", "chi_alloc": "uniform64", "permutation_seed": null, "shots_alloc": "uniform20k"}
  control_final  = {"name": "chi-easy32hard128", "device": "mps.cpu", "chi_alloc": "easy32hard128", "permutation_seed": null, "shots_alloc": "uniform20k"}

Score: per-circuit normalized XEB (canonical mps key order; inverse site
permutation before lookup when the config permutes). No acceptance decision
is made here — this is measurement. Campaign state at evaluation:
10 flywheel rounds, 10 control rounds, 1 promotions total.

Gates: caps only (jobs_max=40, usd_max=0.50; mps.cpu is $0).
