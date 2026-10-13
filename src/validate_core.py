"""Fast scientific-core validation (determinism, QPY, permutation semantics,
XEB/PPL sanity, exact-truth timing). No network. Run BEFORE any experiment.

Usage: .venv/bin/python -u src/validate_core.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from circuits import rcs_circuit, permuted, save_circuit, load_circuit, circuit_sha256
from sim_exact import statevector, sample_counts, save_probabilities
from metrics import xeb_linear, ppl, paired_delta, acceptance

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail else ''}", flush=True)
    if not cond:
        FAILURES.append(name)


def main() -> int:
    import numpy as np

    # 1. determinism + explicit names under global-circuit-counter interference
    a1 = circuit_sha256(rcs_circuit(12, 4, seed=99))
    rcs_circuit(6, 2, seed=1)  # noise: builds other circuits in between
    a2 = circuit_sha256(rcs_circuit(12, 4, seed=99))
    check("rcs determinism (QPY bytes)", a1 == a2, a1[:12])

    # 2. QPY round-trip preserves the state exactly
    qc = rcs_circuit(12, 4, seed=99)
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "c.qpy"
        save_circuit(qc, p)
        qc2 = load_circuit(p)
        sv_a, sv_b = statevector(qc), statevector(qc2)
        same_sv = np.allclose(sv_a, sv_b, atol=1e-12)
    check("QPY round-trip statevector identical", same_sv)

    # 3. permutation semantics: logical L lives at site p[L]
    n = 8
    qc8 = rcs_circuit(n, 4, seed=7)
    perm = [5, 0, 3, 7, 1, 6, 2, 4]
    sv_o = statevector(qc8)
    sv_p = statevector(permuted(qc8, perm))
    # index maps: site index b -> logical index x with x_L = b_{p[L]}
    idx = np.arange(2**n)
    bits = ((idx[:, None] >> np.arange(n)[None, :]) & 1)  # bits[i, q] = qubit q of i
    x = np.zeros(2**n, dtype=np.int64)
    for L in range(n):
        x |= bits[:, perm[L]] << L
    check("permuted() amplitude mapping", np.allclose(sv_p, sv_o[x]),
          "site p[L] carries logical qubit L")

    # 4. XEB sanity on a 12q circuit: exact sampler -> ~1, uniform -> ~0
    #    (normalized by the per-circuit exact-sampler constant — shallow RCS
    #    circuits are pre-Porter-Thomas, raw exact XEB > 1 there)
    from metrics import xeb_normalized, xeb_ideal_constant
    qc12 = rcs_circuit(12, 6, seed=5)
    sv = statevector(qc12)
    p = np.abs(sv) ** 2
    p = p / p.sum()
    exact_counts = sample_counts(sv, shots=5000, seed=42)
    lookup = {format(i, "012b"): float(v) for i, v in enumerate(p)}
    xeb_exact = xeb_normalized(exact_counts, p)
    rng = np.random.default_rng(3)
    uni_counts: dict[str, int] = {}
    for _ in range(5000):
        b = format(int(rng.integers(4096)), "012b")
        uni_counts[b] = uni_counts.get(b, 0) + 1
    xeb_uni = xeb_normalized(uni_counts, p)
    check("XEB(exact sampler) ~ 1", 0.85 < xeb_exact < 1.15,
          f"{xeb_exact:.4f} (raw const {xeb_ideal_constant(p):.3f})")
    check("XEB(uniform sampler) ~ 0", -0.1 < xeb_uni < 0.1, f"{xeb_uni:.4f}")

    # 5. PPL sanity on a synthetic peaked distribution (no qiskit needed)
    key = "101101001011"  # 12 bits
    peak_p = {key: 0.5}
    rngp = np.random.default_rng(9)
    pool = [key] * 2500
    others = [format(int(i), "012b") for i in rngp.integers(0, 4096, 2500)]
    pool += list(others)
    peaked_counts: dict[str, int] = {}
    for b in pool:
        peaked_counts[b] = peaked_counts.get(b, 0) + 1
    ppl_peaked = ppl(peaked_counts, key)
    ppl_uni = ppl(uni_counts, key)
    check("PPL(peaked 0.5) ~ 0.5", 0.3 < ppl_peaked < 0.7, f"{ppl_peaked:.4f}")
    check("PPL(uniform) ~ 0", -0.05 < ppl_uni < 0.05, f"{ppl_uni:.4f}")

    # 6. acceptance gate arithmetic
    d_pos = paired_delta([0.02] * 10 + [0.04] * 10)
    d_neg = paired_delta([0.01] * 10 + [-0.01] * 10)
    acc = acceptance(d_pos, min_delta=0.01, cost_ratio=1.01)
    rej = acceptance(d_neg, min_delta=0.01, cost_ratio=1.01)
    costly = acceptance(d_pos, min_delta=0.01, cost_ratio=1.03)
    check("acceptance accepts clean win", acc["accepted"] and acc["ci_excludes_null"])
    check("acceptance rejects zero effect", not rej["accepted"])
    check("acceptance rejects 3% cost regression", not costly["accepted"])

    # 7. exact-truth timing at G1's smallest size (single worker)
    t0 = time.time()
    qc20 = rcs_circuit(20, 8, seed=11)
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "p20.npy"
        sha = save_probabilities(qc20, f)
        arr = np.load(f, mmap_mode="r")
        ok_mmap = float(arr[int("10101010101010101010", 2)]) > 0
    dt_s = time.time() - t0
    check("20q d=8 exact truth < 240 s", dt_s < 240, f"{dt_s:.1f}s sha={sha[:10]}")
    check("mmap probability lookup works", ok_mmap)

    # 8. joint site-permutation EV invariance (Lane Q scoring basis: permuted
    #    circuit + identically transformed observable => same exact EV)
    from circuits import permute_pauli_label
    from qiskit.quantum_info import SparsePauliOp, Statevector
    n16, d16, s16 = 16, 8, 20269901
    lab = ["I"] * n16
    for s, c in zip((1, 4, 7, 10, 13, 15), ("X", "Y", "Z", "Y", "X", "Z")):
        lab[s] = c
    lab16 = "".join(lab)
    qc16 = rcs_circuit(n16, d16, seed=s16)
    ev0 = float(Statevector.from_instruction(qc16).expectation_value(
        SparsePauliOp(lab16)).real)
    pi16 = list(np.random.default_rng(42).permutation(n16))
    ev1 = float(Statevector.from_instruction(
        permuted(qc16, pi16)).expectation_value(
        SparsePauliOp(permute_pauli_label(lab16, pi16))).real)
    check("joint permutation EV invariance", abs(ev1 - ev0) < 1e-9,
          f"|d|={abs(ev1 - ev0):.1e}")

    print(flush=True)
    if FAILURES:
        print(f"VALIDATION FAILED: {FAILURES}", flush=True)
        return 1
    print("ALL CORE CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
