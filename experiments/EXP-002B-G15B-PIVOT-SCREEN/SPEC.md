# EXP-002B — G1.5b pivot feasibility screen

## Why this experiment exists

EXP-002-G15-FEASIBILITY was parked (cause EXTERNAL_ENDPOINT_DENIED): the sponsor
peaked-circuit endpoint `GET /api/v1/peaked-circuits/file` returns HTTP 403
"Access denied for this endpoint" on the TEST account at every difficulty
probed (runs/20261006T030210Z_g15). Lane P (sponsor peaked circuits, PPL score)
is therefore unavailable before the freeze. Per the preregistered cut order
("second backend lane" is cut before suite shrink), the attack lane pivots to:

**Lane Q — local RCS brickwork at 30–56q, observable estimation on `pauli-path`,
scored by fidelity against a frozen basis (ε_ref = 1e-5, the minimum supported
truncation threshold).**

Lane R (exact-truth XEB ≤ 26q on mps.cpu) is unchanged and keeps the χ evidence
via a one-shot sweep, not as a flywheel mutation.

## What this screen measures (real jobs, no fabrication)

1. `pauli-path` wall-time at ε ∈ {1e-5, 1e-3} on local RCS
   n ∈ {32, 40, 56} × depth ∈ {8, 16} — 12 jobs, Z-on-even-sites observable
   (probe only; the freeze uses frozen random-weight observables).
2. ε-signal: does EV(ε=1e-3) differ from EV(ε=1e-5) beyond float noise? If not,
   the ε mutation family is inert and the flywheel degenerates — must be known
   before freezing.
3. `mps.cpu` telemetry feasibility at n=56 d=16, χ ∈ {64, 256} — 2 jobs, to
   decide whether any ≥30q sampling evidence can be had cheaply (report-only).

## Gates (registered in the ledger)

- jobs_max = 20 (planned 14)
- usd_max  = 0.50 (expected $0.00 on cpu-class devices)

## Pass criteria

- `envelope_ok`: every pauli-path job COMPLETED with wall (queue+run) ≤ 5 min
  → sizes that pass at ε_ref define the freeze's Lane Q sizes; sizes that fail
  are dropped (documented shrink, per the preregistered cut order).
- `eps_moves_ev`: |EV(1e-5) − EV(1e-3)| > 1e-9 on at least one (n, d).
  If false, Lane Q is redesigned before any freeze (this screen may fail
  without sinking the project; it is a measurement, not a claim).

## What this screen does NOT do

- No scoring of any candidate against the basis (that is G3/G4 work).
- No freeze, no holdout access, no promotion. Record-only experiment.

## Deviations from the original goal text (documented, pre-freeze)

Original mutation set {χ, ε, permutation, shots} assumed Lane P survived.
With Lane P dead, χ has no scoreable effect on the primary lane; the flywheel
mutation set becomes {ε, permutation, shots} on Lane Q, with χ measured once as
a Lane R telemetry sweep. This is within the preregistered cut order, which
shrinks the mutation space before it shrinks the suite or the report.
