"""G6 — LOCKED holdout evaluation. ONE-SHOT for the whole campaign.

Post-pivot design (EXP-003): the holdout is 12 exact-truth RCS circuits,
scored by per-circuit normalized XEB (canonical mps count keys, inverse
site-permutation applied when the config permutes). Evaluates exactly three
configs in a SINGLE unlock window (jobs are submitted AFTER re-locking; only
circuits+truths are copied out while unlocked):
  1. flywheel_final  — state.incumbent.config
  2. baseline_r0     — the G3 uniform config
  3. control_final   — state.control_incumbent.config (no-memory arm lineage)

Ledger discipline: EXP-007-HOLDOUT is registered (SPEC+PREREG, caps only,
no acceptance decision — this is measurement, not selection) BEFORE any job
is dispatched, and recorded after. Refuses to run if
suite/.HOLDOUT_EVALUATED exists. Every unlock is appended to
suite/holdout/HOLDOUT_ACCESS.log. Writing the sentinel disables the campaign.

Usage: .venv/bin/python -u src/holdout_eval.py
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

SUITES = ROOT / "suite"
HOLD = SUITES / "holdout"
SENTINEL = SUITES / ".HOLDOUT_EVALUATED"
LEDGER = [".venv/bin/python", "tools/ledger.py"]


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def unlock(log_line: str) -> None:
    HOLD.chmod(0o500)
    for f in HOLD.iterdir():
        f.chmod(0o600 if f.name == "HOLDOUT_ACCESS.log" else 0o400)
    with (HOLD / "HOLDOUT_ACCESS.log").open("a") as f:
        f.write(f"{utcnow()} UNLOCK: {log_line}\n")


def relock() -> None:
    for f in HOLD.iterdir():
        f.chmod(0)
    HOLD.chmod(0)


def main() -> int:
    import subprocess
    if SENTINEL.exists():
        raise SystemExit("FAIL: holdout already evaluated once (sentinel present). "
                         "A second evaluation would invalidate the campaign.")
    man = json.loads((SUITES / "MANIFEST.json").read_text())
    state = json.loads((ROOT / "runs" / "flywheel" / "state.json").read_text())

    holdout = [c for c in man["circuits"] if c["split"] == "holdout"]
    if len(holdout) != 12:
        raise SystemExit(f"FAIL: expected 12 holdout circuits, got {len(holdout)}")
    from harness import BASELINE_CONFIG
    configs = {
        "flywheel_final": state["incumbent"]["config"],
        "baseline_r0": json.loads(json.dumps(BASELINE_CONFIG)),
        "control_final": state["control_incumbent"]["config"],
    }

    # ledger: register the one-shot measurement BEFORE dispatching any job
    exp_id = "EXP-007-HOLDOUT"
    exp_dir = ROOT / "experiments" / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    n_acc = sum(1 for h in state.get("history", []) if h["accepted"])
    (exp_dir / "SPEC.md").write_text(f"""# {exp_id} — G6 one-shot locked-holdout evaluation

The 12 holdout circuits of the frozen suite (suite_sha256
{man['suite_sha256'][:16]}…) are evaluated EXACTLY ONCE, after every round of
both arms is closed. Three configs, one unlock window each for copying
circuits+truths only (jobs run after re-lock):

  flywheel_final = {json.dumps(configs['flywheel_final'])}
  baseline_r0    = {json.dumps(configs['baseline_r0'])}
  control_final  = {json.dumps(configs['control_final'])}

Score: per-circuit normalized XEB (canonical mps key order; inverse site
permutation before lookup when the config permutes). No acceptance decision
is made here — this is measurement. Campaign state at evaluation:
{state['round']} flywheel rounds, {sum(1 for h in state.get('history', []) if h['arm'] == 'control')} control rounds, {n_acc} promotions total.

Gates: caps only (jobs_max=40, usd_max=0.50; mps.cpu is $0).
""")
    (exp_dir / "PREREGISTRATION.json").write_text(json.dumps({
        "exp_id": exp_id, "one_shot": True,
        "configs": configs, "n_holdout": len(holdout),
        "metric": "mean normalized XEB over holdout, per config",
        "suite_sha256": man["suite_sha256"], "frozen_at": utcnow(),
    }, indent=2))
    out = subprocess.run(LEDGER + ["register", exp_id,
                                   str(exp_dir / "SPEC.md"),
                                   "--gate", "jobs_max=40",
                                   "--gate", "usd_max=0.50"],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0 and "already registered" not in out.stdout:
        raise SystemExit(f"FAIL register {exp_id}: {out.stdout}{out.stderr}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"{stamp}_holdout"
    run_dir.mkdir(parents=True, exist_ok=True)
    circuits_dir = run_dir / "circuits"
    circuits_dir.mkdir(exist_ok=True)
    truth_dir = run_dir / "truth"
    truth_dir.mkdir(exist_ok=True)

    # completion guard (additive): holdout stays locked until BOTH arms have
    # 10 recorded rounds AND both canaries (k=6, k=10) exist in state.json
    fly_n = len([h for h in state.get("history", []) if h.get("arm") == "flywheel"])
    ctl_n = len([h for h in state.get("history", []) if h.get("arm") == "control"])
    canary_ks = sorted(c.get("round_k") for c in state.get("canaries", [])
                       if isinstance(c, dict))
    if fly_n < 10 or ctl_n < 10 or 6 not in canary_ks or 10 not in canary_ks:
        raise SystemExit(
            "holdout locked: campaign incomplete — need 10 rounds per arm + "
            f"canaries at k=6,10 (flywheel={fly_n} control={ctl_n} "
            f"canaries={canary_ks})")

    print(f"[g6] unlocking holdout ONCE ({len(holdout)} circuits, 3 configs)")
    unlock(f"one-shot evaluation, configs={list(configs)}")
    for c in holdout:
        shutil.copy(HOLD / f"{c['id']}.qpy", circuits_dir / f"{c['id']}.qpy")
        shutil.copy(HOLD / f"p_{c['id']}.npy", truth_dir / f"p_{c['id']}.npy")
    relock()
    print("[g6] re-locked; secrets copied out of the protected dir for scoring")

    from bq import get_client, run_batch, RoundSpec
    from circuits import load_circuit, permuted, measure_all
    from harness import perm_of, unpermute_key, chi_for, shots_for
    from metrics import xeb_normalized, canonical_counts
    import numpy as np

    client = get_client()
    results: dict[str, dict] = {}
    for name, cfg in configs.items():
        rows = []
        for c in holdout:
            qc = load_circuit(circuits_dir / f"{c['id']}.qpy")
            if qc.num_clbits:
                qc = qc.remove_final_measurements(inplace=False)
            pi = perm_of(qc.num_qubits, cfg.get("permutation_seed"))
            if pi is not None:
                qc = permuted(qc, pi)
            spec = [RoundSpec(measure_all(qc), shots=shots_for(cfg, c["depth"]),
                              options={"mps_bond_dimension": chi_for(cfg, c["depth"])},
                              label=f"g6-{name}-{c['id']}")]
            res = run_batch(client, exp_id, f"g6-{name}", spec,
                            device=cfg["device"], max_concurrent=2)
            r = next(iter(res["jobs"].values()))
            job = r["job"]
            wall_min = ((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000
            row = {"id": c["id"], "n": c["n"], "depth": c["depth"],
                   "job_id": job.job_id, "run_status": job.run_status,
                   "wall_min": round(wall_min, 4), "cost_usd": job.cost}
            if r["counts"] is None:
                row["xeb"] = None
                row["error"] = job.error_message
            else:
                counts = canonical_counts(r["counts"], cfg["device"])
                if pi is not None:
                    counts = {unpermute_key(k, pi): v for k, v in counts.items()}
                p = np.load(truth_dir / f"p_{c['id']}.npy", mmap_mode="r")
                row["xeb"] = round(xeb_normalized(counts, p), 6)
            rows.append(row)
            print(f"[g6] {name}/{c['id']} xeb={row.get('xeb')} job={job.job_id}")
        xeb_vals = [r["xeb"] for r in rows if r["xeb"] is not None]
        results[name] = {
            "config": cfg, "rows": rows,
            "mean_xeb_holdout": (sum(xeb_vals) / len(xeb_vals)) if xeb_vals else None,
        }

    metrics = {
        "gate": "G6", "exp": exp_id, "evaluated_at": utcnow(),
        "suite_sha256": man["suite_sha256"],
        "n_holdout": len(holdout), "results": results,
        "usd": round(sum(r["cost_usd"] or 0 for v in results.values()
                         for r in v["rows"]), 6),
        "jobs": sum(len(v["rows"]) for v in results.values()),
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    out = subprocess.run(LEDGER + ["record", exp_id, str(run_dir)],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"FAIL record {exp_id}: {out.stdout}{out.stderr}")

    # score the frozen campaign prediction now that the final answer exists
    actual = results["flywheel_final"]["mean_xeb_holdout"]
    if actual is not None:
        sc = subprocess.run([".venv/bin/python", "tools/rsi.py", "score",
                             "--campaign", "flywheel-test",
                             "--actual", f"{actual:.6f}"],
                            cwd=ROOT, capture_output=True, text=True)
        print(f"[g6] prediction score: {sc.stdout.strip()}{sc.stderr.strip()}")

    # drop the sentinel in a minimal second unlock, then disable everything
    unlock("write .EVALUATED sentinel")
    HOLD.chmod(0o700)  # creating the NEW .EVALUATED needs a dir write bit; unlock's 0o500 is append-only
    (HOLD / ".EVALUATED").write_text(utcnow() + "\n")
    (HOLD / ".EVALUATED").chmod(0)
    relock()
    SENTINEL.write_text(utcnow() + "\n")
    print(f"[g6] DONE -> {run_dir}/metrics.json (sentinel written, campaign closed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
