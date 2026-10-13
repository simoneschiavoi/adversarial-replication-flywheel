# EXP-001 — G1 tutorial baseline (mini RCS XEB fidelity vs depth)

**Goal**: CPU-scaled reproduction of the BlueQubit tutorial
("reproduce a mini version of Google's 67-qubit RCS benchmark... mini plot in
the style of Fig. S3a: fidelity vs cycles").

**Design** (frozen before any job for this EXP is dispatched):
- RCS brickwork circuits (random SU(4) 2q layers, seeded, QPY-pinned):
  n ∈ {20, 24, 26}, depths {4, 8, 12, 16}; base seed 20261006, per-circuit
  seed = base + n*100 + depth.
- Per circuit: ONE `cpu` job (exact sampler, 5000 shots) and ONE `mps.cpu`
  job with chi=64 (approximate sampler, 5000 shots). 24 jobs total.
- Metric: **per-circuit normalized linear XEB** of each sampler's samples
  against the exact local statevector of the same frozen circuit:
  raw F = 2^n * E_samples[p_ideal(x)] - 1, normalized F_norm = F / C where
  C = 2^n * sum(p_ideal^2) - 1 is the constant the EXACT sampler scores on
  that circuit. Rationale (validated locally pre-freeze, src/validate_core.py):
  shallow RCS circuits are pre-Porter-Thomas (C ranges ~2.1–9 over our depths),
  so raw F of the exact sampler is NOT 1; normalization anchors exact = 1 at
  every depth. Raw values are also reported per row (columns *_xeb_raw).
- Expected: cpu sampler F_norm ~ 1 at all depths; MPS(chi=64) decays with
  depth (entanglement grows past the bond budget). That decay IS the
  tutorial's fidelity-vs-depth plot, obtained at a scale where exact ground
  truth exists.

**Deviation note (preregistered)**: the goal text says "~24–40 qubits". Exact
XEB requires ideal probabilities; at 30–40q no exact ground truth exists on
any available lane, so the exact-truth lane is run at 20/24/26. The tutorial
itself directs a mini 5% subset. The 30–56q scale story is carried by G1.5 /
G2 on the sponsor's peaked circuits (also RCS-style), where the PPL metric
needs no ideal probabilities.

**Cost plan**: 15 cpu jobs (plan-included, $0) + 15 mps.cpu jobs ($0), all
well under the 15-min cap at chi=64, n<=26 (expected seconds each).

**Pass criteria (G1)**: fidelity-vs-depth plot produced; every point carries
a real BlueQubit job ID; cpu-sampler F_norm > 0.9 at all depths (sanity
anchor); mps64 F_norm strictly decreasing trend with depth at n=26
(truncation physics).
