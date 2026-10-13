# EXP-008-GATE-CALIBRATION — gate calibration and repeatability at the decision scale

Post-campaign calibration experiment (the campaign itself is closed: holdout
sentinel `suite/.HOLDOUT_EVALUATED` present). Motivation, flagged by the
review panel as the sharpest weakness: in round 1 BOTH arms ran the same
mutation (`chi_alloc easy32hard128`) — flywheel Δ +0.0336, CI [−0.0013,
+0.0737] → REJECTED; control Δ +0.0344, CI [+0.0010, +0.0744] → PROMOTED.
The gate's verdict flipped on CI noise at n=12.

**Question.** At the campaign's 12-circuit decision scale, what is the
gate's fidelity-component pass probability — P(mean Δ > min_delta AND CI
excludes 0), the two components the campaign gate actually evaluates on
measurement data; the cost gate (wall-time ratio ≤ 1.02) is deterministic
per config here and is NOT simulated — for a true effect of the size the
campaign actually saw, and what is same-config run-to-run noise? Measured
on FRESH circuits with zero contact with the frozen suite or holdout.

## Extracted campaign semantics (verbatim, from src/harness.py)

The easy/hard rule that defines both configs (src/harness.py:52,
CHI_PRESETS declaration):

```
CHI_PRESETS = {          # chi by depth class (easy: d<=8, hard: d>=12)
    "uniform64":    {"easy": 64,  "hard": 64},
    ...
    "easy32hard128": {"easy": 32,  "hard": 128},
```

(src/harness.py:53 `"uniform64"`, src/harness.py:57 `"easy32hard128"`;
full map at src/harness.py:52–60.) Applied by (src/harness.py:150–152):

```
def chi_for(cfg: dict, depth: int) -> int:
    klass = CHI_PRESETS[cfg["chi_alloc"]]
    return klass["easy"] if depth <= 8 else klass["hard"]
```

Shots, same extraction (src/harness.py:63 and src/harness.py:155–157):

```
    "uniform20k":   {"easy": 20000, "hard": 20000},   # 6*20k + 6*20k = 240k

def shots_for(cfg: dict, depth: int) -> int:
    klass = SHOT_PRESETS[cfg["shots_alloc"]]
    return klass["easy"] if depth <= 8 else klass["hard"]
```

Both EXP-008 configs therefore use `shots = 20000` on every circuit; the
device is `mps.cpu`; neither config permutes (permutation_seed None →
identity site order, so no key un-permuting at scoring). CI gate semantics
follow src/metrics.py:146 (`ci_excludes_zero = decision["ci_low"] > 0.0`)
and the promote rule src/metrics.py:143–158 (mean Δ > min_delta AND CI
excludes 0 AND cost noninferior within 2%).

Campaign min_delta (frozen, from runs/flywheel/state.json:116):
**0.026951928377626822** (= 2 × noise_sd 0.013475964188813411, G3).

## Design

- **48 FRESH circuits**: qubits {20, 22, 24, 26} × depths {4, 8, 12, 16} ×
  3 instances. Generator mirrors src/freeze_suite.py's RCS brickwork
  (same `circuits.rcs_circuit` builder) with module constant
  `EXP008_SEED = 20261007`; per-circuit seeds `EXP008_SEED + n*100 + d*10 + i`
  (same arithmetic shape as freeze_suite.py:86).
- **Exact truth**: local statevector probabilities, float32 `.npy`
  (sim_exact.save_probabilities — the same method as the suite build),
  2 workers (the freeze precedent for n=26 memory).
- **2 configs, campaign-exact** (rule quoted above):
  - BASELINE `uniform64`: chi 64 everywhere;
  - CHALLENGER `easy32hard128`: chi 32 on easy circuits (d ≤ 8), chi 128 on
    hard circuits (d ≥ 12).
- **2 independent reps per (circuit, config)** → **192 jobs** (48 × 2 × 2),
  device `mps.cpu`, TEST account, expected cost **$0.00**, concurrency ≤ 2,
  per-job timeout 900 s (expected 1–3 min; ≥3× headroom respected).
- **Deterministic job names**: `exp008-{base|chal}-q{Q}d{D}i{I}-rep{R}`
  with R ∈ {1, 2}. **Resume semantics (dispatch-once contract):** a job
  name that already has ANY provider row in jobs.sqlite is NEVER
  re-dispatched — it is either settled or pending, and `collect`
  reconciles it by its provider id. After every dispatched group, dispatch
  asserts each group name maps to EXACTLY one provider id in the ledger,
  and at the end that no provider id is shared across two names; a breach
  is a hard SystemExit (manual reconciliation, never a resubmit). Within a
  live `run_batch` call, bq's reservation key (batch-level) plus its
  120-min same-name adoption window cover process kills; after that
  window an unfinished name is recovered via `collect` (or, if it failed
  terminally, reported as a failed job — the experiment is then
  incomplete by prereg and no retry job is silently invented). A
  terminal-failed job already recorded with an error is never re-fetched.
- Dispatch is **refused** unless ledger/experiments.json shows EXP-008
  REGISTERED (expected refusal during review), unless the on-disk SPEC.md
  and PREREGISTRATION.json sha256 still match the registration pins in
  ledger/experiments.json (post-registration edits de-register), unless
  today's mps/pauli-path rows in ledger/jobs.sqlite plus remaining plan
  jobs stay ≤ 900 (re-run after 00:00 UTC), for any path argument
  resolving inside `suite/` or a holdout dir, and for any plan artifact
  path that is non-relative, escapes the data dir (resolve() or realpath()
  / symlink), or touches suite/holdout; an extra guard refuses a non-TEST
  BQ_ACCOUNT. Dispatch and analyze both recompute every qpy/truth sha256
  against the plan pins and check the truth shape invariant (float32, length 2^n)
  before any cloud call or scoring.

## Seed non-collision statement

`EXP008_SEED = 20261007` does NOT appear among the integer literals of
src/freeze_suite.py (seed constants found there: `SPLIT_SEED = 20261107`
at line 46, `R_BASE_SEED = 20261100` at line 47; suite per-circuit seeds
are derived as `R_BASE_SEED + n*100 + d*10 + s`, line 86, over n ∈ {20, 24,
26} × d ∈ {4, 8, 12, 16} × s < 4, i.e. 48 derived seeds). The 48 EXP-008
derived seeds (`EXP008_SEED + n*100 + d*10 + i`, n ∈ {20, 22, 24, 26},
i ∈ {0, 1, 2}) are disjoint from the 48 suite derived seeds. Both facts are
ASSERTED AT IMPORT of src/gate_calib.py (ast parse of freeze_suite.py;
SystemExit on any collision) — a collision makes the module unusable.

## Budget / gates

- Ledger gates for registration: **jobs_max = 200** (192 planned + retry
  headroom), **usd_max = 0.50** (expected $0.00 on mps.cpu TEST; headroom
  for reconciliation retries).
- Device: mps.cpu only. Account: TEST only. Daily mps/pauli-path cap 900
  (guard + tools/bq_jobs.py LIMITS).

## No-contact clause

EXP-008 never reads, imports or derives from `prototype/suite/` or any
holdout artifact. Circuits are generated FRESH from EXP008_SEED; truth is
computed locally; scoring uses only `data/counts/` + `data/truth/` +
`data/plan.json`. The only suite-related read is the SOURCE of
src/freeze_suite.py (seed-literal collision assertion), which is not a
suite artifact. Path arguments resolving inside suite/ or holdout are
refused by code.

## Analysis (preregistered — PREREGISTRATION.json is authoritative)

**Scoring (frozen):** XEB = `metrics.xeb_normalized(metrics.canonical_counts(counts,
'mps.cpu'), truth)` — canonical bit order un-reverses mps keys; quantiles
use `np.quantile` default (linear) interpolation; circuit order is the
plan.json `circuits` order. Analyze validates every counts blob BEFORE
scoring: provider_job_id present and matching the ledger row for that
name, run_status COMPLETED, counts summing to exactly 20000, bitstring
width == n, and 192 DISTINCT provider ids across the 192 jobs — any
violation is a hard SystemExit (no partial analysis). Scoring is
once-only: analyze records an inputs digest (plan.json + all counts
blobs) and refuses to overwrite an existing analysis.json unless the
digest is unchanged AND `--redo` is passed; a digest MISMATCH is always
refused.

A1 per-circuit paired Δ (challenger − baseline), per rep and pooled over
reps (48 values). A2 bootstrap 95% CI over the 48 circuits (10000
resamples, numpy default_rng(11), percentile — an EXP-008 choice, larger
than the campaign decision bootstrap's 5000, src/metrics.py:128, seed 3).
A3 same-config repeatability |rep1 − rep2| per circuit per config (mean,
sd ddof=1). A4 fidelity-component pass probability at the n=12 decision
scale: 10000 subset draws (default_rng(12)), components mean Δ >
min_delta and percentile-bootstrap CI over the 12 drawn circuits with
2000 resamples (default_rng(13)) excluding 0 — run at TWO effect levels
(observed pooled Δ as-is, and shifted so the true mean sits exactly at
min_delta), plus A4b: the same draws on the two per-rep
single-evaluation libraries (the pooled two-rep library and the per-rep
libraries bracket the campaign's single-evaluation decision). The
campaign's cost gate (wall-time ratio ≤ 1.02) is NOT simulated — EXP-008's
per-config cost is deterministic. Documented deviations: the inner
bootstrap uses 2000 resamples, not the campaign decision bootstrap's 5000
(nesting feasibility); the inner rng(13) stream advances across draws
within each effect level (fresh stream per level) — an approximation of
the campaign's fresh-per-decision rng. The fresh library includes n=22
circuits (absent from the frozen suite); subset draws model
circuit-subset choice, not fresh shot noise. A5 frozen prediction: pooled
mean per-circuit paired Δ point +0.045, band [+0.015, +0.080], scored
once by `analyze`.

`analyze` writes `data/analysis.json` and renders `ANALYSIS.md` from it;
`grant/exp008_block.py::render_exp008_block` renders the appendix block
strictly from the analysis dict (KeyError on missing fields, no defaults,
no recomputation).
