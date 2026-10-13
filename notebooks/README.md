# Evidence notebooks

Executed notebooks: an outside check of our prototype campaign (01–04) and a laptop-scale peaked-circuit attack
rehearsal (05). Outputs are embedded, so they render on GitHub as-is. **No API key, no cloud jobs**: everything runs
on a laptop CPU from the hash-verified data bundle in `data/` and from code in this folder. Every result is computed
in the notebook; numbers in prose restate an output or quote a cited source. 01, 03, 04 and 05 end with a checks
cell; 02 asserts its reproduction of the preregistered calibration inline.

**Start here.** If you review for Track 2, open `05_peaked_circuits` first. It builds small Aaronson–Zhang-style
peaked circuits of our own (not BlueQubit's challenge circuits), measures what a truncated-MPS attack needs to recover
the hidden string, and shows where that cheap attack stops (all-to-all gates). Then the two method notebooks:
`04_pauli_paths` (where Pauli propagation works, and why it returned zeros on random circuits) and `03_layout_damage`
(an independent MPS against the cloud runs, and XEB overstating fidelity). `01_campaign_audit` and `02_gate_power`
recompute the prototype campaign's numbers and size the scale-up's decision gate.

| notebook | question | runtime |
|---|---|---|
| [`05_peaked_circuits`](05_peaked_circuits.ipynb) | Build small peaked circuits (the sponsor's advantage genre) and measure what a truncated-MPS attack needs to recover the peak, and where that stops working | ~10 min |
| [`04_pauli_paths`](04_pauli_paths.ipynb) | Why did the cloud `pauli-path` probe return exactly 0, and where do Pauli paths work? | ~2 min |
| [`03_layout_damage`](03_layout_damage.ipynb) | Is the permutation collapse real physics? Is linear XEB a sound fidelity proxy for a truncated simulator? | ~7 min |
| [`01_campaign_audit`](01_campaign_audit.ipynb) | Does every headline number of the campaign follow, by the preregistered rules, from the ledgered per-circuit data? | < 1 min |
| [`02_gate_power`](02_gate_power.ipynb) | Why were the flywheel's three near-misses rejected, and how many circuits must a decision use at scale? | ~1.5 min |

## What they show

- **05 · Peaked circuits (11/11 checks pass).** Environment sweeps (`peaked_lite.py`) reach an average peak of 0.186
  at Aaronson–Zhang's 12-qubit layer counts (they report ≈ 0.2 with a different optimiser, arXiv:2404.14493). On 12-
  and 16-qubit 1D circuits in the non-trivial regime (random part deeper than the peaking part), a bond-limited MPS
  attack that never sees the hidden string recovered it at χ = 4–16, while faithful simulation (F ≥ 0.99) needed the
  full exact bond dimension in 12 of 12 instances. It succeeded at fidelities down to 1.7·10⁻³. An attacker-side
  stopping rule (top candidate unchanged from χ to 2χ) reported the right string in 24 of 24 instances. In 83% of 142
  lossy runs the truncated state kept more peak weight than a depolarized state of equal fidelity, and in 67 it
  exceeded the exact peak. **Where it stops:** with all-to-all gates (random matchings; BlueQubit's circuits are
  all-to-all) the recovering χ was a median 1.00 of the exact χ at 16 qubits, against 0.023 in 1D, and reordering by
  gate distance did not bring the advantage back. Kremer & Dupuis's attack on BlueQubit's circuits (arXiv:2604.21908)
  exploits the construction's mirrored structure instead. A static wire relabeling (a deliberately weak toy version of
  the hiding in arXiv:2510.25838) is undone by reading the chain off the gate list. Scope: our own circuits at ≤ 16
  qubits, exactly simulable. This is a protocol rehearsal, not a claim about BlueQubit's challenge circuits.
- **04 · Pauli paths (8/8 checks pass).** An independent numpy Pauli-propagation simulator (`pauli_lite.py`, exact
  against statevectors to 3.3e-16) regenerates the campaign's 20-qubit probe and its recorded exact value
  (−0.001112). At ε = 10⁻³ every term is truncated after 54 of 236 gates and the estimate is exactly 0.0, as the
  cloud returned; smaller ε explodes the term count. The probed observable could not test any approximate method,
  because returning 0 already had error 0.0011. On a 19-qubit heavy-hex analogue of IBM's kicked-Ising circuits the
  same code is accurate to 0.0051 after 5 steps. After 20 steps it exceeds the laptop's term budget at 4 of 9 angles
  and errs by up to 0.0421 elsewhere. A cheap self-check gate (ε-convergence + retained norm) refuses the campaign
  probe but makes one false acceptance (error 0.0421), so Pauli-path verdicts need a gate calibrated against exact
  answers.
- **03 · Layout damage (4/4 checks pass).** Regenerates the campaign's 20-qubit circuits from their seeds:
  circuits and exact-truth files are byte-identical to the frozen manifest (13/13). An independent 138-line numpy MPS
  (`mps_lite.py`) matches the cloud `mps.cpu` results within two shot-noise standard errors for 22 of 25 identity-
  layout pairs; permuted layouts agree in trend only (18 of 65 within 2 SE). Where truncation bites (F < 0.99),
  **normalized linear XEB overstates true fidelity** (median +0.078 for the identity layout, +0.476 under layout
  damage) and can exceed the exact sampler's 1. In the campaign's own cloud rows, 51 of 288 permuted-layout rows
  exceed 1.05 (max 2.134), against 0 of 72 identity-layout rows. Relevant to XEB-based claims (cf. arXiv:2005.02421,
  arXiv:2112.01657) and to what an automated attack loop should optimize.
- **01 · Audit (24/24 checks pass).** All 20 round decisions (paired bootstrap CI, cost ratio, verdict) recompute
  from the per-circuit rows (Δ and CI bit-for-bit, cost ratio to 1e-9), as do the holdout deltas and CIs, the
  frozen prediction, the job ledger (905 campaign jobs, $0.00 billed on the TEST account) and all 432 claim→job
  references. Every recorded `metrics.json` matches the hash the ledger pinned at record time. Disclosed deviation:
  28 of 31 PREREGISTRATION files match their pins, and the other three differ *only* in `frozen_at` (restoring it
  reproduces the pinned hash exactly). Re-running the bootstrap with 300 other seeds shows the campaign's single
  promotion survives in 81% of them: the arms' divergence was decided at the CI boundary.
- **02 · Gate power.** Reproduces EXP-008's preregistered calibration exactly (asserted), then maps the gate's power
  against the number of validation circuits. At 12 circuits the gate promotes an effect of the measured size about as
  often as a coin flip. Its no-effect false-promotion rate stays at or below 0.022. The flywheel's three near-miss
  rejections were a power problem; its other seven were not: four valid permutations lost heavily (the fifth is the
  invalid scoring-bug row), and two shot reallocations were cost-only changes a fidelity gate cannot promote except by
  noise. The power figures assume the
  frozen `min_delta`; the notebook shows why the scale-up must preregister the margin separately from the noise
  calibration. A depth-stratified gate is a candidate design, but it tests a weaker hypothesis (it increasingly
  promotes a change that helps hard circuits and slightly hurts easy ones as the budget grows), and it was designed on
  this data, so it must be confirmed on fresh circuits.

## Run them yourself

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/run_all.py            # re-executes 01–05 in place; fails if any check fails
```

`tools/build_bundle.py --tree <campaign tree> --label <name>` rebuilds `data/<name>/` from a campaign directory:
byte-for-byte copies of the report, ledger, per-round `metrics.json`, EXP-008 analysis and suite manifest, plus
`PROVENANCE.json` (sha256 of every file). The notebooks refuse to run if any bundled file changed.

## Files

- `nbcommon.py`: bundle loader with hash verification, the campaign's bootstrap rule (line-for-line from
  `src/metrics.py`), the gate rule, and the shared figure style.
- `mps_lite.py`: independent MPS simulator (mixed-canonical, SWAP routing, SVD truncation); exact at sufficient χ
  (checked in notebooks 03 and 05).
- `pauli_lite.py`: independent Pauli-propagation simulator (Heisenberg picture, Pauli transfer matrices, coefficient
  truncation, retained-norm and discarded-mass diagnostics); exact at ε = 0 (checked in notebook 04).
- `peaked_lite.py`: peaked-circuit construction (Haar brickwork, environment-sweep peaking optimiser, dense
  statevector checked against qiskit) and the MPS attack (exact sampling and O(nχ²) amplitudes from an `mps_lite`
  MPS); checked in notebook 05.
- `data/test-campaign/`: evidence of the TEST-account campaign (closed 2026-10-07) and EXP-008.
