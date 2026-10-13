"""BlueQubit client wrapper implementing the lifecycle contract.

freeze (caller) -> reserve -> dispatch ONCE -> collect -> validate -> decide.
Ambiguous acknowledgments are reconciled via job-name search, never resubmitted.
Scientific libs allowed here (bluequbit SDK, qiskit).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import bq_jobs  # stdlib, tools/

_ENV_LOADED = False
_LOADED_ACCOUNT = None
_ANNOUNCED = False


def load_env() -> None:
    global _ENV_LOADED, _LOADED_ACCOUNT
    if _ENV_LOADED and os.environ.get("BQ_ACCOUNT", "test") == _LOADED_ACCOUNT:
        return
    env_path = ROOT.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    # BQ_ACCOUNT=personal opts into the personal key for the Oct 11 canonical
    # run — accepted under either name, BLUEQUBIT_API_KEY_PERSONAL or
    # BLUEQUBIT_API_KEY_ACCOUNT_PROD (the name used in .env since 2026-10-07);
    # anything else stays on the TEST key, so a personal key can never leak
    # into a TEST-session run. Fails CLOSED: if the selected account's key is
    # missing, an ambient BLUEQUBIT_API_TOKEN is removed and never used.
    account = os.environ.get("BQ_ACCOUNT", "test")
    if account == "personal":
        var_names = ("BLUEQUBIT_API_KEY_PERSONAL", "BLUEQUBIT_API_KEY_ACCOUNT_PROD")
    else:
        var_names = ("BLUEQUBIT_API_KEY_ACCOUNT_TEST",)
    token = next((os.environ[n] for n in var_names if os.environ.get(n)), None)
    if not token:
        os.environ.pop("BLUEQUBIT_API_TOKEN", None)
        raise SystemExit(
            f"[bq] BQ_ACCOUNT={account}: no API key found under "
            f"{' or '.join(var_names)} (checked .env at {env_path} and the "
            "environment) — refusing to run. Key NAMES only are logged, "
            "never values.")
    os.environ["BLUEQUBIT_API_TOKEN"] = token
    _LOADED_ACCOUNT = account
    _ENV_LOADED = True


def account_label() -> str:
    load_env()
    account = os.environ.get("BQ_ACCOUNT", "test")
    token = os.environ.get("BLUEQUBIT_API_TOKEN", "")
    return (f"account={account} key=…{token[-4:]}" if token
            else f"account={account} key=NONE")


def get_client():
    global _ANNOUNCED
    load_env()
    if not _ANNOUNCED:
        print(f"[bq] {account_label()}", flush=True)
        _ANNOUNCED = True
    from bluequbit import BQClient

    return BQClient()


class RoundSpec:
    """One circuit submission within a reservation."""

    def __init__(self, circuit, *, shots: int | None, options: dict | None,
                 label: str, pauli_sum=None):
        self.circuit = circuit
        self.shots = shots
        self.options = options
        self.label = label
        self.pauli_sum = pauli_sum


def _search_by_name(client, job_name: str, limit_minutes: int = 120):
    """Reconcile an ambiguous ack: find jobs by exact name (our idempotency tag).

    120-min window so a relaunched experiment ADOPTS its earlier same-named
    jobs (completed or still running) instead of resubmitting them.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=limit_minutes)
    try:
        found = client.search(created_later_than=cutoff)
    except Exception:
        return []
    return [j for j in found if j.job_name == job_name]


def run_batch(client, exp_id: str, purpose: str, specs: list[RoundSpec],
              device: str = "mps.cpu", max_concurrent: int = 2,
              poll_timeout_s: float = 900.0, job_name_prefix: str = "",
              planned_usd: float = 0.0, dry_run: bool = False) -> dict:
    """Reserve once for the whole batch, dispatch at most max_concurrent at a time,
    collect + record each job, then settle. Returns {'jobs': [...], 'counts': [...]}."""
    con = bq_jobs.connect()
    total_shots = sum(s.shots or 0 for s in specs)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    idem = f"{exp_id}-{purpose}-{stamp}".lower().replace(".", "-").replace("_", "-")
    reservation = bq_jobs.reserve(con, idem, exp_id, purpose, device,
                                  planned_jobs=len(specs), planned_shots=total_shots,
                                  planned_usd=planned_usd)
    if dry_run:
        return {"reservation": idem, "jobs": []}

    from qiskit import qasm2  # noqa: F401  (ensures qiskit import surface)

    dispatched: list[dict] = []
    pending: list[RoundSpec] = list(specs)
    in_flight: dict[str, RoundSpec] = {}
    results: dict[str, dict] = {}
    error: Exception | None = None
    try:
        while pending or in_flight:
            while pending and len(in_flight) < max_concurrent:
                spec = pending.pop(0)
                name = f"{job_name_prefix}{spec.label}"[:200]
                # ambiguous-ack reconciliation: if a job with this exact name
                # already exists from the last minutes, adopt it, never resubmit
                existing = _search_by_name(client, name)
                if existing:
                    jr = client.get(existing[-1].job_id)
                else:
                    try:
                        jr = client.run(spec.circuit, device=device, shots=spec.shots,
                                        asynchronous=True, job_name=name,
                                        options=spec.options, pauli_sum=spec.pauli_sum)
                    except Exception as e:
                        # fail-fast server-side validation rejects some jobs
                        # synchronously; record and continue with the batch
                        m = __import__("re").search(r"Job (\S+) finished", str(e))
                        jid = m.group(1) if m else None
                        jr = None
                        if jid:
                            try:
                                jr = client.get(jid)
                            except Exception:
                                jr = None
                        pseudo = type("J", (), {})()
                        pseudo.job_id = jid
                        pseudo.job_name = name
                        pseudo.run_status = getattr(jr, "run_status", "SUBMIT_FAILED")
                        pseudo.error_message = str(e)[:300]
                        pseudo.queue_time_ms = getattr(jr, "queue_time_ms", None)
                        pseudo.run_time_ms = getattr(jr, "run_time_ms", None)
                        pseudo.cost = getattr(jr, "cost", None)
                        pseudo.expectation_value = getattr(jr, "expectation_value", None)
                        pseudo.ok = False
                        if jid:
                            bq_jobs.record_job(con, jid, idempotency_key=None, exp_id=exp_id,
                                               device=device, n_qubits=spec.circuit.num_qubits,
                                               shots=spec.shots, options=spec.options,
                                               job_name=name,
                                               submitted_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                               collected_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                               run_status=pseudo.run_status,
                                               run_time_ms=None, queue_time_ms=None,
                                               cost_usd=None, estimated_cost_usd=None,
                                               error=pseudo.error_message)
                            bq_jobs.append_job_id(con, idem, jid)
                        results[jid or f"failed-{len(results)}"] = {
                            "job": pseudo, "spec": spec, "counts": None}
                        continue
                if jr.job_id is None:
                    raise RuntimeError(f"no job id returned for {name} (ambiguous ack)")
                bq_jobs.record_job(con, jr.job_id, idempotency_key=None, exp_id=exp_id,
                                   device=device, n_qubits=spec.circuit.num_qubits,
                                   shots=spec.shots, options=spec.options, job_name=name,
                                   submitted_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                   collected_at=None, run_status=jr.run_status,
                                   run_time_ms=None, queue_time_ms=None,
                                   cost_usd=None, estimated_cost_usd=jr.estimated_cost,
                                   error=None)
                bq_jobs.append_job_id(con, idem, jr.job_id)
                dispatched.append({"job_id": jr.job_id, "name": name})
                in_flight[jr.job_id] = spec
                time.sleep(0.5)
            # wait for at least one in-flight job to finish
            job_ids = list(in_flight)
            done = None
            try:
                done = client.wait(job_ids, timeout=poll_timeout_s)
            except TimeoutError as e:
                for jid in getattr(e, "job_ids", []) or []:
                    client.cancel(jid)
                raise
            except Exception:
                # a watched job failed terminally server-side (e.g.
                # FAILED_VALIDATION); poll individually and harvest every job
                # that is in a terminal state, failed or not
                from bluequbit.job_metadata_constants import \
                    JOB_NON_TERMINAL_STATES
                done = []
                for jid in job_ids:
                    try:
                        jr = client.get(jid)
                    except Exception:
                        continue
                    if jr.run_status not in JOB_NON_TERMINAL_STATES:
                        done.append(jr)
                if not done:
                    raise
            done_list = done if isinstance(done, list) else [done]
            for jr in done_list:
                spec = in_flight.pop(jr.job_id)
                counts = None
                if jr.ok:
                    try:
                        counts = jr.get_counts()
                    except Exception:
                        # observable-only jobs (pauli_sum, no shots) carry no counts
                        counts = None
                bq_jobs.record_job(con, jr.job_id, idempotency_key=idem, exp_id=exp_id,
                                   device=device, n_qubits=spec.circuit.num_qubits,
                                   shots=spec.shots, options=spec.options,
                                   job_name=jr.job_name,
                                   submitted_at=None,
                                   collected_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                   run_status=jr.run_status, run_time_ms=jr.run_time_ms,
                                   queue_time_ms=jr.queue_time_ms, cost_usd=jr.cost,
                                   estimated_cost_usd=jr.estimated_cost,
                                   error=jr.error_message)
                results[jr.job_id] = {"job": jr, "spec": spec, "counts": counts}
        total_usd = sum(r["job"].cost or 0.0 for r in results.values())
        verdict = bq_jobs.settle(con, idem, actual_jobs=len(results),
                                 actual_shots=total_shots, actual_usd=total_usd)
        return {"reservation": idem, "jobs": results, "settle": verdict}
    except Exception as exc:  # noqa: BLE001 — reservation hygiene on any failure
        error = exc
        remaining = [jid for jid in in_flight]
        if remaining:
            try:
                client.cancel(remaining)
            except Exception:
                pass
        bq_jobs.settle(con, idem, actual_jobs=len(results),
                       actual_shots=0, actual_usd=0.0,
                       note=f"FAILED: {type(exc).__name__}: {exc}"[:300])
        raise
