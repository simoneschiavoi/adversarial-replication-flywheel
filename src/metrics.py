"""Metrics: XEB fidelity, peak-proximity lift (PPL), bootstrap CIs, paired deltas.

All functions are deterministic given (counts, truth, seed). No LLM anywhere.
"""

from __future__ import annotations

import numpy as np


def counts_to_xy(counts: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """bitstrings (display order) and their frequencies."""
    items = [(b, c) for b, c in counts.items() if isinstance(c, (int, float)) and c > 0]
    bs = [b for b, _ in items]
    w = np.array([c for _, c in items], dtype=float)
    return bs, w


def canonical_counts(counts: dict[str, float], device: str) -> dict[str, float]:
    """Normalize device key conventions to canonical display order.

    Empirical finding (G1, 2026-10-06, jobs in runs/20261006T025115Z_g1):
    mps.cpu returns count keys bit-reversed relative to the cpu device and to
    qiskit display order — reversing restores normalized XEB to ~1.0 for a
    near-exact sampler. cpu-family keys are already canonical.
    """
    if device.startswith("mps"):
        return {k[::-1]: v for k, v in counts.items()}
    return counts


def xeb_linear(counts: dict[str, float], p_ideal: dict[str, float] | callable) -> float:
    """Linear XEB of a sampler: 2^n * E_x[p_ideal(x)] - 1  (1 = exact, 0 = uniform)."""
    bs, w = counts_to_xy(counts)
    n = len(bs[0])
    if callable(p_ideal):
        p = np.array([p_ideal(b) for b in bs])
    else:
        p = np.array([p_ideal.get(b, 0.0) for b in bs])
    total = w.sum()
    return float(2**n * np.dot(w, p) / total - 1.0)


def xeb_ideal_constant(p: np.ndarray) -> float:
    """XEB the EXACT sampler would score on this circuit: 2^n * sum(p^2) - 1.

    Equals 1 under Porter-Thomas convergence, but shallow random circuits sit
    above it (measured: d=2 -> ~8, d=12 -> ~1.3 at n=12-16). Normalizing by
    this per-circuit constant anchors exact = 1 at every depth.
    """
    q = np.asarray(p, dtype=np.float64)
    n = int(np.log2(len(q)))
    return float(2**n * float(np.dot(q, q)) - 1.0)


def xeb_normalized(counts: dict[str, float], p: np.ndarray) -> float:
    """Raw linear XEB divided by the exact-sampler constant (exact -> 1)."""
    const = xeb_ideal_constant(p)
    if const <= 1e-9:
        return float("nan")
    n = len(next(iter(counts)))
    idx = np.fromiter((int(b, 2) for b in counts), dtype=np.int64)
    w = np.fromiter(counts.values(), dtype=np.float64)
    q = np.asarray(p, dtype=np.float64)[idx]
    raw = float(2**n * np.dot(w, q) / w.sum() - 1.0)
    return raw / const


def hamming(b: str, key: str) -> int:
    return sum(1 for x, y in zip(b, key) if x != y)


def ppl(counts: dict[str, float], key: str) -> float:
    """Peak-proximity lift: (n/2 - E_x[d_H(x, key)]) / (n/2).

    0 for a uniform random sampler; 1 if every sample IS the key.
    Always computable from counts alone, at any qubit count.
    """
    bs, w = counts_to_xy(counts)
    n = len(key)
    d = np.array([hamming(b, key) for b in bs], dtype=float)
    ev = float(np.dot(w, d) / w.sum())
    return float((n / 2.0 - ev) / (n / 2.0))


def ppl_bootstrap_ci(counts: dict[str, float], key: str, n_boot: int = 2000,
                     seed: int = 7, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap CI for PPL by resampling the raw shots."""
    bs, w = counts_to_xy(counts)
    shots = int(round(w.sum()))
    n = len(key)
    pool = []
    for b, c in zip(bs, w):
        pool.extend([b] * int(c))
    if not pool:
        return (float("nan"), float("nan"))
    pool_arr = np.array([hamming(b, key) for b in pool])
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        d = rng.choice(pool_arr, size=shots, replace=True)
        stats[i] = (n / 2.0 - d.mean()) / (n / 2.0)
    return (float(np.quantile(stats, alpha / 2)),
            float(np.quantile(stats, 1 - alpha / 2)))


def xeb_bootstrap_ci(counts: dict[str, float], p_ideal, n_boot: int = 2000,
                     seed: int = 11, alpha: float = 0.05) -> tuple[float, float]:
    bs, w = counts_to_xy(counts)
    shots = int(round(w.sum()))
    n = len(bs[0])
    if callable(p_ideal):
        p = np.array([p_ideal(b) for b in bs])
    else:
        p = np.array([p_ideal.get(b, 0.0) for b in bs])
    pool = np.repeat(p, w.astype(int))
    if len(pool) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        ps = rng.choice(pool, size=shots, replace=True)
        stats[i] = 2**n * ps.mean() - 1.0
    return (float(np.quantile(stats, alpha / 2)),
            float(np.quantile(stats, 1 - alpha / 2)))


def paired_delta(deltas: list[float], n_boot: int = 5000, seed: int = 3,
                 alpha: float = 0.05) -> dict:
    """Bootstrap CI of the MEAN paired delta (candidate - incumbent per circuit)."""
    d = np.asarray(deltas, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)])
    return {
        "n": int(len(d)),
        "mean_delta": float(d.mean()),
        "ci_low": float(np.quantile(means, alpha / 2)),
        "ci_high": float(np.quantile(means, 1 - alpha / 2)),
        "per_circuit": [float(x) for x in d],
    }


def acceptance(decision: dict, min_delta: float, cost_ratio: float) -> dict:
    """Preregistered gate: mean val improvement > min_delta with 95% CI excluding
    zero, and cost noninferior within 2%."""
    ci_excludes_zero = decision["ci_low"] > 0.0
    improvement = decision["mean_delta"] > min_delta and ci_excludes_zero
    noninferior_cost = cost_ratio <= 1.02
    return {
        "improvement": bool(improvement),
        "ci_excludes_null": bool(ci_excludes_zero),
        "mean_delta": decision["mean_delta"],
        "ci_low": decision["ci_low"],
        "ci_high": decision["ci_high"],
        "cost_ratio": cost_ratio,
        "cost_noninferior": bool(noninferior_cost),
        "accepted": bool(improvement and noninferior_cost),
    }
