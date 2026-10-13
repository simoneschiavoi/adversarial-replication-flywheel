#!/usr/bin/env python3
"""Transactional job/money store for BlueQubit dispatch (ledger/jobs.sqlite).

Python stdlib only (sqlite3). The BlueQubit SDK is never imported here; this
module only books reservations and facts. The caller in src/ implements the
lifecycle contract:

    freeze -> reserve -> dispatch ONCE -> collect -> validate -> decide

Rules enforced by code:
  * No dispatch without a prior reservation row (atomic check-and-insert in a
    single IMMEDIATE transaction).
  * Idempotency key is persisted at reservation; provider job ids are recorded
    at dispatch; a reservation already marked DISPATCHED can never be
    dispatched again (ambiguous acknowledgment => reconcile via job search,
    never a blind resubmit).
  * Daily quota epoch (UTC date) accounting: combined mps.cpu + pauli-path jobs
    are capped; `cpu` jobs capped separately.
  * Planned-vs-actual $ reconciled at settle; paid-cost drift > 20% raises
    pause_paid flag for the harness to act on.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "ledger" / "jobs.sqlite"

# Plan limits (test account, Standard). Combined mps/pps daily cap below the
# account's 1000 so prototype + rerun both fit; cpu tier is effectively free.
LIMITS = {
    "mps_daily_jobs": 900,
    "cpu_daily_jobs": 5000,
    "usd_budget_total": 2.0,
}
DRIFT_PAUSE = 0.20  # >20% planned-vs-actual drift on paid cost pauses paid dispatch

SCHEMA = """
CREATE TABLE IF NOT EXISTS reservations (
    idempotency_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    exp_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    device TEXT NOT NULL,
    planned_jobs INTEGER NOT NULL,
    planned_shots INTEGER NOT NULL,
    planned_usd REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('RESERVED','DISPATCHED','COLLECTED','SETTLED','FAILED')),
    provider_job_ids TEXT NOT NULL DEFAULT '[]',
    actual_jobs INTEGER,
    actual_shots INTEGER,
    actual_usd REAL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    provider_job_id TEXT PRIMARY KEY,
    idempotency_key TEXT,
    exp_id TEXT NOT NULL,
    device TEXT NOT NULL,
    n_qubits INTEGER,
    shots INTEGER,
    options TEXT,
    job_name TEXT,
    submitted_at TEXT,
    collected_at TEXT,
    run_status TEXT,
    run_time_ms INTEGER,
    queue_time_ms INTEGER,
    cost_usd REAL,
    estimated_cost_usd REAL,
    error TEXT,
    counts_digest TEXT
);
CREATE TABLE IF NOT EXISTS budget_epoch (
    day TEXT PRIMARY KEY,
    mps_jobs_used INTEGER NOT NULL DEFAULT 0,
    cpu_jobs_used INTEGER NOT NULL DEFAULT 0,
    usd_used REAL NOT NULL DEFAULT 0.0,
    usd_reserved REAL NOT NULL DEFAULT 0.0
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def utc_day() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def daily_usage(con: sqlite3.Connection, day: str | None = None) -> dict:
    day = day or utc_day()
    row = con.execute("SELECT * FROM budget_epoch WHERE day=?", (day,)).fetchone()
    if row is None:
        return {"day": day, "mps_jobs_used": 0, "cpu_jobs_used": 0,
                "usd_used": 0.0, "usd_reserved": 0.0}
    return dict(row)


def reserve(con, idempotency_key: str, exp_id: str, purpose: str, device: str,
            planned_jobs: int, planned_shots: int, planned_usd: float = 0.0,
            note: str = "") -> dict:
    """Atomic quota/$ reservation BEFORE submit. Raises SystemExit on any breach."""
    if planned_jobs <= 0:
        raise SystemExit("FAIL: planned_jobs must be >= 1")
    day = utc_day()
    with con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT * FROM reservations WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            con.execute("ROLLBACK")
            if existing["status"] != "RESERVED":
                raise SystemExit(
                    f"FAIL: idempotency key {idempotency_key} already "
                    f"{existing['status']} — reconcile via job search, never resubmit"
                )
            return dict(existing)
        usage = daily_usage(con, day)
        if "mps" in device or "pauli-path" in device:
            if usage["mps_jobs_used"] + planned_jobs > LIMITS["mps_daily_jobs"]:
                raise SystemExit(
                    f"FAIL: mps daily cap {LIMITS['mps_daily_jobs']} would be exceeded "
                    f"({usage['mps_jobs_used']} used, {planned_jobs} planned)"
                )
            mps_delta, cpu_delta = planned_jobs, 0
        else:
            if usage["cpu_jobs_used"] + planned_jobs > LIMITS["cpu_daily_jobs"]:
                raise SystemExit("FAIL: cpu daily cap would be exceeded")
            mps_delta, cpu_delta = 0, planned_jobs
        if usage["usd_used"] + usage["usd_reserved"] + planned_usd > LIMITS["usd_budget_total"]:
            raise SystemExit(
                f"FAIL: $ budget {LIMITS['usd_budget_total']} would be exceeded "
                f"(used {usage['usd_used']}, reserved {usage['usd_reserved']}, planned {planned_usd})"
            )
        con.execute(
            "INSERT INTO reservations (idempotency_key, created_at, exp_id, purpose, device,"
            " planned_jobs, planned_shots, planned_usd, status) VALUES (?,?,?,?,?,?,?,?, 'RESERVED')",
            (idempotency_key, utcnow(), exp_id, purpose, device,
             planned_jobs, planned_shots, planned_usd),
        )
        con.execute(
            "INSERT INTO budget_epoch (day, mps_jobs_used, cpu_jobs_used, usd_used, usd_reserved)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(day) DO UPDATE SET"
            "  mps_jobs_used = mps_jobs_used + excluded.mps_jobs_used,"
            "  cpu_jobs_used = cpu_jobs_used + excluded.cpu_jobs_used,"
            "  usd_reserved  = usd_reserved  + excluded.usd_reserved",
            (day, mps_delta, cpu_delta, 0.0, planned_usd),
        )
    return dict(con.execute(
        "SELECT * FROM reservations WHERE idempotency_key=?", (idempotency_key,)
    ).fetchone())


def mark_dispatched(con, idempotency_key: str, provider_job_ids: list[str]) -> None:
    with con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT status FROM reservations WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"FAIL: no reservation {idempotency_key} — dispatch without reserve")
        if row["status"] != "RESERVED":
            raise SystemExit(
                f"FAIL: reservation {idempotency_key} is {row['status']}; "
                "double dispatch refused (reconcile via job search)"
            )
        con.execute(
            "UPDATE reservations SET status='DISPATCHED', provider_job_ids=? WHERE idempotency_key=?",
            (json.dumps(provider_job_ids), idempotency_key),
        )


def append_job_id(con, idempotency_key: str, provider_job_id: str) -> None:
    """Append a job id to a DISPATCHED reservation (batch of one reservation, many jobs)."""
    with con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT status, provider_job_ids FROM reservations WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"FAIL: no reservation {idempotency_key}")
        if row["status"] == "RESERVED":
            con.execute(
                "UPDATE reservations SET status='DISPATCHED', provider_job_ids=?"
                " WHERE idempotency_key=?",
                (json.dumps([provider_job_id]), idempotency_key),
            )
        elif row["status"] == "DISPATCHED":
            ids = json.loads(row["provider_job_ids"])
            if provider_job_id not in ids:
                ids.append(provider_job_id)
            con.execute(
                "UPDATE reservations SET provider_job_ids=? WHERE idempotency_key=?",
                (json.dumps(ids), idempotency_key),
            )
        else:
            raise SystemExit(
                f"FAIL: reservation {idempotency_key} is {row['status']}; append refused")


def record_job(con, provider_job_id: str, *, idempotency_key: str | None, exp_id: str,
               device: str, n_qubits: int | None, shots: int | None, options: dict | None,
               job_name: str | None, submitted_at: str | None, collected_at: str | None,
               run_status: str, run_time_ms: int | None, queue_time_ms: int | None,
               cost_usd: float | None, estimated_cost_usd: float | None,
               error: str | None = None) -> None:
    with con:
        con.execute(
            "INSERT INTO jobs (provider_job_id, idempotency_key, exp_id, device, n_qubits,"
            " shots, options, job_name, submitted_at, collected_at, run_status, run_time_ms,"
            " queue_time_ms, cost_usd, estimated_cost_usd, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(provider_job_id) DO UPDATE SET"
            "  collected_at=excluded.collected_at, run_status=excluded.run_status,"
            "  run_time_ms=excluded.run_time_ms, queue_time_ms=excluded.queue_time_ms,"
            "  cost_usd=excluded.cost_usd, error=excluded.error",
            (provider_job_id, idempotency_key, exp_id, device, n_qubits, shots,
             json.dumps(options or {}), job_name, submitted_at, collected_at, run_status,
             run_time_ms, queue_time_ms, cost_usd, estimated_cost_usd, error),
        )


def settle(con, idempotency_key: str, actual_jobs: int, actual_shots: int,
           actual_usd: float, note: str = "") -> dict:
    """Planned-vs-actual reconciliation at collect. Returns drift verdict."""
    with con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM reservations WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"FAIL: no reservation {idempotency_key}")
        if row["status"] == "SETTLED":
            return {"already_settled": True}
        planned_usd = row["planned_usd"]
        drift = None
        if planned_usd > 0:
            drift = abs(actual_usd - planned_usd) / planned_usd
        con.execute(
            "UPDATE reservations SET status='SETTLED', actual_jobs=?, actual_shots=?,"
            " actual_usd=?, note=? WHERE idempotency_key=?",
            (actual_jobs, actual_shots, actual_usd, note, idempotency_key),
        )
        day = row["created_at"][:10]
        con.execute(
            "UPDATE budget_epoch SET usd_used = usd_used + ?,"
            " usd_reserved = MAX(0.0, usd_reserved - ?) WHERE day=?",
            (actual_usd, planned_usd, day),
        )
    verdict = {
        "idempotency_key": idempotency_key,
        "planned_usd": planned_usd,
        "actual_usd": actual_usd,
        "drift": drift,
        "pause_paid": bool(drift is not None and drift > DRIFT_PAUSE and actual_usd > 0),
    }
    return verdict


def spend_summary(con) -> dict:
    rows = con.execute(
        "SELECT COALESCE(SUM(actual_usd),0.0) s FROM reservations WHERE status='SETTLED'"
    ).fetchone()
    live = con.execute(
        "SELECT COALESCE(SUM(planned_usd),0.0) s FROM reservations WHERE status!='SETTLED'"
    ).fetchone()
    settled = rows["s"] or 0.0
    reserved = live["s"] or 0.0
    return {
        "settled_usd": round(settled, 4),
        "open_reserved_usd": round(reserved, 4),
        "total_committed_usd": round(settled + reserved, 4),
        "budget_usd": LIMITS["usd_budget_total"],
        "within_budget": settled + reserved <= LIMITS["usd_budget_total"],
        "today": daily_usage(con),
    }


def export(con, out_json: pathlib.Path, out_csv: pathlib.Path) -> None:
    jobs = [dict(r) for r in con.execute(
        "SELECT * FROM jobs ORDER BY submitted_at, provider_job_id")]
    res = [dict(r) for r in con.execute(
        "SELECT * FROM reservations ORDER BY created_at")]
    out_json.write_text(json.dumps(
        {"reservations": res, "jobs": jobs,
         "limits": LIMITS, "spend": spend_summary(con)}, indent=2))
    import csv
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["provider_job_id", "exp_id", "device", "n_qubits", "shots",
                    "options", "run_status", "run_time_ms", "queue_time_ms",
                    "cost_usd", "idempotency_key", "job_name"])
        for j in jobs:
            w.writerow([j["provider_job_id"], j["exp_id"], j["device"], j["n_qubits"],
                        j["shots"], j["options"], j["run_status"], j["run_time_ms"],
                        j["queue_time_ms"], j["cost_usd"], j["idempotency_key"],
                        j["job_name"]])


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    con = connect()
    if cmd == "summary":
        print(json.dumps(spend_summary(con), indent=2))
        return 0
    if cmd == "export":
        out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "report"
        out.mkdir(parents=True, exist_ok=True)
        export(con, out / "job_ledger.json", out / "job_ledger.csv")
        print(f"OK exported to {out}/job_ledger.{{json,csv}}")
        return 0
    if cmd == "jobs":
        for r in con.execute("SELECT * FROM jobs ORDER BY submitted_at"):
            print(dict(r))
        return 0
    print("usage: bq_jobs.py [summary|jobs|export [dir]]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
