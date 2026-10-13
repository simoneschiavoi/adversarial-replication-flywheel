# EXP-009 — PROD-key smoke test (personal account)

**Goal**: verify the personal-account key (`BLUEQUBIT_API_KEY_ACCOUNT_PROD`,
added to `.env` 2026-10-07) and the `BQ_ACCOUNT=personal` switch in
`src/bq.py` end-to-end, BEFORE the Oct-11 replication run.

**Design**: identical probe to EXP-000-G0-SMOKE, run against the personal
account: 4-qubit GHZ on the `cpu` device, 512 shots, job name
`exp009-prodsmoke-ghz`. Records job-id round-trip, wall/queue/run times,
billed cost, and asserts the announce line resolves `account=personal` with
a key distinct from the TEST key (last-4 comparison only; full keys never
leave `.env`).

**Pass criteria** (all required):
- run_status COMPLETED
- job-id round-trip verified
- GHZ probability mass (0000 + 1111) > 0.90
- billed cost field present and ≤ $0.01
- account switch resolved to `account=personal`

**Budget**: 1 job, `cpu` device, gates `usd_max=0.01`, `jobs_max=2`. No
QPU/GPU usage in this experiment — personal-account compute stays reserved
for the Oct-11 replication ($8 ceiling).

**Preregistration note**: SPEC + PREREGISTRATION frozen BEFORE execution
(unlike EXP-000, which was registered post-hoc as an infrastructure probe).
No acceptance decision, no scientific claim; de-risking only.
