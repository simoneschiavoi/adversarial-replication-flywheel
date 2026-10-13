# EXP-003 — G2 suite freeze (post-pivot exact-truth design)

## Design lineage (why this suite looks like this)

1. Original goal: 48 circuits = 36 sponsor peaked (Lane P, PPL score, 30–56q)
   + 12 local exact-truth RCS (Lane R). Mutation space {χ, ε, permutation, shots}.
2. EXP-002 parked: `GET /api/v1/peaked-circuits/file` → 403 on the TEST account
   (runs/20261006T030210Z_g15). Lane P unavailable.
3. EXP-002B (G1.5b/c pivot screen): pauli-path on random RCS is degenerate in
   the feasible region — ε=1e-5 is server-rejected ("memory overflow") at every
   probed (n,d) including 20q; ε=1e-3 completes in ~0.06 min returning EV
   exactly 0.0 (all paths truncated). No usable window, no ε signal
   (runs/20261006T030424Z_g15b, envelope_ok=False, usable_sizes=[]).
4. Per the preregistered cut order — second backend lane first, then the
   mutation space shrinks to the core {χ, permutation, shots} — the acceptance
   suite falls back to the exact-truth lane, expanded to all 48 circuits.

## Frozen suite

- 48 local RCS brickwork circuits: n ∈ {20, 24, 26} × depth ∈ {4, 8, 12, 16}
  × 4 seeds (seed = 20261100 + 100n + 10d + s). QPY-sha-pinned.
- Exact truth: local statevector probabilities (float32), sha-pinned.
- Split: seeded permutation (default_rng(20261107)) over all 48 — 24 train /
  12 val / 12 holdout.
- Attacker: mps.cpu. Score: per-circuit normalized XEB
  (raw / (2^n·Σp²−1); exact→1, uniform→0; mps count keys canonicalized).
- Acceptance metric: mean normalized XEB over the 12 val circuits, paired
  per-circuit vs incumbent. Cost: sum of queue+run minutes over val jobs.
- Mutation space (frozen): chi_alloc presets, site permutation (jointly
  transformed scoring — no oracle leakage), shots_alloc presets.
- Holdout: circuits + truths chmod-000 in suite/holdout/, access-logged,
  one-shot evaluator with sentinel; harness refuses rounds after the sentinel.

## Freeze invariants

- Freeze dispatches ZERO cloud jobs (all local).
- One-shot: a second freeze is refused while MANIFEST.json exists.
- The manifest sha covers every circuit, truth sha, split, and rule.

## Out-of-suite telemetry (reported, never gated on)

- mps.cpu at 56q d16: χ=64 wall 7.53 min (job in the g15b run dir) — a
  feasibility datum beyond the acceptance suite.
- pauli-path window characterization at 32–56q (g15b/c) — including the
  silent EV=0.0 degeneracy at ε=1e-3.

## Gates (registered at freeze)

Caps only: jobs_max=1, usd_max=0 — the freeze itself runs no jobs; recording
the freeze artifact anchors its integrity in the ledger.
