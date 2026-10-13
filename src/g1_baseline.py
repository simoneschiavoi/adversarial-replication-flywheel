"""G1 — tutorial baseline: CPU-scaled reproduction of the BlueQubit tutorial
(reproduce Google's RCS XEB fidelity-vs-depth plot, mini scale).

Preregistered in experiments/EXP-001-G1-TUTORIAL-BASELINE (frozen before dispatch):
- RCS brickwork circuits at n in {20, 24, 26}, depths {4, 8, 12, 16}.
- Per circuit: ONE `cpu` job (exact sampler, 5000 shots) + ONE `mps.cpu`
  job chi=64 (approximate sampler, 5000 shots). 40 jobs total.
- XEB of each sampler vs exact local truth; every point carries its job ID.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

EXP = "EXP-001-G1-TUTORIAL-BASELINE"
SIZES = [20, 24, 26]
DEPTHS = [4, 8, 12, 16]
SHOTS = 5000
CHI = 64
BASE_SEED = 20261006


def main() -> int:
    from bq import get_client, run_batch, RoundSpec
    from circuits import rcs_circuit, measure_all, save_circuit
    from sim_exact import precompute_suite
    from metrics import xeb_normalized, xeb_linear
    from plots import g1_plot

    client = get_client()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"{stamp}_g1"
    run_dir.mkdir(parents=True, exist_ok=True)
    truth_dir = run_dir / "truth"
    truth_dir.mkdir(exist_ok=True)

    circuits_meta = []
    jobs_local = []
    for n in SIZES:
        for d in DEPTHS:
            seed = BASE_SEED + n * 100 + d
            qc = rcs_circuit(n, d, seed=seed)
            cpath = run_dir / f"rcs_n{n}_d{d}_s{seed}.qpy"
            sha = save_circuit(qc, cpath)
            ppath = truth_dir / f"p_n{n}_d{d}_s{seed}.npy"
            circuits_meta.append({"n": n, "depth": d, "seed": seed,
                                  "qpy": cpath.name, "sha256": sha,
                                  "prob": str(ppath.relative_to(ROOT))})
            jobs_local.append((str(cpath), str(ppath)))

    # exact truth in a BACKGROUND thread (cloud jobs dispatch meanwhile);
    # per-size worker counts cap peak RSS (~3.2 GB/worker at 26q) under 14 GB RAM
    import threading
    workers_for = {20: 6, 24: 4, 26: 3}

    def _precompute_all():
        for n in SIZES:
            sub = [p for p in jobs_local if f"_n{n}_" in pathlib.Path(p[0]).name]
            precompute_suite(sub, workers=workers_for[n])
            print(f"[g1] exact truth done for n={n}", flush=True)

    truth_thread = threading.Thread(target=_precompute_all, name="truth", daemon=True)
    truth_thread.start()
    print(f"[g1] exact ground truth precompute launched in background "
          f"({len(jobs_local)} circuits)", flush=True)

    specs_cpu, specs_mps = [], []
    for m in circuits_meta:
        n, d = m["n"], m["depth"]
        qc = rcs_circuit(n, d, seed=m["seed"])
        specs_cpu.append(RoundSpec(measure_all(qc), shots=SHOTS, options=None,
                                   label=f"g1-cpu-n{n}-d{d}"))
        specs_mps.append(RoundSpec(measure_all(qc), shots=SHOTS,
                                   options={"mps_bond_dimension": CHI},
                                   label=f"g1-mps-n{n}-d{d}"))

    res_cpu = run_batch(client, EXP, "cpu-exact-sampler", specs_cpu,
                        device="cpu", max_concurrent=2)
    res_mps = run_batch(client, EXP, "mps-chi64-sampler", specs_mps,
                        device="mps.cpu", max_concurrent=2)
    print("[g1] cloud batches collected; waiting for exact truth…", flush=True)
    truth_thread.join(timeout=3600)
    if truth_thread.is_alive():
        print("FAIL: exact-truth precompute still running after 60 min", flush=True)
        return 2

    by_label = {}
    for r in list(res_cpu["jobs"].values()) + list(res_mps["jobs"].values()):
        by_label[r["job"].job_name] = r

    rows = []
    total_usd = 0.0
    total_jobs = 0
    for m in circuits_meta:
        n, d = m["n"], m["depth"]
        import numpy as np
        p_arr = np.load(ROOT / m["prob"], mmap_mode="r")
        lookup = lambda b: float(p_arr[int(b, 2)])  # noqa: E731
        row = dict(m)
        for lane, label in (("cpu", f"g1-cpu-n{n}-d{d}"), ("mps64", f"g1-mps-n{n}-d{d}")):
            r = by_label.get(label)
            if r is None or r["counts"] is None:
                row[f"{lane}_job_id"] = None
                row[f"{lane}_xeb"] = None
                row[f"{lane}_error"] = (r["job"].error_message if r else "missing")
                continue
            row[f"{lane}_job_id"] = r["job"].job_id
            row[f"{lane}_xeb"] = round(xeb_normalized(r["counts"], p_arr), 5)
            row[f"{lane}_xeb_raw"] = round(xeb_linear(r["counts"], lookup), 5)
            row[f"{lane}_run_ms"] = r["job"].run_time_ms
            row[f"{lane}_queue_ms"] = r["job"].queue_time_ms
            row[f"{lane}_cost_usd"] = r["job"].cost
            total_usd += r["job"].cost or 0.0
            total_jobs += 1
        rows.append(row)
        print(f"n={n} d={d}: XEB cpu={row.get('cpu_xeb')} mps64={row.get('mps64_xeb')}",
              flush=True)

    (run_dir / "metrics.json").write_text(json.dumps({
        "gate": "G1", "exp": EXP, "shots": SHOTS, "chi": CHI, "rows": rows,
        "jobs": total_jobs, "usd": round(total_usd, 4),
        "reservations": [res_cpu["reservation"], res_mps["reservation"]],
    }, indent=2))
    try:
        from plots import g1_plot
        g1_plot(rows, run_dir / "xeb_vs_depth.png")
        print(f"plot -> {run_dir / 'xeb_vs_depth.png'}")
    except Exception as e:
        print(f"plot failed (non-fatal): {e}")

    ok = all(r.get("cpu_xeb") is not None and r.get("mps64_xeb") is not None
             for r in rows)
    print(f"\nG1 {'PASS' if ok else 'PARTIAL'} -> {run_dir}/metrics.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
