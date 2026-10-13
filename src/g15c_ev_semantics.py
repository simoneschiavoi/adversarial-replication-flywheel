"""G1.5c — EV semantics + usable-epsilon window probe (follow-up to EXP-002B).

The G1.5b screen found: eps=1e-5 -> FAILED_VALIDATION (server: memory overflow)
on every (n, d) in {32,40,56}x{8,16}; eps=1e-3 -> COMPLETED in ~0.05 min with
EV exactly 0.0 on a weight-n/2 Z-string. Either all paths were truncated (H1)
or the pauli_sum pipeline is not doing what we think (H2).

This probe separates them with local ground truth at 20q, where the exact EV is
computable locally, and maps the usable (weight, eps) window at 32q:

  A. n=20 d=8 RCS, weight-10 random Pauli string, eps in {1e-5, 3e-5, 1e-4, 1e-3}
     -> compare cloud EV to local exact EV (both label orders, convention check)
  B. n=32 d=8 RCS, weight-4 string,  eps in {1e-5, 1e-4, 1e-3}
  C. n=32 d=8 RCS, weight-8 string,  eps in {1e-4, 3e-4}

Jobs: 9 pauli-path, $0 expected. Read-only wrt the ledger (recorded as part of
the EXP-002B attempt trail via metrics.json in its run dir, no new gates).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

EXP = "EXP-002B-G15B-PIVOT-SCREEN"  # same experiment; this is the follow-up probe
SEED = 20261300


def random_label(n: int, weight: int, seed: int) -> str:
    import numpy as np
    rng = np.random.default_rng(seed)
    sites = rng.choice(n, size=weight, replace=False)
    chars = rng.choice(list("XYZ"), size=weight)
    label = ["I"] * n
    for s, c in zip(sites, chars):
        label[s] = str(c)
    return "".join(label)


def main() -> int:
    from bq import get_client, run_batch, RoundSpec
    from circuits import rcs_circuit, save_circuit, load_circuit

    client = get_client()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "runs" / f"{stamp}_g15c"
    out_dir.mkdir(parents=True, exist_ok=True)

    probes = []
    # A: 20q with local exact EV
    qc20 = rcs_circuit(20, 8, seed=SEED)
    p20 = out_dir / "rcs_n20_d8.qpy"
    save_circuit(qc20, p20)
    lab20 = random_label(20, 10, SEED + 1)
    from qiskit.quantum_info import SparsePauliOp, Statevector
    exact = float(Statevector.from_instruction(qc20).expectation_value(
        SparsePauliOp(lab20)).real)
    exact_rev = float(Statevector.from_instruction(qc20).expectation_value(
        SparsePauliOp(lab20[::-1])).real)
    print(f"[A] n=20 label={lab20} exact={exact:+.6f} exact_rev={exact_rev:+.6f}")
    for eps in (1e-5, 3e-5, 1e-4, 1e-3):
        probes.append({"tag": "A20-w10", "n": 20, "weight": 10, "eps": eps,
                       "qpy": p20, "label": lab20,
                       "exact": exact, "exact_rev": exact_rev})
    # B: 32q weight 4
    qc32 = rcs_circuit(32, 8, seed=SEED + 2)
    p32 = out_dir / "rcs_n32_d8.qpy"
    save_circuit(qc32, p32)
    lab4 = random_label(32, 4, SEED + 3)
    lab8 = random_label(32, 8, SEED + 4)
    for eps in (1e-5, 1e-4, 1e-3):
        probes.append({"tag": "B32-w4", "n": 32, "weight": 4, "eps": eps,
                       "qpy": p32, "label": lab4})
    for eps in (1e-4, 3e-4):
        probes.append({"tag": "C32-w8", "n": 32, "weight": 8, "eps": eps,
                       "qpy": p32, "label": lab8})

    from circuits import load_circuit as _lc
    specs, meta = [], []
    for i, t in enumerate(probes):
        lab = f"g15c-{t['tag']}-e{t['eps']:g}"
        specs.append(RoundSpec(
            _lc(t["qpy"]), shots=None, pauli_sum=[(t["label"], 1.0)],
            options={"pauli_path_truncation_threshold": t["eps"]}, label=lab))
        meta.append({"i": i, "label": lab, **{k: t[k] for k in
                                               ("tag", "n", "weight", "eps")}})

    res = run_batch(client, EXP, "g15c", specs, device="pauli-path",
                    max_concurrent=1)
    rows = []
    for m in meta:
        r = next((v for v in res["jobs"].values() if v["job"].job_name == m["label"]),
                 None)
        job = r["job"] if r else None
        ev = job.expectation_value if job else None
        wall = ((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000 if job else None
        row = {**m, "job_id": job.job_id if job else None,
               "status": job.run_status if job else "MISSING",
               "ev": ev, "wall_min": round(wall, 4) if wall else None,
               "cost_usd": job.cost if job else None,
               "error": job.error_message if job else "no result"}
        if ev is not None and "exact" in m:
            row["abs_err_qiskit_order"] = abs(ev - m["exact"])
            row["abs_err_reversed_order"] = abs(ev - m["exact_rev"])
        rows.append(row)
        print(f"  {m['label']}: {row['status']} ev={ev} "
              f"err_qiskit={row.get('abs_err_qiskit_order')}")

    completed = [r for r in rows if r["status"] == "COMPLETED"]
    nonzero = [r for r in completed if r["ev"] not in (None, 0.0)]
    ev_pipeline_ok = False
    conv = None
    for r in completed:
        if "abs_err_qiskit_order" in r:
            if r["abs_err_qiskit_order"] < 1e-3:
                ev_pipeline_ok, conv = True, "qiskit"
                break
            if r["abs_err_reversed_order"] < 1e-3:
                ev_pipeline_ok, conv = True, "reversed"
                break
    if not ev_pipeline_ok and nonzero:
        # pipeline returns nonzero EVs but none match exact at 20q -> H2 variant
        ev_pipeline_ok = "NONZERO_BUT_NO_MATCH"
    window = [{k: r[k] for k in ("tag", "weight", "eps", "status",
                                 "ev", "wall_min")} for r in rows]
    verdict = {
        "gate": "G1.5c", "ev_pipeline_ok": ev_pipeline_ok,
        "label_convention": conv, "window": window,
        "h1_truncation_zero_ev": len(completed) > 0 and not nonzero,
        "jobs": len(rows),
        "usd": round(sum((r.get("cost_usd") or 0) for r in rows if r.get("cost_usd")), 4),
        "decided_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps(
        {"gate": "G1.5c", "exp": EXP, "rows": rows, **verdict}, indent=2))
    print(json.dumps({k: verdict[k] for k in
                      ("ev_pipeline_ok", "label_convention",
                       "h1_truncation_zero_ev")}, indent=1))
    print(f"-> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
