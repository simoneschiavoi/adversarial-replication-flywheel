"""A small, independent matrix-product-state simulator (numpy only).

Written for the evidence notebooks to cross-check cloud `mps.cpu` results
locally. It shares no code with the campaign harness. Scope: circuits of
1-qubit and 2-qubit gates on a 1D chain, qubit k at chain site k.

- Mixed-canonical MPS with a movable orthogonality centre, so every SVD
  truncation is the locally optimal (largest-singular-value) one.
- Two-qubit gates on non-adjacent sites are routed with SWAP chains (move one
  qubit next to the other, apply, move back); every SWAP is itself truncated
  to the bond limit chi -- the mechanism by which a bad qubit-to-site layout
  costs fidelity at fixed chi.
- to_statevector() contracts the MPS to a dense vector in qiskit index order
  (index = sum_k bit_k * 2**k) for exact scoring at <= ~22 qubits.

The only qiskit-specific piece is gates_from_qiskit(), which converts a qiskit
circuit into (matrix, qubits) pairs.
"""

from __future__ import annotations

import numpy as np

SWAP = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex)


def gates_from_qiskit(qc):
    """List of (matrix, qubits). 2q matrices are in qiskit's little-endian
    convention: basis index = bit(q0) + 2*bit(q1) for qubits (q0, q1)."""
    out = []
    for inst in qc.data:
        qs = tuple(qc.find_bit(q).index for q in inst.qubits)
        if inst.operation.name in ("measure", "barrier"):
            continue
        out.append((np.asarray(inst.operation.to_matrix(), dtype=complex), qs))
    return out


class MPS:
    def __init__(self, n: int, chi: int, cutoff: float = 1e-14):
        self.n, self.chi, self.cutoff = n, chi, cutoff
        self.A = []
        for _ in range(n):
            t = np.zeros((1, 2, 1), dtype=complex)
            t[0, 0, 0] = 1.0
            self.A.append(t)
        self.center = 0
        self.discarded = 0.0       # sum of discarded squared singular values (normalized state)
        self.max_bond = 1
        self.n_svd = 0

    # ---- canonical-form bookkeeping
    def _move_center(self, target: int) -> None:
        while self.center < target:
            k = self.center
            a = self.A[k]
            l, d, r = a.shape
            q, rr = np.linalg.qr(a.reshape(l * d, r))
            self.A[k] = q.reshape(l, d, -1)
            self.A[k + 1] = np.tensordot(rr, self.A[k + 1], axes=(1, 0))
            self.center += 1
        while self.center > target:
            k = self.center
            a = self.A[k]
            l, d, r = a.shape
            q, rr = np.linalg.qr(a.reshape(l, d * r).T)
            self.A[k] = q.T.reshape(-1, d, r)
            self.A[k - 1] = np.tensordot(self.A[k - 1], rr.T, axes=(2, 0))
            self.center -= 1

    # ---- gates
    def apply_1q(self, u: np.ndarray, k: int) -> None:
        self.A[k] = np.einsum("ij,ljr->lir", u, self.A[k])

    def _apply_adjacent(self, g4: np.ndarray, i: int, center_right: bool) -> None:
        """g4 is (2,2,2,2) [out_i, out_i1, in_i, in_i1] on sites (i, i+1)."""
        self._move_center(i)
        a, b = self.A[i], self.A[i + 1]
        l, r = a.shape[0], b.shape[2]
        theta = np.tensordot(a, b, axes=(2, 0))                       # l,2,2,r
        theta = np.tensordot(g4, theta, axes=([2, 3], [1, 2]))        # 2,2,l,r
        theta = theta.transpose(2, 0, 1, 3).reshape(l * 2, 2 * r)
        u, s, vh = np.linalg.svd(theta, full_matrices=False)
        self.n_svd += 1
        norm2 = float(np.sum(s ** 2))
        keep = int(min(self.chi, np.sum(s > self.cutoff * s[0])))
        self.discarded += float(np.sum(s[keep:] ** 2)) / norm2
        u, s, vh = u[:, :keep], s[:keep] / np.sqrt(np.sum(s[:keep] ** 2)), vh[:keep]
        self.max_bond = max(self.max_bond, keep)
        if center_right:
            self.A[i] = u.reshape(l, 2, keep)
            self.A[i + 1] = (s[:, None] * vh).reshape(keep, 2, r)
            self.center = i + 1
        else:
            self.A[i] = (u * s[None, :]).reshape(l, 2, keep)
            self.A[i + 1] = vh.reshape(keep, 2, r)
            self.center = i

    @staticmethod
    def _site_tensor(g: np.ndarray, qa_left: bool) -> np.ndarray:
        """qiskit little-endian 4x4 on (qa, qb) -> (2,2,2,2) on (left, right) sites."""
        t = g.reshape(2, 2, 2, 2)              # [out_b, out_a, in_b, in_a]
        return t.transpose(1, 0, 3, 2) if qa_left else t

    def apply_2q(self, g: np.ndarray, qa: int, qb: int) -> None:
        i, j = min(qa, qb), max(qa, qb)
        swap4 = SWAP.reshape(2, 2, 2, 2)
        for k in range(j - 1, i, -1):          # bring site j next to i
            self._apply_adjacent(swap4, k, center_right=False)
        self._apply_adjacent(self._site_tensor(g, qa_left=(qa == i)), i, center_right=True)
        for k in range(i + 1, j):              # move it back
            self._apply_adjacent(swap4, k, center_right=True)

    def run(self, gates) -> "MPS":
        for m, qs in gates:
            if len(qs) == 1:
                self.apply_1q(m, qs[0])
            else:
                self.apply_2q(m, qs[0], qs[1])
        return self

    # ---- readout
    def to_statevector(self) -> np.ndarray:
        """Dense vector, qiskit index order (bit of qubit k has weight 2**k)."""
        psi = self.A[0].reshape(2, -1)
        for k in range(1, self.n):
            a = self.A[k]
            psi = (psi @ a.reshape(a.shape[0], -1)).reshape(-1, a.shape[2])
        psi = psi.reshape([2] * self.n)        # axes = sites 0..n-1, site 0 most significant
        psi = psi.transpose(list(range(self.n))[::-1]).reshape(-1)
        return psi / np.linalg.norm(psi)


def normalized_xeb(p_model: np.ndarray, p_ideal: np.ndarray) -> float:
    """Infinite-shot normalized linear XEB of a sampler with distribution p_model:
    (2^n sum p_model p_ideal - 1) / (2^n sum p_ideal^2 - 1); exact sampler -> 1."""
    N = len(p_ideal)
    return float((N * np.dot(p_model, p_ideal) - 1.0) / (N * np.dot(p_ideal, p_ideal) - 1.0))
