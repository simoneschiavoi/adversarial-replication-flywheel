"""G1.5b — pivot feasibility screen (Lane P sponsor-peaked endpoint is 403-denied
on this account; see EXP-002 park note). New attack lane under test:

  Lane Q: LOCAL RCS brickwork at 30-56q, observable estimation on `pauli-path`,
          scored by |EV - EV_ref| with the frozen basis EV_ref = pauli-path at
          epsilon = 1e-5 (tightest supported threshold).
  Lane R (unchanged): exact-truth XEB <= 26q on mps.cpu (chi mutation family).

This screen times, on real jobs:
  1. pauli-path at eps in {1e-5, 1e-3} on n in {32, 40, 56} x depth in {8, 16}
  2. mps.cpu chi in {64, 256} at n=56 d=16 (telemetry feasibility at scale)
Verdict: envelope_ok = every pauli-path job wall <= 5 min (3x headroom under
the 15-min cap). If a size is too slow, freeze shrinks to the sizes that pass.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

EXP = "EXP-002B-G15B-PIVOT-SCREEN"
SIZES = [32, 40, 56]
DEPTHS = [8, 16]
BASE_SEED = 20261200


def main() -> int:
    from bq import get_client, run_batch, RoundSpec
    from circuits import rcs_circuit, save_circuit

    client = get_client()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "runs" / f"{stamp}_g15b"
    out_dir.mkdir(parents=True, exist_ok=True)

    circs = []
    for n in SIZES:
        for d in DEPTHS:
            seed = BASE_SEED + n * 100 + d
            qc = rcs_circuit(n, d, seed=seed)
            path = out_dir / f"rcs_n{n}_d{d}_s{seed}.qpy"
            sha = save_circuit(qc, path)
            twoq = sum(1 for i in qc.data if len(i.qubits) == 2)
            circs.append({"n": n, "depth": d, "seed": seed, "sha256": sha,
                          "two_qubit_gates": twoq, "qpy": path})
            print(f"minted n={n} d={d} 2q_gates={twoq}")

    # ---- pauli-path timing at two epsilons -----------------------------------
    # observable: Z on every even site (label in qiskit order, length n)
    pp = []
    for c in circs:
        zlabel = "".join("Z" if i % 2 == 0 else "I" for i in range(c["n"]))
        for eps in (1e-5, 1e-3):
            specs = [RoundSpec(
                load_free(c), shots=None,
                pauli_sum=[(zlabel, 1.0)],
                options={"pauli_path_truncation_threshold": eps},
                label=f"g15b-pp-n{c['n']}-d{c['depth']}-e{eps:g}")]
            try:
                res = run_batch(client, EXP, "ppscreen", specs,
                                device="pauli-path", max_concurrent=2)
                r = next(iter(res["jobs"].values()))
                job = r["job"]
                wall = ((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000
                pp.append({"n": c["n"], "depth": c["depth"], "eps": eps,
                           "job_id": job.job_id, "run_status": job.run_status,
                           "wall_min": round(wall, 3),
                           "ev": job.expectation_value,
                           "cost_usd": job.cost,
                           "error": job.error_message})
                print(f"  pp n={c['n']} d={c['depth']} eps={eps:g}: "
                      f"{job.run_status} wall={wall:.2f}m ev={job.expectation_value}")
            except Exception as e:
                pp.append({"n": c["n"], "depth": c["depth"], "eps": eps,
                           "error": f"{type(e).__name__}: {e}"[:200]})
                print(f"  pp n={c['n']} d={c['depth']} eps={eps:g}: ERROR {e}")

    # ---- mps.cpu telemetry feasibility at 56q ---------------------------------
    mps = []
    big = [c for c in circs if c["n"] == 56 and c["depth"] == 16][0]
    from circuits import measure_all
    for chi in (64, 256):
        specs = [RoundSpec(measure_all(load_free(big)), shots=20000,
                           options={"mps_bond_dimension": chi},
                           label=f"g15b-mps-n56-d16-chi{chi}")]
        try:
            res = run_batch(client, EXP, "mpsscreen", specs,
                            device="mps.cpu", max_concurrent=1)
            r = next(iter(res["jobs"].values()))
            job = r["job"]
            wall = ((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000
            mps.append({"n": 56, "depth": 16, "chi": chi, "job_id": job.job_id,
                        "run_status": job.run_status, "wall_min": round(wall, 3),
                        "cost_usd": job.cost, "error": job.error_message})
            print(f"  mps n=56 d=16 chi={chi}: {job.run_status} wall={wall:.2f}m")
        except Exception as e:
            mps.append({"chi": chi, "error": f"{type(e).__name__}: {e}"[:200]})
            print(f"  mps n=56 d=16 chi={chi}: ERROR {e}")

    # ---- verdict ---------------------------------------------------------------
    ok_pp = [t for t in pp if t.get("run_status") == "COMPLETED"]
    envelope_ok = bool(ok_pp) and all(t["wall_min"] <= 5.0 for t in ok_pp) \
        and len(ok_pp) == len(pp)
    # sizes usable for the freeze = every (size, depth) completed <= 5 min at eps_ref
    ok_pairs = {(t["n"], t["depth"]) for t in ok_pp
                if t["eps"] == 1e-5 and t["wall_min"] <= 5.0}
    usable_sizes = sorted({n for n, _ in ok_pairs})
    evs = {}
    for t in ok_pp:
        evs.setdefault((t["n"], t["depth"]), {})[f"eps{t['eps']:g}"] = t["ev"]
    eps_signal = any(
        len(v) == 2 and None not in v.values()
        and abs(v["eps1e-05"] - v["eps0.001"]) > 1e-9 for v in evs.values())
    total_usd = round(sum(t.get("cost_usd") or 0 for t in pp + mps), 4)
    verdict = {
        "gate": "G1.5b", "pass": envelope_ok, "envelope_ok": envelope_ok,
        "usable_sizes": usable_sizes, "eps_moves_ev": eps_signal,
        "pauli_path": pp, "mps": mps, "usd": total_usd,
        "jobs": len(pp) + len(mps),
        "pivot_reason": "GET /api/v1/peaked-circuits/file returns 403 "
                        "(Access denied for this endpoint) on the TEST account "
                        "at all difficulties — sponsor peaked lane unavailable; "
                        "Lane Q (pauli-path observables, local RCS 30-56q) tested.",
        "decided_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps({
        "gate": "G1.5b", "exp": EXP, "envelope_ok": envelope_ok,
        "usable_sizes": usable_sizes, "eps_moves_ev": eps_signal,
        "pauli_path": pp, "mps": mps, "usd": total_usd, "jobs": len(pp) + len(mps),
    }, indent=2))
    print(f"\nG1.5b envelope_ok={envelope_ok} usable_sizes={usable_sizes} "
          f"eps_signal={eps_signal} -> {out_dir}")
    return 0 if envelope_ok else 2


def load_free(c):
    from circuits import load_circuit
    return load_circuit(c["qpy"])


if __name__ == "__main__":
    sys.exit(main())
