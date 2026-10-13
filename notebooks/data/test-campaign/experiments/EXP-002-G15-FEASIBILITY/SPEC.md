# EXP-002 — G1.5 feasibility screen (BEFORE freezing the suite)

**Goal**: verify that candidate attack jobs at 30–56q fit the ≤5-minute
envelope (3× headroom under the 15-min mps cap) BEFORE the suite is frozen,
and detect whether the sponsor's peaked circuits give the MPS sampler any
peak-lift signal to optimize.

**Design**:
1. Probe `get_peaked_circuit` at difficulties {1,3,5,7,9,10}: record n,
   2q gate count, metadata.
2. For up to 3 difficulties that exist: submit `mps.cpu` sampling jobs at
   chi ∈ {16, 64, 256}, 20k shots each; record wall minutes (queue+run) and
   PPL (peak-proximity lift) vs the known key.
3. One `pauli-path` observable job (Z-string, threshold 1e-5) for lane-B timing.

**Decision rule (preregistered)**:
- If NO attack job completes ≤5 min → shrink size/depth before freezing
  (G2 must not proceed at this scale).
- PPL signal absent at all chi (no gradient for the flywheel to climb on lane A)
  → lane A stays in the suite for the adversarial/cost story, but the primary
  optimization metric switches to the exact-truth lane C (documented in
  EXP-003/005 preregistration BEFORE round 1, not after seeing flywheel data).

**Cost plan**: ≤ 3 difficulties × 3 chi + 1 pauli-path ≈ 10 jobs, all $0
plan-included.
