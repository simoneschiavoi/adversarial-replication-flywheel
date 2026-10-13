"""EXP-009: personal-account (PROD key) smoke test — G0 probe via BQ_ACCOUNT=personal.

Mirrors src/g0_smoke.py exactly (4-qubit GHZ, `cpu` device, 512 shots) but
authenticates through src/bq.py account switching. Writes
runs/<stamp>_g9prod/metrics.json. Hard gate: failing this blocks Oct-11 planning.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    import bq  # src/bq.py: load_env honors BQ_ACCOUNT=personal + ACCOUNT_PROD alias

    bq.load_env()
    account = os.environ.get("BQ_ACCOUNT", "test")
    if account != "personal":
        raise SystemExit("refusing: BQ_ACCOUNT != personal (probe must hit the PERSONAL account)")

    label = bq.account_label()
    print("announce:", label)
    if not label.startswith("account=personal"):
        raise SystemExit(f"account switch failed: {label}")

    # key-distinctness: last-4 only, never the full token
    personal_last4 = (os.environ.get("BLUEQUBIT_API_TOKEN") or "")[-4:]
    test_last4 = (os.environ.get("BLUEQUBIT_API_KEY_ACCOUNT_TEST") or "")[-4:]
    key_distinct = len(personal_last4) == 4 and personal_last4 != test_last4

    import bluequbit
    from qiskit import QuantumCircuit

    client = bq.get_client()

    qc = QuantumCircuit(4, 4)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    qc.cx(2, 3)
    qc.measure(range(4), range(4))

    t0 = time.time()
    result = client.run(qc, device="cpu", shots=512, job_name="exp009-prodsmoke-ghz")
    wall_s = time.time() - t0

    got = client.get(result.job_id)
    round_trip_ok = got.job_id == result.job_id and got.run_status == "COMPLETED"

    counts = result.get_counts()
    ghz_mass = sum(c for b, c in counts.items() if b in ("0000", "1111")) / sum(
        counts.values()
    )
    billed = result.cost

    metrics = {
        "gate": "EXP-009-PROD-KEY-SMOKE",
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "account_label": label,
        "key_last4_distinct_from_test": key_distinct,
        "sdk_version": bluequbit.__version__,
        "job_id": result.job_id,
        "job_name": result.job_name,
        "device": result.device,
        "run_status": result.run_status,
        "job_id_round_trip_ok": round_trip_ok,
        "wall_clock_submit_to_result_s": round(wall_s, 3),
        "queue_time_ms": result.queue_time_ms,
        "run_time_ms": result.run_time_ms,
        "billed_cost_usd": billed,
        "shots": result.shots,
        "num_qubits": result.num_qubits,
        "ghz_probability_mass": round(ghz_mass, 6),
    }

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"{stamp}_g9prod"
    run_dir.mkdir(parents=True, exist_ok=True)

    passed = (
        round_trip_ok
        and result.run_status == "COMPLETED"
        and ghz_mass > 0.90
        and billed is not None
        and billed <= 0.01
        and label.startswith("account=personal")
    )
    metrics["EXP009_PASS"] = passed
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items()}, indent=2))
    print("run_dir:", run_dir)
    print("\nEXP-009:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
