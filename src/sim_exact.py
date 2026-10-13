"""Exact statevector ground truth for <=26q circuits (qiskit Statevector, numpy).

Deterministic, CPU-only, free. Used to score cloud sampler jobs (XEB, peak
probability). Bitstring convention: qiskit display order (MSB = q[n-1]).
"""

from __future__ import annotations

import pathlib

import numpy as np
from qiskit.quantum_info import Statevector


def statevector(qc) -> np.ndarray:
    """Exact statevector of a measurement-free qiskit circuit."""
    return np.asarray(Statevector.from_instruction(qc).data)


def probabilities(state: np.ndarray, bitstrings: list[str]) -> np.ndarray:
    """Ideal probabilities of qiskit-display-order bitstrings."""
    idx = [int(b.replace(" ", ""), 2) for b in bitstrings]
    return np.abs(state[idx]) ** 2


def probability_lookup(state: np.ndarray):
    """Return a callable bitstring -> ideal probability (for metrics.xeb_linear)."""
    n = int(np.log2(len(state)))

    def lookup(b: str) -> float:
        return float(abs(state[int(b, 2)]) ** 2)

    return lookup


def sample_counts(state: np.ndarray, shots: int, seed: int) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    p = np.abs(state) ** 2
    p = p / p.sum()
    draws = rng.choice(len(p), size=shots, p=p)
    counts: dict[str, int] = {}
    n = int(np.log2(len(p)))
    for d in draws:
        b = format(int(d), f"0{n}b")
        counts[b] = counts.get(b, 0) + 1
    return counts


def save_probabilities(qc, out_path) -> str:
    """Exact ideal probabilities as float32 .npy (26q = 268 MB) for mmap scoring."""
    import hashlib

    sv = statevector(qc)
    p = (np.abs(sv) ** 2).astype(np.float32)
    np.save(out_path, p)
    return hashlib.sha256(p.tobytes()).hexdigest()


def prob_lookup_from_file(path):
    """mmap-backed bitstring -> ideal probability lookup."""
    p = np.load(path, mmap_mode="r")

    def lookup(b: str) -> float:
        return float(p[int(b, 2)])

    return lookup


def _precompute_one(pair: tuple) -> str:
    """Module-level worker for mp.Pool (closures are not picklable)."""
    qpy_path, prob_path = pair
    if pathlib.Path(prob_path).exists():
        return prob_path
    from circuits import load_circuit

    qc = load_circuit(qpy_path)
    save_probabilities(qc, prob_path)
    return prob_path


def precompute_suite(job_args: list[tuple], workers: int = 8) -> None:
    """Parallel exact precompute. job_args = [(qpy_path, prob_path), ...]."""
    import multiprocessing as mp

    todo = [p for p in job_args if not pathlib.Path(p[1]).exists()]
    if not todo:
        return
    with mp.Pool(min(workers, len(todo))) as pool:
        pool.map(_precompute_one, todo)
