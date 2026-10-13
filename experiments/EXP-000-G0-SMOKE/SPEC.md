# EXP-000 — G0 smoke test

**Goal**: verify API + key reachability end-to-end before anything else.

**Design**: 4-qubit GHZ circuit on the `cpu` device, 512 shots. Record
wall-clock, queue time, run time, exact API host, job-id round-trip
(submit -> get -> search), and the job's submitted-vs-billed cost.

**Pass criteria** (all required):
- run_status COMPLETED
- job-id round-trip verified
- GHZ probability mass (0000 + 1111) > 0.90
- billed cost field present (expected $0.00 on the plan-included cpu tier)

**Disclosure**: this SPEC was written AFTER the smoke run executed
(infrastructure probe, no acceptance decision involved, no scientific claim).
It is registered for the audit trail only; nothing in the campaign depends on
promoting EXP-000.

## Result

PASS — 2026-10-06, job `1g8svhqUveQX5nBm`, wall 1.08 s, queue 125 ms, run 1 ms,
billed $0.00, GHZ mass 1.000. See `runs/*_g0/metrics.json`.
