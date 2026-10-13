"""G1.5 feasibility screen — BEFORE freezing the suite.

1. Probe sponsor peaked circuits: difficulties, sizes, gate counts.
2. Time 2-3 candidate attack jobs on mps.cpu at 30-56q across chi.
3. Measure PPL signal (does MPS sampling lift the peak at all?).
4. Probe pauli-path lane timing on the same circuits.
Verdict: if no attack job completes <= 5 min (3x headroom under the 15-min
cap), we must shrink circuit size/depth BEFORE freezing.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

EXP = "EXP-002-G15-FEASIBILITY"


def main() -> int:
    from bq import get_client, run_batch, RoundSpec
    from circuits import measure_all
    from metrics import ppl

    client = get_client()
    probe = {}

    # --- 1. probe peaked circuit difficulties -------------------------------
    # Also: (a) try explicit circuit_id 0/1 for reproducibility mapping,
    #        (b) at n<=24 verify the server key's bitstring convention against
    #            a LOCAL exact argmax (display order vs reversed).
    from sim_exact import statevector
    for diff in (1, 3, 5, 7, 9, 10):
        try:
            pc = None
            for attempt in (1, 2):  # AMBIGUOUS_ACK-class retry, once
                try:
                    pc = client.get_peaked_circuit(diff, None)
                    break
                except Exception:
                    if attempt == 2:
                        raise
            circ, key, meta = pc.circuit, pc.key, pc.metadata
            entry = {
                "n_qubits": circ.num_qubits,
                "two_qubit_gates": sum(1 for i in circ.data if len(i.qubits) == 2),
                "key_len": len(key),
                "metadata": str(meta),
                "key_prefix": key[:8] + "…",
            }
            # reproducibility map: does an explicit circuit_id work?
            for cid in (0, 1):
                try:
                    pc2 = client.get_peaked_circuit(diff, cid)
                    entry[f"circuit_id_{cid}"] = {
                        "n_qubits": pc2.circuit.num_qubits,
                        "same_as_random": pc2.qasm_str == pc.qasm_str,
                    }
                except Exception as e:
                    entry[f"circuit_id_{cid}"] = {"error": f"{type(e).__name__}"[:60]}
            # key convention check vs local exact argmax (small circuits only)
            if circ.num_qubits <= 24:
                try:
                    import numpy as np
                    sv = statevector(circ.remove_final_measurements(inplace=False)
                                     if circ.num_clbits else circ)
                    argmax = format(int(np.argmax(np.abs(sv))), f"0{circ.num_qubits}b")
                    entry["key_convention"] = {
                        "local_argmax": argmax[:16] + "…",
                        "key_equals_argmax_display_order": key == argmax,
                        "key_equals_argmax_reversed": key == argmax[::-1],
                    }
                except Exception as e:
                    entry["key_convention"] = {"error": f"{type(e).__name__}: {e}"[:120]}
            probe[f"difficulty_{diff}"] = entry
            print(f"difficulty {diff}: n={circ.num_qubits} 2q={entry['two_qubit_gates']} "
                  f"meta={str(meta)[:60]}")
        except Exception as e:
            probe[f"difficulty_{diff}"] = {"error": f"{type(e).__name__}: {e}"[:200]}
            print(f"difficulty {diff}: FAILED {e}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "runs" / f"{stamp}_g15"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "peaked_probe.json").write_text(json.dumps(probe, indent=2))

    # pick difficulties that exist and span sizes for the timing screen
    cands = [d for d in (1, 3, 5, 7, 9, 10) if probe.get(f"difficulty_{d}", {}).get("n_qubits")]
    if not cands:
        print("NO peaked circuits available — screen cannot run the attack lane")
        (out_dir / "verdict.json").write_text(json.dumps({
            "gate": "G1.5", "pass": False,
            "reason": "get_peaked_circuit unavailable at all difficulties",
        }, indent=2))
        return 1

    # --- 2+3. time MPS attack jobs across chi, measure PPL ------------------
    timings = []
    for diff in cands[:3]:  # 2-3 candidate attack jobs per the spec
        circ, key, _ = _fetch(client, diff)
        measured = measure_all(circ)
        for chi in (16, 64, 256):
            specs = [RoundSpec(measured, shots=20000,
                               options={"mps_bond_dimension": chi},
                               label=f"g15-d{diff}-chi{chi}")]
            try:
                res = run_batch(client, EXP, "screen", specs, device="mps.cpu")
                r = list(res["jobs"].values())[0]
                job = r["job"]
                p = ppl(r["counts"], key) if r["counts"] else float("nan")
                wall_min = ((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000
                timings.append({
                    "difficulty": diff, "n_qubits": circ.num_qubits, "chi": chi,
                    "job_id": job.job_id, "run_status": job.run_status,
                    "queue_ms": job.queue_time_ms, "run_ms": job.run_time_ms,
                    "wall_minutes": round(wall_min, 3),
                    "cost_usd": job.cost, "ppl": round(p, 5),
                    "error": job.error_message,
                })
                print(f"  d{diff} chi={chi}: {job.run_status} wall={wall_min:.2f}m ppl={p:.4f} job={job.job_id}")
            except Exception as e:
                timings.append({"difficulty": diff, "chi": chi,
                                "error": f"{type(e).__name__}: {e}"[:200]})
                print(f"  d{diff} chi={chi}: ERROR {e}")

    # --- 4. pauli-path lane probe (observable estimation) -------------------
    pp_timings = []
    for diff in cands[:1]:
        try:
            circ, key, _ = _fetch(client, diff)
            n = circ.num_qubits
            pauli = [("Z" * n, 1.0)]
            res = run_batch(client, EXP, "ppprobe", [RoundSpec(
                circ, shots=None, pauli_sum=pauli,
                options={"pauli_path_truncation_threshold": 1e-5},
                label=f"g15-pp-d{diff}")], device="pauli-path")
            r = list(res["jobs"].values())[0]
            job = r["job"]
            pp_timings.append({"difficulty": diff, "n_qubits": n,
                               "job_id": job.job_id, "run_status": job.run_status,
                               "wall_minutes": round(((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000, 3),
                               "queue_ms": job.queue_time_ms, "run_ms": job.run_time_ms,
                               "expectation_value": job.expectation_value,
                               "cost_usd": job.cost})
            print(f"  pauli-path d{diff}: {job.run_status} ev={job.expectation_value}")
        except Exception as e:
            pp_timings.append({"difficulty": diff,
                               "error": f"{type(e).__name__}: {e}"[:200]})
            print(f"  pauli-path d{diff}: ERROR {e}")

    # --- verdict -------------------------------------------------------------
    ok_jobs = [t for t in timings if t.get("run_status") == "COMPLETED"]
    envelope_ok = bool(ok_jobs) and any(t["wall_minutes"] <= 5.0 for t in ok_jobs)
    ppl_signal = any((t.get("ppl") is not None and t.get("ppl") == t.get("ppl")
                      and t.get("ppl", 0) > 0.005) for t in ok_jobs)
    total_usd = round(sum(t.get("cost_usd") or 0.0 for t in timings)
                      + sum(p.get("cost_usd") or 0.0 for p in pp_timings), 4)
    total_jobs = len(timings) + len(pp_timings)
    verdict = {
        "gate": "G1.5",
        "pass": envelope_ok,
        "envelope_ok": envelope_ok,
        "ppl_signal_seen": ppl_signal,
        "timings": timings,
        "pauli_path": pp_timings,
        "probed_difficulties": probe,
        "usd": total_usd,
        "jobs": total_jobs,
        "decided_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps({
        "gate": "G1.5", "exp": EXP, "envelope_ok": envelope_ok,
        "ppl_signal_seen": ppl_signal, "usd": total_usd, "jobs": total_jobs,
        "timings": timings, "pauli_path": pp_timings,
    }, indent=2))
    print(f"\nG1.5 envelope_ok={envelope_ok} ppl_signal={ppl_signal} -> {out_dir}")
    return 0 if envelope_ok else 2


def _fetch(client, diff):
    pc = client.get_peaked_circuit(diff, None)
    return pc.circuit, pc.key, pc.metadata


if __name__ == "__main__":
    sys.exit(main())
