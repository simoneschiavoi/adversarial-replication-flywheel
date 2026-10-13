"""Shared helpers for the evidence notebooks.

- load_bundle(): open notebooks/data/<label>/ and verify every file's sha256
  against PROVENANCE.json before any number is read.
- paired_delta(): the campaign's bootstrap rule, re-implemented line for line
  from src/metrics.py (seed 3, 5000 resamples, percentile 95% CI) so the
  notebooks can recompute recorded CIs bit-for-bit without importing the
  campaign code.
- style(): one matplotlib look for every figure (validated categorical palette:
  slot 1 blue, slot 2 orange, slot 3 aqua; hairline grid; ink colors for text).
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import numpy as np

NB_ROOT = pathlib.Path(__file__).resolve().parent

# --- palette (light surface). Arms keep their color in every figure.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
NEUTRAL = "#898781"
ARM_COLOR = {"flywheel": BLUE, "control": ORANGE, "baseline": NEUTRAL}


def style() -> None:
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE, "figure.dpi": 110,
        "font.family": "sans-serif", "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK_2,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "grid.linestyle": "-", "axes.axisbelow": True,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "legend.frameon": False, "lines.linewidth": 2.0,
        "axes.titlesize": 11, "axes.titleweight": "bold",
        "axes.titlelocation": "left",
    })


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class Bundle:
    def __init__(self, label: str):
        self.root = NB_ROOT / "data" / label
        self.prov = json.loads((self.root / "PROVENANCE.json").read_text())

    def verify(self) -> dict:
        bad = [f["path"] for f in self.prov["files"]
               if sha256(self.root / f["path"]) != f["sha256"]]
        return {"files": len(self.prov["files"]), "mismatches": bad}

    def path(self, rel: str) -> pathlib.Path:
        return self.root / rel

    def json(self, rel: str):
        return json.loads(self.path(rel).read_text())


def load_bundle(label: str | None = None) -> Bundle:
    """Default bundle: $NB_BUNDLE, else 'test-campaign'."""
    import os
    b = Bundle(label or os.environ.get("NB_BUNDLE", "test-campaign"))
    v = b.verify()
    if v["mismatches"]:
        raise RuntimeError(f"bundle files changed since build: {v['mismatches']}")
    return b


def paired_delta(deltas, n_boot: int = 5000, seed: int = 3, alpha: float = 0.05) -> dict:
    """Identical algorithm to src/metrics.py::paired_delta (campaign code)."""
    d = np.asarray(deltas, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)])
    return {
        "n": int(len(d)),
        "mean_delta": float(d.mean()),
        "ci_low": float(np.quantile(means, alpha / 2)),
        "ci_high": float(np.quantile(means, 1 - alpha / 2)),
    }


def gate(mean_delta: float, ci_low: float, cost_ratio: float, min_delta: float) -> bool:
    """Preregistered acceptance rule (src/metrics.py::acceptance)."""
    return bool(mean_delta > min_delta and ci_low > 0.0 and cost_ratio <= 1.02)


def check_table(rows, title: str = "") -> str:
    """Render [(claim, recorded, recomputed, ok)] as a markdown table string."""
    out = [f"**{title}**\n" if title else "",
           "| check | recorded | recomputed | match |", "|---|---|---|---|"]
    for claim, rec, new, ok in rows:
        out.append(f"| {claim} | {rec} | {new} | {'✅' if ok else '❌'} |")
    return "\n".join(out)
