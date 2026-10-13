"""EXP-008 appendix block for the grant evidence appendix.

`render_exp008_block(analysis)` consumes the verbatim content of
experiments/EXP-008-GATE-CALIBRATION/data/analysis.json (written by
`src/gate_calib.py analyze`) and returns the block the appendix builder
integrates:

    {"headline": str, "lines": [str, ...], "target_page": int}

STRICT contract (reviewer-facing):
  * EVERY number below renders from the analysis dict ONLY — no defaults,
    no recomputation, no side inputs. Missing fields raise KeyError on
    purpose (direct indexing — including the per-rep keys — so an absent
    field can never silently pass); the decision scale renders from
    a4["n_val"], never a hardcoded 12.
  * Plain strings only — no reportlab objects; the appendix builder
    (grant/make_appendix.py) owns layout, fonts and styles.
  * target_page = 1: the appendix is capped at 4 pages by design (the
    grant structure in GRANT-ANALYSIS.md) and page 4 carries <100pt of
    slack, so the EXP-008 calibration renders as a COMPACT block
    (headline + 3 note lines, no section heading — the headline itself
    leads with the experiment id) at the END of page 1, right after the
    headline paragraph; the page-4 honest-negatives section references
    EXP-008. The builder fails closed if the build would exceed 4 pages.
    Design echo numbers (seed, shots, reps, configs) render from
    analysis.meta, never hardcoded.
  * Label discipline: A4 is "fidelity-component pass probability" — the
    campaign's cost gate (wall-time ratio <= 1.02) is NOT simulated; the
    A4/A5 line says so.
"""

from __future__ import annotations

TARGET_PAGE = 1  # renders at the end of page 1 (page-4 slack is <100pt); the
# 4-page cap itself is enforced by make_appendix.py on the whole build


def render_exp008_block(analysis: dict) -> dict:
    meta = analysis["meta"]
    a1 = analysis["a1"]
    a2 = analysis["a2"]
    a3 = analysis["a3"]
    a4 = analysis["a4"]
    a5 = analysis["a5"]
    observed = a4["observed"]
    shifted = a4["shifted_to_min_delta"]
    a4b = a4["per_rep_single_evaluation"]
    pooled_mean = a1["pooled_mean"]
    p_pass_obs = observed["p_both"]
    p_pass_shift = shifted["p_both"]
    # direct key access on the per-rep dict: a missing rep MUST raise
    # KeyError, never an IndexError from a positional fallback
    a4b_rep1 = a4b["rep1"]["observed"]["p_both"]
    a4b_rep2 = a4b["rep2"]["observed"]["p_both"]
    noise_ratio = a3["vs_min_delta"]["max_mean_over_min_delta"]
    min_delta = a3["vs_min_delta"]["min_delta"]
    jobs_total = meta["jobs_total"]
    usd_observed = meta["ledger_view"]["usd_observed"]
    seed = meta["exp008_seed"]
    shots = meta["shots"]
    reps = meta["n_reps"]
    cfg_b = meta["configs"]["base"]["chi_alloc"]
    cfg_c = meta["configs"]["chal"]["chi_alloc"]
    n_val = a4["n_val"]

    headline = (
        f"<b>Gate calibration (EXP-008).</b> Fidelity-component pass "
        f"probability {p_pass_obs * 100:.1f}% at the observed effect (pooled "
        f"mean paired Δ {pooled_mean:+.5f}), {p_pass_shift * 100:.1f}% at a "
        f"true effect sitting exactly at min_delta; worst same-config rep "
        f"noise {noise_ratio:.2f}× min_delta.")

    lines = [
        f"Design: {meta['n_circuits']} fresh circuits (seed {seed}, zero "
        f"suite/holdout contact), baseline {cfg_b} vs challenger {cfg_c} "
        f"(easy d≤8 / hard d≥12), {shots} shots × {reps} reps — "
        f"{jobs_total} jobs on {meta['device']}, TEST account, Oct 7 "
        f"(${usd_observed:.2f}).",
        f"A1/A2/A3: pooled paired Δ {pooled_mean:+.5f} (per-rep "
        f"{a1['per_rep_mean']['rep1']:+.5f}/"
        f"{a1['per_rep_mean']['rep2']:+.5f}); bootstrap 95% CI "
        f"[{a2['ci_low']:+.5f}, {a2['ci_high']:+.5f}]; rep noise |rep1−rep2| "
        f"= {a3['base']['mean_over_min_delta']:.2f}× (base) / "
        f"{a3['chal']['mean_over_min_delta']:.2f}× (chal) of min_delta "
        f"{min_delta:.6f}.",
        f"A4/A5: at the {n_val}-circuit decision scale P(both) = "
        f"{p_pass_obs * 100:.1f}% observed / {p_pass_shift * 100:.1f}% "
        f"shifted-to-min_delta; per-rep single-evaluation libraries "
        f"{a4b_rep1 * 100:.1f}% / {a4b_rep2 * 100:.1f}%. Fidelity components "
        f"only — the cost gate (ratio ≤ 1.02) is not simulated "
        f"(deterministic per config). Frozen prediction (point "
        f"{a5['point']:+.3f}, band [{a5['band_low']:+.3f}, "
        f"{a5['band_high']:+.3f}]): observed {a5['observed']:+.5f}, "
        f"in_band = {a5['in_band']}.",
    ]

    return {"headline": headline, "lines": lines, "target_page": TARGET_PAGE}
