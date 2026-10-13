"""Peaked circuits at laptop scale: construction and an MPS peak-finding attack (numpy only).

Construction (in the spirit of Aaronson & Zhang's peaked circuits): a random 1D
brickwork R of Haar two-qubit gates, followed by a "peaking" brickwork P whose
gates are optimised so that the full circuit C = P R sends |0...0> to a hidden
bitstring s with large probability (the "peak weight" |<s|C|0>|^2).

Optimiser: exact environment sweeps. For one gate G of P with everything else
fixed, the amplitude is <s|C|0> = Tr(G E) with E the 4x4 environment; the
unitary maximising |Tr(G E)| is G = Y X^dagger for E = X S Y^dagger (SVD), and the
new amplitude is the nuclear norm sum(S). Each update can only raise the peak
weight, so a sweep is monotone.

Attack: simulate C with a bond-limited MPS (mps_lite.MPS), draw samples from the
truncated state, and keep the sampled bitstring whose MPS amplitude is largest.
Sampling and amplitudes cost O(n chi^2) each -- no dense vectors are needed.

Conventions follow mps_lite / qiskit: a gate is (4x4 matrix, (qa, qb)) with
basis index bit(qa) + 2*bit(qb); statevector index = sum_k bit_k * 2**k.
"""

from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------- circuits
def haar_u4(rng: np.random.Generator) -> np.ndarray:
    z = (rng.normal(size=(4, 4)) + 1j * rng.normal(size=(4, 4))) / np.sqrt(2)
    q, r = np.linalg.qr(z)
    return q * (np.diag(r) / np.abs(np.diag(r)))[None, :]


def layer_pairs(n: int, layer: int) -> list[tuple[int, int]]:
    start = layer % 2
    return [(q, q + 1) for q in range(start, n - 1, 2)]


def brickwork(n: int, depth: int, rng: np.random.Generator, first_layer: int = 0):
    """Gate list of a depth-`depth` 1D brickwork of Haar gates."""
    return [(haar_u4(rng), p) for d in range(depth) for p in layer_pairs(n, first_layer + d)]


def to_qiskit(n: int, gates):
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import UnitaryGate
    qc = QuantumCircuit(n)
    for g, (a, b) in gates:
        qc.append(UnitaryGate(g, check_input=False), [a, b])
    return qc


# ---------------------------------------------------------------- dense statevector (n <= 20)
def zero_state(n: int) -> np.ndarray:
    psi = np.zeros(2 ** n, dtype=complex)
    psi[0] = 1.0
    return psi


def basis_state(n: int, s: str) -> np.ndarray:
    """|s> with s written q0 first (s[k] = bit of qubit k)."""
    psi = np.zeros(2 ** n, dtype=complex)
    psi[sum(int(c) << k for k, c in enumerate(s))] = 1.0
    return psi


def _front(psi: np.ndarray, n: int, a: int, b: int) -> np.ndarray:
    """View psi as (4, rest) with row index bit(a) + 2*bit(b)."""
    t = psi.reshape([2] * n)
    return np.moveaxis(t, [n - 1 - b, n - 1 - a], [0, 1]).reshape(4, -1)


def _back(m: np.ndarray, n: int, a: int, b: int) -> np.ndarray:
    t = m.reshape([2] * n)
    return np.moveaxis(t, [0, 1], [n - 1 - b, n - 1 - a]).reshape(-1)


def apply(psi: np.ndarray, n: int, g: np.ndarray, a: int, b: int) -> np.ndarray:
    return _back(g @ _front(psi, n, a, b), n, a, b)


def run(psi: np.ndarray, n: int, gates) -> np.ndarray:
    for g, (a, b) in gates:
        psi = apply(psi, n, g, a, b)
    return psi


# ---------------------------------------------------------------- peaking optimiser
def optimise_peak(n: int, rand_gates, peak_gates, s: str, sweeps: int = 30, tol: float = 1e-10):
    """Environment-sweep the gates of `peak_gates` (modified copy returned) to
    maximise |<s| P R |0>|^2. Returns (gates, history of peak weight per sweep)."""
    P = [(g.copy(), q) for g, q in peak_gates]
    psi0 = run(zero_state(n), n, rand_gates)
    target = basis_state(n, s)
    hist = [float(abs(np.vdot(target, run(psi0, n, P))) ** 2)]
    m = len(P)
    for _ in range(sweeps):
        phis = [None] * m                   # phis[k] = (G_{k+1} ... G_{m-1})^dagger |s>
        phi = target
        for k in range(m - 1, -1, -1):
            phis[k] = phi
            g, (a, b) = P[k]
            phi = apply(phi, n, g.conj().T, a, b)
        psi = psi0
        for k in range(m):
            _, (a, b) = P[k]
            env = _front(psi, n, a, b) @ _front(phis[k], n, a, b).conj().T   # E[in, out]
            x, _, yh = np.linalg.svd(env)
            g = yh.conj().T @ x.conj().T                                     # argmax |Tr(G E)|
            P[k] = (g, (a, b))
            psi = apply(psi, n, g, a, b)
        hist.append(float(abs(np.vdot(target, psi)) ** 2))
        if hist[-1] - hist[-2] < tol:
            break
    return P, hist


# ---------------------------------------------------------------- MPS readout (scalable)
def mps_amplitude(mps, s: str) -> complex:
    """<s|psi_mps>, O(n chi^2)."""
    v = np.ones(1, dtype=complex)
    for k, c in enumerate(s):
        v = v @ mps.A[k][:, int(c), :]
    return complex(v[0])


def mps_sample(mps, shots: int, rng: np.random.Generator) -> list[str]:
    """Exact sampling from the (normalised) MPS state, vectorised over shots."""
    mps._move_center(0)                     # sites 1..n-1 right-canonical
    a0 = mps.A[0]
    nrm = np.sqrt(np.sum(np.abs(a0) ** 2))
    v = np.ones((shots, 1), dtype=complex)
    bits = np.zeros((shots, mps.n), dtype=np.int8)
    for k in range(mps.n):
        a = mps.A[k] / (nrm if k == 0 else 1.0)
        w = np.einsum("sl,ldr->sdr", v, a)
        p = np.sum(np.abs(w) ** 2, axis=2)
        p /= p.sum(axis=1, keepdims=True)
        d = (rng.random(shots) < p[:, 1]).astype(np.int8)
        bits[:, k] = d
        v = w[np.arange(shots), d, :]
        v /= np.linalg.norm(v, axis=1, keepdims=True)
    return ["".join(map(str, row)) for row in bits]


def mps_attack(mps, shots: int, rng: np.random.Generator):
    """Sample, then return the sampled bitstring with the largest |MPS amplitude|^2
    and that value. Uses only the MPS (no dense vector, no knowledge of s)."""
    cands = set(mps_sample(mps, shots, rng))
    scored = [(abs(mps_amplitude(mps, x)) ** 2, x) for x in cands]
    w, best = max(scored)
    return best, float(w), len(cands)
