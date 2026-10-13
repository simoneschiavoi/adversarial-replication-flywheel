# DIRECTION.md — judgment records, abandoned paths, wake conditions

## Journal

- 2026-10-06 (boot): suite metric chosen = peak-proximity lift (PPL) on
  BlueQubit peaked circuits (server-minted via `get_peaked_circuit`, known
  peak key) — scoreable at any qubit count without ideal probabilities;
  validated against exact local statevector truth on the ≤26q sub-suite.
  XEB fidelity reserved for the tutorial baseline (G1) where exact truth
  exists. Reason: exact XEB is intractable at 30–56q; a proxy validated
  against exact truth at small n is the honest design.
- 2026-10-06 (boot): attack backend lane = mps.cpu (χ ≤ 2048, shots ≤ 1M).
  pauli-path lane is an observable estimator, not a sampler — cut to stretch
  (matches the preregistered cut order: "second backend lane").

## Abandoned paths

- (none yet)

## Wake conditions

- If get_peaked_circuit difficulties do not span 30–56q → mint self-seeded
  peaked circuits via the same construction locally (still sha-pinned).
- If mps.cpu attack jobs exceed the 5-min envelope at 30+q → shrink depth/χ
  BEFORE freezing (G1.5 gate), never after.
