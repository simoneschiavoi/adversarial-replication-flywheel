"""A small, independent Pauli-propagation ("Pauli path") simulator (numpy only).

Written for the evidence notebooks to explain the campaign's `pauli-path`
probes locally. It shares no code with the campaign harness or with BlueQubit's
service; it is a textbook Heisenberg-picture method, so it shows the *regimes*
of the technique, not the internals of any particular implementation.

- An observable is a real linear combination of Hermitian Pauli strings
  O = sum_s c_s P_s, stored as two arrays: uint64 keys and float64 coefficients.
  Qubit q has its X bit at position q and its Z bit at position 32 + q
  (single-qubit code: I=0, X=1, Z=2, Y=3), so n <= 32.
- Gates are applied in reverse circuit order, O -> G^dag O G, through each
  gate's Pauli transfer matrix M[a, b] = Tr(P_a G^dag P_b G) / 2^k (k = 1, 2).
  Clifford gates permute strings; non-Clifford gates branch them.
- After every gate equal strings are merged and terms with |c| < eps are
  dropped (coefficient truncation). eps = 0 is exact.
- <0...0| O |0...0> = sum of coefficients of strings with no X/Y component.

Diagnostics returned with every run: peak number of terms, the retained
squared norm sum c^2 (exactly conserved without truncation, so its loss
measures how much of the observable was thrown away), and the discarded L1
mass sum |c| over every truncated term, which bounds the absolute error of
the estimate (each dropped term c P contributes c <psi|V^dag P V|psi>, at most
|c| in magnitude, to the exact value).
"""

from __future__ import annotations

import time

import numpy as np

_P = [np.eye(2), np.array([[0, 1], [1, 0]]), np.array([[1, 0], [0, -1]]),
      np.array([[0, -1j], [1j, 0]])]                      # codes I, X, Z, Y


def _pauli_2q(b: int) -> np.ndarray:
    """Local index b = code(q_first) + 4 * code(q_second) -> 4x4 matrix in
    qiskit's little-endian order (basis index = bit(q_first) + 2 bit(q_second))."""
    return np.kron(_P[b // 4], _P[b % 4])


def ptm(u: np.ndarray) -> np.ndarray:
    """Heisenberg Pauli transfer matrix: u^dag P_b u = sum_a M[a, b] P_a."""
    u = np.asarray(u, dtype=complex)
    k = 1 if u.shape[0] == 2 else 2
    basis = _P if k == 1 else [_pauli_2q(b) for b in range(16)]
    m = np.empty((len(basis), len(basis)))
    for b, pb in enumerate(basis):
        h = u.conj().T @ pb @ u
        for a, pa in enumerate(basis):
            m[a, b] = np.real(np.trace(pa @ h)) / 2 ** k
    m[np.abs(m) < 1e-13] = 0.0
    return m


def _local_bits(code: int, q: int) -> int:
    return ((code & 1) << q) | ((code >> 1) << (32 + q))


def _code(keys: np.ndarray, q: int) -> np.ndarray:
    return ((keys >> np.uint64(q)) & np.uint64(1)) | (((keys >> np.uint64(32 + q)) & np.uint64(1)) << np.uint64(1))


def pauli_string(label: dict) -> int:
    """{qubit: 'X'|'Y'|'Z'} -> key."""
    key = 0
    for q, ch in label.items():
        key |= _local_bits({"X": 1, "Z": 2, "Y": 3}[ch], q)
    return key


def from_qiskit_label(label: str) -> int:
    """qiskit Pauli label (rightmost character = qubit 0) -> key."""
    return pauli_string({q: ch for q, ch in enumerate(reversed(label)) if ch != "I"})


def _apply(keys, coefs, m, qs):
    if len(qs) == 1:
        c = _code(keys, qs[0]).astype(np.int64)
        clear = np.uint64(~(_local_bits(3, qs[0])) & 0xFFFFFFFFFFFFFFFF)
        bits = [np.uint64(_local_bits(a, qs[0])) for a in range(4)]
    else:
        q1, q2 = qs
        c = (_code(keys, q1) + (_code(keys, q2) << np.uint64(2))).astype(np.int64)
        clear = np.uint64(~(_local_bits(3, q1) | _local_bits(3, q2)) & 0xFFFFFFFFFFFFFFFF)
        bits = [np.uint64(_local_bits(a % 4, q1) | _local_bits(a // 4, q2)) for a in range(16)]
    base = keys & clear
    out_k, out_c = [], []
    for b in np.unique(c):
        sel = c == b
        col = m[:, b]
        for a in np.nonzero(col)[0]:
            out_k.append(base[sel] | bits[a])
            out_c.append(coefs[sel] * col[a])
    k = np.concatenate(out_k)
    v = np.concatenate(out_c)
    uk, inv = np.unique(k, return_inverse=True)
    return uk, np.bincount(inv, weights=v, minlength=len(uk))


def propagate(gates, observable: dict, eps: float = 0.0, max_terms: int = 1_000_000,
              ptm_cache: dict | None = None, trace: bool = False) -> dict:
    """Heisenberg-propagate `observable` ({key: coef}) through `gates`
    [(matrix, qubits), ...] (circuit order) and return <0^n|U^dag O U|0^n>.

    Raises nothing on overflow: if the number of terms after a gate exceeds
    max_terms the run stops and status = 'over_cap' (the analogue of a
    service refusing a truncation threshold as a memory risk).
    trace=True also returns per-gate (terms, max |c|) after truncation."""
    t0 = time.time()
    keys = np.array(list(observable.keys()), dtype=np.uint64)
    coefs = np.array(list(observable.values()), dtype=float)
    norm0 = float(np.sum(coefs ** 2))
    peak, l1_dropped, status, done = len(keys), 0.0, "ok", 0
    cache = {} if ptm_cache is None else ptm_cache
    tr = []
    for g, qs in reversed(gates):
        if len(keys) == 0:
            break
        key = (g.tobytes(), len(qs))
        if key not in cache:
            cache[key] = ptm(g)
        keys, coefs = _apply(keys, coefs, cache[key], qs)
        if eps > 0:
            drop = np.abs(coefs) < eps
            l1_dropped += float(np.sum(np.abs(coefs[drop])))
            keys, coefs = keys[~drop], coefs[~drop]
        else:
            nz = coefs != 0.0
            keys, coefs = keys[nz], coefs[nz]
        peak = max(peak, len(keys))
        done += 1
        if trace:
            tr.append((len(keys), float(np.max(np.abs(coefs))) if len(keys) else 0.0))
        if len(keys) > max_terms:
            status = "over_cap"
            break
    zmask = np.uint64(0xFFFFFFFF)
    ev = float(np.sum(coefs[(keys & zmask) == 0])) if status == "ok" else float("nan")
    out = {"ev": ev, "status": status, "terms_final": int(len(keys)), "terms_peak": int(peak),
           "norm_retained": float(np.sum(coefs ** 2)) / norm0 if status == "ok" else float("nan"),
           "l1_dropped": l1_dropped, "gates_done": done, "gates_total": len(gates),
           "seconds": time.time() - t0}
    if trace:
        out["trace"] = tr
    return out
