"""Oct-11 re-probe of the three platform findings on the PERSONAL account.

1. Peaked endpoint: SDK get_peaked_circuit at difficulties {1,3,5,7,9,10}.
   TEST 2026-10-06: HTTP 403 "Access denied for this endpoint" at every
   difficulty (EXP-002 parked, EXTERNAL_ENDPOINT_DENIED).
2. mps.cpu count-key order: ONE $0 job — rcs_n20_d4_s20263010 (the TEST
   evidence circuit), chi=256, 20k shots — scored raw vs canonical (reversed).
   Raw << 1 and reversed ~ 1 confirms the bit-reversed key convention on this
   account/SDK version; metrics.canonical_counts relies on it.
3. pauli-path degeneracy on random RCS: NOT re-probed (no budget
   re-litigation). TEST evidence cited: job tjiUQT7ynMGEAdix — eps >= 1e-4
   RUNS but returns EV exactly 0.0 (empty retained path set) on 20q weight-10,
   exact = -0.001112; eps <= 1e-5 rejected server-side.

Runs under EXP-002-G15-FEASIBILITY (caps only). Requires BQ_ACCOUNT=personal.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    import os

    if os.environ.get("BQ_ACCOUNT") != "personal":
        raise SystemExit("refusing: BQ_ACCOUNT != personal (probe must hit the "
                         "PERSONAL account)")

    import bq
    from circuits import rcs_circuit, measure_all
    from metrics import xeb_normalized

    client = bq.get_client()  # prints the [bq] announce; fails closed on key

    # --- 1. peaked endpoint -------------------------------------------------
    peaked: dict[str, dict] = {}
    for diff in (1, 3, 5, 7, 9, 10):
        try:
            pc = client.get_peaked_circuit(diff)
            peaked[f"difficulty_{diff}"] = {
                "ok": True, "circuit_name": getattr(pc.circuit, "name", None),
                "metadata": str(getattr(pc, "metadata", None))[:200]}
        except Exception as e:  # noqa: BLE001 — the probe RECORDS the failure
            peaked[f"difficulty_{diff}"] = {"ok": False, "error": str(e)[:300]}
    peaked_any = any(v.get("ok") for v in peaked.values())

    # --- 2. mps bit-reverse sanity (one $0 job) ------------------------------
    qc = rcs_circuit(20, 4, 20263010)
    from qiskit.quantum_info import Statevector
    p = np.abs(Statevector.from_instruction(qc).data) ** 2
    p = p.astype(np.float64)

    from bq import run_batch, RoundSpec
    specs = [RoundSpec(measure_all(qc), shots=20000,
                       options={"mps_bond_dimension": 256},
                       label="reprobe-rcs_n20_d4_s20263010")]
    res = run_batch(client, "EXP-002-G15-FEASIBILITY", "reprobe-bitreverse",
                    specs, device="mps.cpu", max_concurrent=1)
    r = next(iter(res["jobs"].values()))
    job = r["job"]
    counts = r["counts"]
    raw_xeb = xeb_normalized(counts, p) if counts else None
    canon_xeb = xeb_normalized({k[::-1]: v for k, v in counts.items()}, p) \
        if counts else None
    bitreverse_ok = bool(
        counts and canon_xeb is not None and raw_xeb is not None
        and canon_xeb > 0.9 and raw_xeb < 0.5 * canon_xeb)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"{stamp}_g15reprobe"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "peaked_probe.json").write_text(json.dumps(peaked, indent=2))
    np.save(run_dir / "p_rcs_n20_d4_s20263010.npy", p)
    metrics = {
        "gate": "Oct11-reprobe", "exp": "EXP-002-G15-FEASIBILITY",
        "account": bq.account_label(), "utc": utcnow(),
        "peaked_any_success": peaked_any,
        "mps_bitreverse": {
            "job_id": job.job_id, "run_status": job.run_status,
            "cost_usd": job.cost,
            "run_time_ms": job.run_time_ms, "queue_time_ms": job.queue_time_ms,
            "xeb_raw_key_order": None if raw_xeb is None else round(raw_xeb, 6),
            "xeb_canonical_reversed": None if canon_xeb is None else round(canon_xeb, 6),
            "confirmed": bitreverse_ok,
        },
        "pauli_path_degeneracy": {
            "reprobed": False,
            "cited_test_evidence": {
                "job_id": "tjiUQT7ynMGEAdix",
                "finding": "eps>=1e-4 runs but returns EV exactly 0.0 (empty "
                           "retained path set) on 20q weight-10 random RCS; "
                           "eps<=1e-5 rejected server-side; exact = -0.001112"},
        },
    }
    metrics["verdict"] = {
        "peaked_endpoint": ("AVAILABLE" if peaked_any
                            else "DENIED (403 — replicates TEST finding)"),
        "mps_bit_reverse": ("CONFIRMED" if bitreverse_ok else "CHECK MANUALLY"),
        "pauli_degeneracy": "CITED (TEST evidence, not re-probed)",
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (run_dir / "verdict.json").write_text(json.dumps(metrics["verdict"], indent=2))

    out = subprocess.run(
        [".venv/bin/python", "tools/ledger.py", "record",
         "EXP-002-G15-FEASIBILITY", str(run_dir)],
        cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"FAIL record EXP-002: {out.stdout}{out.stderr}")

    print(json.dumps(metrics["verdict"], indent=2))
    print(f"run_dir: {run_dir}")
    print("probe mps job:", job.job_id, job.run_status,
          f"cost={job.cost} raw={raw_xeb} canon={canon_xeb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
