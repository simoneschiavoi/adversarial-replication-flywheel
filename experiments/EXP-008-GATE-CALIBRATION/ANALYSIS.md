# EXP-008-GATE-CALIBRATION — ANALYSIS (auto-rendered by `gate_calib.py analyze`)

generated: 2026-10-07T20:06:32+00:00 · source of every number below:
`data/analysis.json` (this file is a render, never hand-edited) · plan
sha256 `e6b78a0a5b646b6e…` · 192 jobs on
mps.cpu (TEST account) · campaign min_delta = 0.026951928

## A1 — per-circuit paired Δ (challenger − baseline)
- pooled mean over the 48 circuits: **+0.033890**
- per-rep means: rep1 +0.036324 · rep2 +0.031456
- pooled Δ by (n, d) cell (mean over the 3 instances; full 48-value arrays
  in analysis.json):

| n | d | class | pooled Δ |
|---|---|-------|----------|
| 20 | 4 | easy | -0.002988 |
| 20 | 8 | easy | -0.011274 |
| 20 | 12 | hard | -0.007068 |
| 20 | 16 | hard | +0.100687 |
| 22 | 4 | easy | -0.003993 |
| 22 | 8 | easy | -0.011634 |
| 22 | 12 | hard | +0.006476 |
| 22 | 16 | hard | +0.147357 |
| 24 | 4 | easy | +0.005958 |
| 24 | 8 | easy | +0.001394 |
| 24 | 12 | hard | +0.019900 |
| 24 | 16 | hard | +0.125712 |
| 26 | 4 | easy | +0.006924 |
| 26 | 8 | easy | -0.000087 |
| 26 | 12 | hard | +0.007759 |
| 26 | 16 | hard | +0.157114 |

## A2 — bootstrap 95% CI over the 48 circuits
10000 resamples, numpy default_rng(11), percentile method:
**[+0.017454, +0.052119]**

## A3 — same-config repeatability |rep1 − rep2|
- BASELINE (uniform64): mean 0.013116, sd 0.009425
  — 0.49× min_delta
- CHALLENGER (easy32hard128): mean 0.012736, sd 0.012093
  — 0.47× min_delta
- min_delta = 0.026951928: the gate's own noise
  yardstick vs the measured rep-to-rep noise above.

## A4 — fidelity-component pass probability at the n=12 decision scale
10000 subset draws (numpy default_rng(12)),
inner bootstrap 2000 resamples
(default_rng(13)), CI rule: exclude 0 iff
ci_low > 0 (campaign semantics). This simulates ONLY the gate's fidelity
components (mean > min_delta AND CI excludes 0); the campaign's cost gate
(wall-time ratio ≤ 1.02) is NOT simulated — EXP-008's per-config cost is
deterministic. The fresh library includes n=22 circuits (absent from the
frozen suite); subset draws model circuit-subset choice, not fresh shot
noise.

- observed effect (pooled Δ as-is, mean +0.033890):
  P(mean Δ > min_delta) = 0.6579
  P(CI excludes 0) = 0.6336
  **P(both) = 0.5852**
- shifted effect (true mean = min_delta exactly, shift
  -0.006938):
  P(mean Δ > min_delta) = 0.4862
  P(CI excludes 0) = 0.3449
  **P(both) = 0.3351**
- A4b, per-rep single-evaluation libraries (same circuit subsets; the
  pooled two-rep library and these bracket the campaign's
  single-evaluation decision):
- rep1: P(both) observed 0.6612 / shifted 0.3359
- rep2: P(both) observed 0.4591 / shifted 0.3138

DEVIATION (preregistered in PREREGISTRATION.json): the inner bootstrap uses
2000 resamples per draw, not the campaign
decision bootstrap's 5000 (src/metrics.py:128, seed 3) — 10000
draws × 5000 resamples × 12 circuits was the nesting feasibility bound;
2000 is fixed here and stated up front. The inner rng(13) stream advances
across draws within each effect level (fresh stream per level) — an
approximation of the campaign's fresh-per-decision rng.

## A5 — frozen prediction (scored once, here)
point +0.045, band [+0.015, +0.080]
(frozen in PREREGISTRATION.json BEFORE any dispatch) ·
observed pooled mean **+0.033890** · in_band = **True**

## Traceability
Per-job XEB, provider job ids and run statuses: `data/analysis.json` (`jobs`).
Raw counts: `data/counts/<job_name>.json`. Bookkeeping: `ledger/jobs.sqlite`
(exp_id `EXP-008-GATE-CALIBRATION`, 192 collected
jobs, $0.00). Truth: local statevector
probabilities under `data/truth/` (sha-pinned in `data/plan.json`).
