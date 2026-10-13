"""G0 smoke test: 4-qubit GHZ on the `cpu` device, end-to-end.

Records: wall-clock, queue behavior, API host, job-id round-trip, submitted-vs-billed cost.
Writes runs/<stamp>_g0/metrics.json. Hard gate: failing this stops the campaign.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> str:
    env_path = ROOT.parent / ".env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    token = os.environ.get("BLUEQUBIT_API_KEY_ACCOUNT_TEST")
    if not token:
        raise SystemExit("BLUEQUBIT_API_KEY_ACCOUNT_TEST not found in .env")
    os.environ["BLUEQUBIT_API_TOKEN"] = token
    return token


def main() -> int:
    load_env()
    import bluequbit
    from bluequbit import BQClient
    from qiskit import QuantumCircuit

    client = BQClient()  # reads BLUEQUBIT_API_TOKEN

    qc = QuantumCircuit(4, 4)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    qc.cx(2, 3)
    qc.measure(range(4), range(4))

    t0 = time.time()
    result = client.run(qc, device="cpu", shots=512, job_name="g0-smoke-ghz")
    t_submit_to_result = time.time() - t0

    # job-id round trip: submit -> get(job_id) -> search by job id
    got = client.get(result.job_id)
    round_trip_ok = got.job_id == result.job_id and got.run_status == "COMPLETED"

    counts = result.get_counts()
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
    ghz_mass = sum(c for b, c in counts.items() if b in ("0000", "1111")) / sum(
        counts.values()
    )

    metrics = {
        "gate": "G0",
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sdk_version": bluequbit.__version__,
        "api_endpoint": "https://app.bluequbit.io/api/v1",
        "job_id": result.job_id,
        "job_name": result.job_name,
        "device": result.device,
        "run_status": result.run_status,
        "job_id_round_trip_ok": round_trip_ok,
        "wall_clock_submit_to_result_s": round(t_submit_to_result, 3),
        "queue_time_ms": result.queue_time_ms,
        "run_time_ms": result.run_time_ms,
        "estimated_runtime_ms": result.estimated_runtime,
        "estimated_cost_usd": result.estimated_cost,
        "billed_cost_usd": result.cost,
        "shots": result.shots,
        "num_qubits": result.num_qubits,
        "top_counts": dict(top),
        "ghz_probability_mass": round(ghz_mass, 6),
        "device_options": result.device_options,
        "run_results": result.run_results,
    }

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"{stamp}_g0"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    passed = (
        round_trip_ok
        and result.run_status == "COMPLETED"
        and ghz_mass > 0.90
        and metrics["billed_cost_usd"] is not None
    )
    metrics["G0_PASS"] = passed
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    print("\nG0:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
