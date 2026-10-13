# AGENTS.md — constitution of the Adversarial Replication Flywheel prototype

Read order (mandatory, before touching anything):
1. this file
2. `STATE.md` (rolling state)
3. `researcher/POLICY.md`, `researcher/LAWS.json`, `researcher/rsi.json` views
4. the SPEC + PREREGISTRATION of the experiment you are about to touch

## What this is

A closed-loop, self-improving classical attack harness on quantum-advantage
claims, run on the BlueQubit platform. The prototype (System A) is the evidence
appendix of a grant proposal and the seed of the funded 3-month system (System
B): same files, same gates, miniature scale.

Language rules (hard): no AGI vocabulary anywhere ("autonomous scientist",
"intelligence explosion", etc. are banned). Say "self-improving simulation
loops" / "closed-loop method refinement". The phrase "recursive
self-improvement" appears AT MOST ONCE across all artifacts, operationally
defined as: accepted mutants become versioned parents of the next round.

## Loop stages and gates

| Stage | Gate | Enforced by |
|---|---|---|
| S0 BOOT | G0: API+key reachable, 4q GHZ smoke, job-id round trip, submitted-vs-billed cost | `src/g0_smoke.py` |
| S1 CALIBRATE | G1: tutorial baseline (RCS XEB vs depth, real job IDs) | `experiments/EXP-001-*` |
| S1.5 SCREEN | G1.5: attack jobs ≤5 min on mps.cpu BEFORE freeze | `experiments/EXP-002-*` |
| S2 FREEZE | G2: 48 circuits (24 train/12 val/12 LOCKED holdout), MANIFEST sha-pinned | `suite/`, `tools/protected_paths.sh` |
| S3 BASELINE | G3: incumbent config ledgered + prediction row frozen | `tools/ledger.py`, `tools/rsi.py predict` |
| S4 FLYWHEEL | G4: 8–15 rounds, ONE mutation/round, PROMOTE code-enforced | `tools/ledger.py` |
| S5 CONTROLS | no-memory arm mandatory (equal $), random-search stretch | `experiments/EXP-006-*` |
| S6 HARVEST | insights + laws from evidence | `tools/rsi.py`, `researcher/LAWS.json` |
| S7 REPORT | G5 report complete or honest plateau; G6 holdout touched ONCE; G7 claims.json complete | `src/report.py` |
| S8 PORT | G8: spend ≤ $2 (test) / rerun on personal account | `tools/bq_jobs.py` |

## Hard rules (violating any of these invalidates the campaign)

1. **Freeze before run.** Every experiment has SPEC.md + PREREGISTRATION.json
   sha-pinned at `ledger.py register` BEFORE results exist for it.
2. **Reserve before submit.** No BlueQubit job is dispatched without a
   reservation row in `ledger/jobs.sqlite` (idempotency key persisted). An
   ambiguous acknowledgment is reconciled via `client.search` — NEVER a blind
   resubmit. Double dispatch of one reservation is refused by code.
3. **PROMOTE is impossible without gate pass + hash integrity** (`tools/ledger.py`).
   A gate metric missing from metrics.json is a FAIL, never a pass.
4. **3-attempt cap** per experiment. PARK/BAN require a cause class.
5. **The holdout is LOCKED.** `suite/holdout/` is never read by the improver,
   never loaded by the mutation controller, evaluated exactly once at close by
   `src/holdout_eval.py`, and only if the ledger shows campaign completion.
6. **Rerunning a healthy run is fraud.** A completed, valid run is immutable;
   re-execution happens only on INFRA failure with a cause class.
7. **Every reported number traces to a real BlueQubit job ID.** No fabricated
   or "simulated" results, ever. Exact ideal probabilities used for scoring are
   computed locally from the sha-pinned frozen circuits — deterministic, public,
   and disclosed as such; the *samples* always come from real jobs.
8. **One mutation per round.** The mutation and its acceptance gate are written
   into the round's SPEC before any job for that round is dispatched.
9. **Noise canary**: the round-0 incumbent is re-evaluated on val at rounds ~6
   and ~10; drift beyond the preregistered noise band tightens CI gates.
10. **Zero promotions is a valid, reportable outcome.** The honest-plateau
    branch is a designed deliverable. Never fabricate a staircase.

## Budgets (test account)

- Total spend ≤ $2 on this account (GPU/QPU FORBIDDEN — they burn $ credits;
  cpu/mps.cpu/pauli-path are plan-included, billed $0.00).
- ≤2 concurrent jobs; ≤900 combined mps.cpu/pauli-path jobs per UTC day
  (account cap 1000; headroom kept deliberately).
- 15-min hard cap per mps/pauli-path job — size everything with ≥3× headroom
  (≤5 min planning envelope).

## Tool constraints

- `tools/` (ledger, rsi, lawcheck, bq_jobs): Python stdlib ONLY.
- Scientific libraries (numpy, qiskit, bluequbit SDK, matplotlib) live only in
  `src/`.

## Banned vocabulary quicklist

banned: AGI, artificial general intelligence, autonomous scientist,
intelligence explosion, "the system discovers new science".
preferred: closed-loop method refinement, self-improving simulation loop,
versioned attack portfolio, enforced experiment ledger.
