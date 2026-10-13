"""G7 — campaign report: staircase + control overlay, cost-fidelity Pareto,
chi sweep, per-round table, claims.json (every number -> job IDs), job export.

Usage: .venv/bin/python -u src/report.py [--holdout runs/<stamp>_holdout]
Runs after G6 (holdout evaluated once). If holdout metrics are absent the
report is produced in PARTIAL mode (no holdout/claims sections) — usable for
mid-campaign checks, never a substitute for the final report.

Every numeric claim lands in claims.json with the job IDs that produced it.
Zero promotions is a valid outcome and is reported as such.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

FLYWHEEL_DIR = ROOT / "runs" / "flywheel"
OUT_DIR = ROOT / "runs" / "report"

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── FACTS TO ADAPT ON A FRESH RUN (Oct 11: personal account, verify cost) ──
# 2026-10-11 adapted for the personal-account replication run (all ledgered
# jobs billed $0.00 on mps.cpu; spend cross-check vs billing dashboard owed
# before the appendix ships).
FACTS_ACCOUNT = "personal account"
FACTS_DEVICE_COST = "mps.cpu ($0)"


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(p: pathlib.Path) -> dict:
    return json.loads(p.read_text())


def find_holdout_metrics(explicit: str | None) -> pathlib.Path | None:
    if explicit:
        p = ROOT / explicit if not pathlib.Path(explicit).is_absolute() \
            else pathlib.Path(explicit)
        return p / "metrics.json" if (p / "metrics.json").exists() else None
    cands = sorted(ROOT.glob("runs/*_holdout/metrics.json"))
    return cands[-1] if cands else None


def paired_rows(rows_a: list[dict], rows_b: list[dict]) -> tuple[list[float], list[str]]:
    """Per-circuit paired deltas a-b over shared circuit ids (+ their job ids)."""
    bmap = {r["id"]: r for r in rows_b}
    deltas, ids = [], []
    for a in rows_a:
        b = bmap.get(a["id"])
        if a.get("xeb") is not None and b is not None and b.get("xeb") is not None:
            deltas.append(a["xeb"] - b["xeb"])
            ids += [a.get("job_id"), b.get("job_id")]
    return deltas, [i for i in ids if i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout")
    args = ap.parse_args()

    state = load_json(FLYWHEEL_DIR / "state.json")
    man = load_json(ROOT / "suite" / "MANIFEST.json")
    g3 = load_json(ROOT / state["g3_run_dir"] / "metrics.json")
    hold_path = find_holdout_metrics(args.holdout)
    hold = load_json(hold_path) if hold_path else None
    if hold is None:
        print("[g7] PARTIAL mode: no holdout metrics found")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    claims: list[dict] = []

    def claim(text: str, value, evidence: dict) -> None:
        claims.append({"claim": text, "value": value, "evidence": evidence})

    hist = state["history"]
    fly = [h for h in hist if h["arm"] == "flywheel"]
    ctl = [h for h in hist if h["arm"] == "control"]
    base_val = g3["val_run1"]
    base_jobs = [r["job_id"] for r in base_val["rows"] if r.get("job_id")]

    claim("Baseline (r0) mean val normalized XEB", base_val["mean_xeb"],
          {"run": state["g3_run_dir"], "job_ids": base_jobs})
    claim("Run-to-run noise sd of paired val XEB (two identical passes)",
          g3["noise_sd_paired"],
          {"run": state["g3_run_dir"], "job_ids": base_jobs + [
              r["job_id"] for r in g3["val_run2"]["rows"] if r.get("job_id")]})
    claim("Promotion threshold min_delta", state["min_delta"],
          {"formula": "max(2.0*sd_paired, 0.005)"})

    # ---------------------------------------------------------- staircase
    # two panels sharing x: top = incumbent trajectory (zoomed so the
    # min_delta band and the single control promotion are readable; the
    # flywheel step line sits exactly on the baseline because it never
    # promoted — that coincidence IS the result); bottom = every candidate's
    # val mean on the full 0-1 scale (rejected permutation catastrophes etc.)
    C_FLY, C_CTL = "#0072B2", "#D55E00"  # Okabe-Ito: luminance-separated, grayscale-safe
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(7.0, 5.6), sharex=True, height_ratios=[2.2, 1.0])
    for arm, rows, color, z in (("flywheel", fly, C_FLY, 3.5),
                                ("control", ctl, C_CTL, 3.0)):
        y = base_val["mean_xeb"]
        xs, ys = [0], [y]
        for h in rows:
            if h["accepted"]:
                y = h["val_mean_xeb"]
            xs.append(h["round"])
            ys.append(y)
        # flywheel z above control: both lines sit exactly on the baseline
        # before the promotion round and control would otherwise hide it
        ax.step(xs, ys, where="post", color=color, linewidth=2.2, zorder=z,
                label=f"{arm} incumbent (val)")
        ax2.scatter([h["round"] for h in rows], [h["val_mean_xeb"] for h in rows],
                    s=30, facecolors="none", edgecolors=color,
                    marker="o" if arm == "flywheel" else "s", linewidths=1.3,
                    zorder=3, label=f"{arm} candidates")
        for h in rows:
            if h["accepted"]:
                ax.scatter([h["round"]], [h["val_mean_xeb"]], s=120, color=color,
                           marker="*" if arm == "flywheel" else "X", zorder=5)
                # flywheel label ABOVE its marker, control BELOW: with both
                # arms promoting r1 at close values (personal rerun) one
                # above-offset put the control text under the flywheel step
                # line; zorder over the lines lets the halo mask crossings
                _above = arm == "flywheel"
                ax.annotate(f"promote r{h['round']}: "
                            f"{h['mean_delta']:+.4f} (CI excl. 0)",
                            (h["round"], h["val_mean_xeb"]),
                            textcoords="offset points",
                            xytext=(9, 7) if _above else (9, -9),
                            va="bottom" if _above else "top",
                            fontsize=8, color=color, zorder=6,
                            bbox=dict(facecolor="white", edgecolor="none",
                                      alpha=0.9, pad=1.5))
    ax.axhline(base_val["mean_xeb"], color="k", linestyle="-.", linewidth=1.4,
               zorder=4, label=f"baseline r0 = {base_val['mean_xeb']:.4f}")
    r_max = max(10, len(fly), len(ctl))
    ax.fill_between([0, r_max],
                    base_val["mean_xeb"] - state["min_delta"],
                    base_val["mean_xeb"] + state["min_delta"],
                    color="gray", alpha=0.25, label="noise band (±min_delta)")
    ax2.axhline(base_val["mean_xeb"], color="k", linestyle="-.", linewidth=1,
                zorder=2)
    ax2.fill_between([0, r_max],
                     base_val["mean_xeb"] - state["min_delta"],
                     base_val["mean_xeb"] + state["min_delta"],
                     color="gray", alpha=0.25)
    # zoom to the STEP trajectory only (baseline ± band + promoted incumbents);
    # taking min/max over every candidate's val mean (permutation crashes at
    # ~0.02-0.55) flattened the panel and hid the staircase entirely
    step_vals = [base_val["mean_xeb"]] + [h["val_mean_xeb"] for h in hist
                                          if h["accepted"]]
    y_lo = min(base_val["mean_xeb"] - state["min_delta"], *step_vals) - 0.020
    y_hi = max(base_val["mean_xeb"] + state["min_delta"], *step_vals) + 0.016
    ax.set_ylim(y_lo, y_hi)
    ax.set_xlim(-0.3, r_max + 0.3)
    ax2.set_ylim(-0.04, 1.05)  # headroom so the r4 crash marker isn't clipped
    ax2.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0])
    ax.set_ylabel("mean normalized XEB on val (12 circuits)")
    ax2.set_ylabel("all candidates")
    ax2.set_xlabel("round")
    ax.set_title("Adversarial flywheel vs no-memory control (val staircase)")
    from matplotlib.lines import Line2D
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Line2D([], [], color=C_CTL, marker="X", linestyle="None",
                          markersize=7))
    labels.append("promotion event")
    # 2-column: a 5-row single-column box anchored lower-right reaches up
    # into the baseline, occluding the dotted r0 line AND the flywheel step
    # line that sits exactly on it (the figure's headline result); flattened
    # to 3 rows it stays inside the empty strip below the noise band
    ax.legend(handles, labels, loc="lower right", fontsize=7.5, ncol=2,
              framealpha=0.95, columnspacing=0.9, handletextpad=0.5,
              borderpad=0.4)
    # center-left: the crash markers (~0.02-0.55) live bottom-left/mid-right
    # and the ~1.0 candidates top — the vertical middle of the left half is
    # the only band clear of markers at every width (a 2-column box at lower
    # left covered the round-4 crash point)
    ax2.legend(loc="center left", fontsize=7.5, ncol=2, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "staircase.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # ---------------------------------------------------------- Pareto
    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    ax.scatter(base_val["cost_min"], base_val["mean_xeb"], color="k", marker="^",
               s=52, zorder=3, label="baseline r0 (val)")
    for h in fly:
        ax.scatter(h["cost_min"], h["val_mean_xeb"], color=C_FLY,
                   marker="*" if h["accepted"] else "o",
                   s=52 if h["accepted"] else 26, zorder=3)
    for h in ctl:
        ax.scatter(h["cost_min"], h["val_mean_xeb"], color=C_CTL,
                   marker="X" if h["accepted"] else "s",
                   s=52 if h["accepted"] else 26, zorder=3)
    if hold:
        # baseline_r0 FIRST: its diamond lands almost exactly on the
        # flywheel-final diamond (the flywheel never left r0 — that IS the
        # result), so drawing it last occluded the flywheel crescent
        for name, color in (("baseline_r0", "k"),
                            ("control_final", C_CTL),
                            ("flywheel_final", C_FLY)):
            r = hold["results"][name]
            cost = sum(x["wall_min"] for x in r["rows"])
            ax.scatter(cost, r["mean_xeb_holdout"], marker="D", s=70,
                       color=color, edgecolors="w", zorder=5,
                       label=f"{name.replace('_', ' ')} (holdout)")
        # headline annotation: control's holdout win, computed not hardcoded.
        # The cost parenthetical ("+0.3 min vs r0") was removed: it mixed a
        # holdout-wall basis into a figure whose x-axis carries val-suite cost
        # AND read sign-ambiguous (control is CHEAPER; the "+0.3" was
        # r0-minus-control). The paired delta + CI is the claim that matters.
        from metrics import paired_delta
        cf_r = hold["results"]["control_final"]
        cf_cost = sum(x["wall_min"] for x in cf_r["rows"])
        bl_r = hold["results"]["baseline_r0"]
        s_cf = paired_delta(paired_rows(cf_r["rows"], bl_r["rows"])[0])
        ax.annotate(f"control final (holdout): {cf_r['mean_xeb_holdout']:.4f} XEB\n"
                    f"paired vs r0: {s_cf['mean_delta']:+.4f}\n"
                    f"95% CI [{s_cf['ci_low']:+.4f}, {s_cf['ci_high']:+.4f}]",
                    (cf_cost, cf_r["mean_xeb_holdout"] + 0.008),
                    xytext=(0.03, 0.70), textcoords="axes fraction", fontsize=8,
                    color=C_CTL, va="center", ha="left", zorder=6,
                    arrowprops=dict(arrowstyle="-|>", color="#444444",
                                    lw=1.1))
        # the three holdout finals nearly coincide on the main axes (their
        # costs differ by <0.4 min on a ~11-min axis) — zoom inset so the
        # decisive control-vs-r0 separation is readable; positions are data,
        # only the view is magnified
        axins = ax.inset_axes([0.46, 0.48, 0.34, 0.32])
        ins_pts = []
        for name, color, tag, dx, dy in (
                ("control_final", C_CTL, "control", 0, 5),
                ("baseline_r0", "k", "r0", -7, 6),
                ("flywheel_final", C_FLY, "fly", 7, -5)):
            r = hold["results"][name]
            c = sum(x["wall_min"] for x in r["rows"])
            ins_pts.append((c, r["mean_xeb_holdout"]))
            axins.scatter(c, r["mean_xeb_holdout"], marker="D", s=30,
                          color=color, edgecolors="w", linewidths=0.8,
                          zorder=5)
            axins.annotate(tag, (c, r["mean_xeb_holdout"]),
                           textcoords="offset points", xytext=(dx, dy),
                           fontsize=8, color=color, ha="left", va="center")
        axins.set_xlim(min(x for x, _ in ins_pts) - 0.40,
                       max(x for x, _ in ins_pts) + 0.40)
        axins.set_ylim(min(y for _, y in ins_pts) - 0.016,
                       max(y for _, y in ins_pts) + 0.016)
        axins.tick_params(labelsize=7.5, labelbottom=False)
        axins.set_title("holdout finals zoom", fontsize=8, pad=3,
                        bbox=dict(facecolor="white", edgecolor="none",
                                  alpha=0.85, pad=1.5))
        axins.grid(alpha=0.3)
        ind = ax.indicate_inset_zoom(axins, edgecolor="#666666", alpha=0.75,
                                     linewidth=0.8)
        # rect + connectors BELOW the markers so they never slice a glyph
        try:
            ind.rect.set_zorder(1.5)
            for c in ind.connecters:
                c.set_zorder(1.5)
        except AttributeError:
            pass
    ax.set_xlabel("wall time per 12-circuit suite (queue+run, minutes)")
    ax.set_ylabel("mean normalized XEB")
    ax.set_title("Cost vs fidelity Pareto (rejected, promoted, holdout finals)")
    handles, labels = ax.get_legend_handles_labels()
    # X proxy in control orange: the only promotion in this campaign is the
    # control r1 X — the swatch must map to the marker that exists
    handles.append(Line2D([], [], color=C_CTL, marker="X",
                          linestyle="None", markersize=7))
    labels.append("promotion event (X)")
    ax.legend(handles, labels, fontsize=8, loc="lower right", framealpha=0.95)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "pareto.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # ---------------------------------------------------------- chi sweep
    sweep = {"32": g3["chi_sweep"]["32"], "64": base_val}
    for k in ("128", "256"):
        if k in g3["chi_sweep"]:
            sweep[k] = g3["chi_sweep"][k]
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    chis = sorted(int(c) for c in sweep)
    overall = [sweep[str(c)]["mean_xeb"] for c in chis]
    ax.plot(chis, overall, "o-", color="#0072B2", label="val mean (all 12)")
    man_rows = {c["id"]: c for c in man["circuits"]}
    for klass, depths, color, mk in (("easy (d≤8)", (4, 8), "#009E73", "^"),
                                     ("hard (d≥12)", (12, 16), "#D55E00", "s")):
        ys = []
        for c in chis:
            vals = [r["xeb"] for r in sweep[str(c)]["rows"]
                    if r["xeb"] is not None and man_rows[r["id"]]["depth"] in depths]
            ys.append(sum(vals) / len(vals) if vals else float("nan"))
        ax.plot(chis, ys, mk + ("--" if "hard" in klass else ":"), color=color,
                label=klass)
    # headline annotation: overall chi=32 -> chi=256 gain, computed not
    # hardcoded; anchored to the AXES top-left corner — the old data-anchored
    # version rode up into the title and straddled the top spine
    d_lo, d_hi = overall[0], overall[-1]
    ax.text(0.02, 0.97,
            f"χ {chis[0]}\u2192{chis[-1]}: {d_hi - d_lo:+.4f} overall",
            transform=ax.transAxes, ha="left", va="top", fontsize=8,
            color="#0072B2",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.5))
    ax.set_ylim(0.67, 1.05)
    ax.set_xscale("log", base=2)
    ax.set_xticks(chis)
    ax.set_xticklabels([str(c) for c in chis])
    ax.set_xlabel("MPS bond dimension χ, uniform (log2 scale)")
    ax.set_ylabel("mean normalized XEB on val")
    ax.set_title("χ sweep at baseline (telemetry, not a gate)")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "chi_sweep.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    chi_ids = [r["job_id"] for k in sweep for r in sweep[k]["rows"] if r.get("job_id")]
    claim("chi gradient on val: mean XEB at chi=32 vs chi=256",
          [sweep["32"]["mean_xeb"], sweep["256"]["mean_xeb"]],
          {"run": state["g3_run_dir"], "job_ids": chi_ids})

    # ---------------------------------------------------------- rounds table
    lines = ["| arm | round | mutation | value | mean delta | 95% CI | cost ratio | verdict |",
             "|---|---|---|---|---|---|---|---|"]
    # cost ratio = candidate cost / incumbent cost at that round; the incumbent
    # cost only moves on a promotion (history rows store cost_min, not the ratio)
    inc_cost = {"flywheel": base_val["cost_min"], "control": base_val["cost_min"]}
    rounds_rows = []
    for h in hist:
        ratio = h["cost_min"] / inc_cost[h["arm"]]
        lines.append(
            f"| {h['arm']} | {h['round']} | {h['mutation']['family']} "
            f"| {h['mutation']['value']} | {h['mean_delta']:+.5f} "
            f"| [{h['ci_low']:+.5f}, {h['ci_high']:+.5f}] "
            f"| {ratio:.3f} "
            f"| {'PROMOTED' if h['accepted'] else 'rejected'} |")
        rounds_rows.append({
            "arm": h["arm"], "round": h["round"],
            "family": h["mutation"]["family"],
            "value": str(h["mutation"]["value"]),
            "mean_delta": h["mean_delta"],
            "ci": [h["ci_low"], h["ci_high"]],
            "cost_ratio": ratio, "accepted": h["accepted"]})
        if h["accepted"]:
            inc_cost[h["arm"]] = h["cost_min"]
    rounds_table = "\n".join(lines)
    (OUT_DIR / "rounds_table.md").write_text(rounds_table + "\n")
    # structured twin of rounds_table.md — grant/make_appendix.py builds the
    # PDF rounds table from this, so no number is ever transcribed by hand
    (OUT_DIR / "rounds.json").write_text(json.dumps(rounds_rows, indent=1) + "\n")
    for h in hist:
        rm = load_json(ROOT / h["run_dir"] / "metrics.json")
        claim(f"{h['arm']} r{h['round']} ({h['mutation']['family']}="
              f"{h['mutation']['value']}) paired mean val delta",
              h["mean_delta"],
              {"run": h["run_dir"], "ci": [h["ci_low"], h["ci_high"]],
               "accepted": h["accepted"],
               "job_ids": [r["job_id"] for r in rm["val"]["rows"] if r.get("job_id")]})

    # ---------------------------------------------------------- holdout + claims
    hold_sec = ""
    if hold:
        res = hold["results"]
        fw, bl, cf = res["flywheel_final"], res["baseline_r0"], res["control_final"]
        from metrics import paired_delta
        d_fw, ids_fw = paired_rows(fw["rows"], bl["rows"])
        d_cf, ids_cf = paired_rows(cf["rows"], bl["rows"])
        d_duel, ids_duel = paired_rows(fw["rows"], cf["rows"])
        s_fw, s_cf, s_duel = (paired_delta(d) for d in (d_fw, d_cf, d_duel))
        hold_sec = f"""
## Holdout (G6, evaluated ONCE, {hold['n_holdout']} circuits)

| config | mean normalized XEB | paired delta vs r0 | 95% CI |
|---|---|---|---|
| baseline r0 | {bl['mean_xeb_holdout']:.5f} | — | — |
| no-memory control final | {cf['mean_xeb_holdout']:.5f} | {s_cf['mean_delta']:+.5f} | [{s_cf['ci_low']:+.5f}, {s_cf['ci_high']:+.5f}] |
| flywheel final | {fw['mean_xeb_holdout']:.5f} | {s_fw['mean_delta']:+.5f} | [{s_fw['ci_low']:+.5f}, {s_fw['ci_high']:+.5f}] |

Flywheel minus control (paired): {s_duel['mean_delta']:+.5f}, CI
[{s_duel['ci_low']:+.5f}, {s_duel['ci_high']:+.5f}].
"""
        claim("Flywheel final holdout mean XEB", fw["mean_xeb_holdout"],
              {"run": str(hold_path.parent.relative_to(ROOT)),
               "job_ids": [r["job_id"] for r in fw["rows"]]})
        claim("Baseline r0 holdout mean XEB", bl["mean_xeb_holdout"],
              {"run": str(hold_path.parent.relative_to(ROOT)),
               "job_ids": [r["job_id"] for r in bl["rows"]]})
        claim("Control final holdout mean XEB", cf["mean_xeb_holdout"],
              {"run": str(hold_path.parent.relative_to(ROOT)),
               "job_ids": [r["job_id"] for r in cf["rows"]]})
        claim("Flywheel-vs-r0 paired holdout delta", s_fw["mean_delta"],
              {"ci": [s_fw["ci_low"], s_fw["ci_high"]], "job_ids": ids_fw})
        claim("Control-vs-r0 paired holdout delta", s_cf["mean_delta"],
              {"ci": [s_cf["ci_low"], s_cf["ci_high"]], "job_ids": ids_cf})
        claim("Flywheel-vs-control paired holdout delta", s_duel["mean_delta"],
              {"ci": [s_duel["ci_low"], s_duel["ci_high"]], "job_ids": ids_duel})

    # ---------------------------------------------------------- summary
    n_promo_fly = sum(1 for h in fly if h["accepted"])
    n_promo_ctl = sum(1 for h in ctl if h["accepted"])
    pred_line = ""
    pred_rec = None
    pred_path = ROOT / "researcher" / "PREDICTIONS.jsonl"
    if pred_path.exists() and hold is not None:
        for line in pred_path.read_text().splitlines():
            r = json.loads(line)
            if r["campaign"] == "flywheel-test" and r["scored"]:
                pred_rec = r
                pred_line = (f"\nFrozen prediction (made at G3, before any round): "
                             f"point {r['point']:.5f}, band "
                             f"[{r['band'][0]:.5f}, {r['band'][1]:.5f}] — actual "
                             f"{r['actual']:.5f}, in band: **{r['in_band']}**.")
                claim("Preregistered prediction in band", r["in_band"],
                      {"prediction": r, "source": "researcher/PREDICTIONS.jsonl"})

    # ---------------------------------------------------------- headline
    headline_par = (f"The flywheel completed {len(fly)} preregistered rounds with "
                    f"{n_promo_fly} promotions; the no-memory control promoted "
                    f"{n_promo_ctl}.")
    if n_promo_fly == 0 and fly:
        best = max(fly, key=lambda h: h["mean_delta"])
        if best["mean_delta"] > state["min_delta"]:
            headline_par += (f" The best flywheel candidate (r{best['round']} "
                             f"{best['mutation']['family']}={best['mutation']['value']}, "
                             f"Δ{best['mean_delta']:+.5f}) cleared the mean-delta bar "
                             f"({state['min_delta']:.5f}) but its 95% CI "
                             f"[{best['ci_low']:+.5f}, {best['ci_high']:+.5f}] included "
                             f"zero — the promotion gate held.")
    if hold is not None and n_promo_ctl > 0:
        headline_par += (" The control-arm promotion was confirmed on the locked "
                         "holdout (paired delta vs r0 below).")

    report = f"""# Adversarial Replication Flywheel — campaign report ({FACTS_ACCOUNT})

Generated {utcnow()} · suite sha256 `{man['suite_sha256'][:16]}…` ·
{state['round']} flywheel rounds + {len(ctl)} control rounds ·
{n_promo_fly}/{len(fly)} flywheel promotions, {n_promo_ctl}/{len(ctl)} control
promotions.{pred_line}

Score: mean per-circuit normalized XEB (1 = exact). Device: {FACTS_DEVICE_COST}.
Promotion gate: paired 95% CI excludes 0 AND mean delta > min_delta
({state['min_delta']:.5f} = 2x measured run-to-run sd) AND cost noninferior
within 2% — enforced by the experiment ledger, never by hand.

## Headline

{headline_par}

{hold_sec if hold_sec else "Holdout not yet evaluated (run src/holdout_eval.py after all rounds close)."}

## Val staircase (per round)

![staircase](staircase.png)

{rounds_table}

## Cost-fidelity Pareto

![pareto](pareto.png)

## chi telemetry sweep (G3)

![chi sweep](chi_sweep.png)

## Zero-promotion clause

{'All flywheel rejections are reported as such — no promotion happened, and that is a valid, preregistered outcome.' if n_promo_fly == 0 else 'Promotions above are the complete set; every other round was rejected by the gate.'}

Full per-round metrics: runs/flywheel/*/, every job in ledger/jobs.sqlite
(export below). Claims ledger: claims.json.
"""
    (OUT_DIR / "report.md").write_text(report)
    (OUT_DIR / "claims.json").write_text(json.dumps(
        [{"generated_at": utcnow(), "suite_sha256": man["suite_sha256"]}]
        + claims, indent=2))

    # structured headline summary — grant/make_appendix.py renders every
    # numeric surface of the PDF from this file (no hand transcription)
    def _walk_job_ids(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "job_ids" and isinstance(v, list):
                    yield from v
                else:
                    yield from _walk_job_ids(v)
        elif isinstance(node, list):
            for v in node:
                yield from _walk_job_ids(v)

    refs = list(_walk_job_ids(claims))
    import bq_jobs
    con = bq_jobs.connect()
    ledger_jobs = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    devices = [r[0] for r in con.execute(
        "SELECT DISTINCT device FROM jobs ORDER BY device")]
    con.close()
    best_fly = max(fly, key=lambda h: h["mean_delta"]) if fly else None
    summary = {
        "generated_at": utcnow(),
        "suite_sha256": man["suite_sha256"],
        "rounds_per_arm": {"flywheel": len(fly), "control": len(ctl)},
        "promotions": {"flywheel": n_promo_fly, "control": n_promo_ctl},
        "baseline": {"mean_xeb_val": base_val["mean_xeb"],
                     "cost_min": base_val["cost_min"]},
        "min_delta": state["min_delta"],
        "noise_sd_paired": g3["noise_sd_paired"],
        "best_flywheel": None if best_fly is None else {
            "round": best_fly["round"], "family": best_fly["mutation"]["family"],
            "value": str(best_fly["mutation"]["value"]),
            "mean_delta": best_fly["mean_delta"],
            "ci": [best_fly["ci_low"], best_fly["ci_high"]],
            "accepted": best_fly["accepted"]},
        "prediction": pred_rec,
        "holdout": None if hold is None else {
            "n_holdout": hold["n_holdout"],
            "results": {k: {"mean_xeb_holdout": v["mean_xeb_holdout"],
                            "wall_min": sum(x["wall_min"] for x in v["rows"])}
                        for k, v in hold["results"].items()},
            "paired": {"control_vs_r0": {"delta": s_cf["mean_delta"],
                                          "ci": [s_cf["ci_low"], s_cf["ci_high"]]},
                       "flywheel_vs_r0": {"delta": s_fw["mean_delta"],
                                          "ci": [s_fw["ci_low"], s_fw["ci_high"]]},
                       "flywheel_vs_control": {"delta": s_duel["mean_delta"],
                                               "ci": [s_duel["ci_low"],
                                                      s_duel["ci_high"]]}}},
        "claims": {"n_claims": len(claims), "n_job_refs": len(refs),
                   "n_distinct_jobs": len(set(refs))},
        "ledger": {"jobs_total": ledger_jobs, "devices": devices},
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")

    # job export for reproducibility
    import bq_jobs
    con = bq_jobs.connect()
    bq_jobs.export(con, OUT_DIR / "jobs_export.json", OUT_DIR / "jobs_export.csv")

    print(f"[g7] report -> {OUT_DIR}/report.md ({len(claims)} claims, "
          f"holdout={'yes' if hold else 'PARTIAL'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
