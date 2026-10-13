"""Reproduce + fix-verify the permutation scoring bug (2026-10-06, G4 r4).

Symptom (runs/flywheel/*_r4, EXP-005-R04): permutation seed 11 collapsed
normalized XEB to ~0.00-0.07 on ALL val circuits including trivially-easy
n20 d8 (incumbent ~1.0) — impossible for a pure relabeling at fixed chi.

Root cause: after canonical_counts(), count keys are in qiskit DISPLAY order
(leftmost char = clbit n-1 = site n-1). permute_bitstring(k, inv) scatters in
string-POSITION space as if position i were site i, but position i = site
n-1-i; reversal does not commute with the permutation, so the gather uses the
wrong mapping whenever pi is not reversal-symmetric.

This script, on one n=20 d=8 val circuit (exact local statevectors, $0):
  A. score the exact UNPERMUTED sampler vs truth           -> ~1.0 (sanity)
  B. score the exact PERMUTED sampler via the OLD unpermute -> ~0.x (bug)
  C. score the exact PERMUTED sampler via the NEW unpermute -> ~A (fix ok)
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from circuits import rcs_circuit, load_circuit  # noqa: E402
from harness import perm_of, inv_perm, permute_bitstring, unpermute_key  # noqa: E402
from metrics import xeb_linear, xeb_ideal_constant  # noqa: E402

SEED = 20263180  # rcs_n20_d8_s20263180 — a val circuit whose truth we can recompute
PERM_SEED = 11   # the exact mutation value from r4


def main() -> int:
    man_circ = next(c for c in load_manifest() if str(SEED) in c["id"])
    qc = load_circuit(ROOT / "suite" / man_circ["qpy"])
    n = qc.num_qubits

    from qiskit.quantum_info import Statevector
    p_truth = np.abs(Statevector.from_instruction(qc).data) ** 2
    const = xeb_ideal_constant(p_truth)
    truth_disp = {format(i, f"0{n}b"): float(p_truth[i]) for i in range(2 ** n)}

    pi = perm_of(n, PERM_SEED)
    inv = inv_perm(pi)
    from circuits import permuted
    qc_perm = permuted(qc, pi)
    p_perm = np.abs(Statevector.from_instruction(qc_perm).data) ** 2

    # exact-sampler "counts": use the full distribution once (weights=p)
    def score(key_map, probs=None) -> float:
        pr = p_perm if probs is None else probs
        counts = {key_map(format(i, f"0{n}b")): float(pr[i])
                  for i in range(2 ** n)}
        return xeb_linear(counts, truth_disp) / const

    a = score(lambda k: k, probs=p_truth)                  # unpermuted exact vs truth (sanity)
    b = score(lambda k: permute_bitstring(k, inv))         # OLD path
    c = score(lambda k: unpermute_key(k, pi))              # NEW path
    print(f"A unpermuted identity      : {a:.4f}")
    print(f"B permuted, OLD unpermute   : {b:.4f}   <- should be broken (~0)")
    print(f"C permuted, NEW unpermute   : {c:.4f}   <- should be ~A")
    ok = a > 0.9 and b < 0.5 and abs(c - a) < 0.05
    print("VERDICT:", "bug reproduced + fix verified" if ok else "UNEXPECTED")
    return 0 if ok else 1


def load_manifest() -> list[dict]:
    import json
    man = json.loads((ROOT / "suite" / "MANIFEST.json").read_text())
    return man["circuits"]


if __name__ == "__main__":
    sys.exit(main())
