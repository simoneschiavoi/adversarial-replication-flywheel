#!/usr/bin/env python3
"""Enforced experiment ledger for the Adversarial Replication Flywheel prototype.

Port of the JS-ASIC asic_ledger.py, generalized. Python stdlib only.

Invariants (enforced by code, not by convention):
  * register()  sha-pins SPEC.md + PREREGISTRATION.json gates at registration time.
  * record()    sha-pins the run's metrics.json; a re-record of the SAME attempt
                directory is refused unless the bytes are identical.
  * promote()   is IMPOSSIBLE without (a) hash integrity of SPEC + latest metrics
                (re-hashed at decision time), (b) every gate metric PRESENT in
                metrics.json and inside its bound. A gate key registered but
                missing from metrics.json FAILS the promotion — absent never passes.
  * 3-attempt cap per experiment; a 4th record() is refused.
  * PARK / BAN require --cause-class; --force promote stamps a disclosure row
                into the ledger entry (forced promotions are visible forever).
  * Gate vocabulary is closed: GATE_KEYS below. Anything else is refused at
                registration.

GATE_KEYS semantics (metrics.json must carry the SAME key names):
  score_max          metrics["score"]          must be <= gate   (cost-like; lower better)
  fidelity_min       metrics["fidelity"]       must be >= gate   (quality; higher better)
  usd_max            metrics["usd"]            must be <= gate
  jobs_max           metrics["jobs"]           must be <= gate   (integer)
  ci_excludes_null   metrics["ci_excludes_null"] must be true when gate is true

Usage:
  ledger.py register EXP-005 path/to/SPEC.md --gate score_max=123.4 --gate fidelity_min=0.62 ...
  ledger.py record  EXP-005 path/to/run_dir
  ledger.py promote EXP-005 [--run run_dir] [--force --disclosure "text"]
  ledger.py park    EXP-005 --cause-class INFRA_FAILURE --note "..."
  ledger.py ban     EXP-005 --cause-class METHOD_KILLED --note "..."
  ledger.py show    [EXP-ID]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "ledger" / "experiments.json"
MAX_ATTEMPTS = 3

GATE_KEYS = ("score_max", "fidelity_min", "usd_max", "jobs_max", "ci_excludes_null")
METRIC_KEY_FOR_GATE = {
    "score_max": "score",
    "fidelity_min": "fidelity",
    "usd_max": "usd",
    "jobs_max": "jobs",
    "ci_excludes_null": "ci_excludes_null",
}
STATES = ("REGISTERED", "RECORDED", "PROMOTED", "FORCED_PROMOTION", "PARKED", "BANNED")


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return {"experiments": {}}


def save_ledger(ledger: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=False) + "\n")
    tmp.replace(LEDGER_PATH)


def get_exp(ledger: dict, exp_id: str) -> dict:
    exp = ledger["experiments"].get(exp_id)
    if exp is None:
        raise SystemExit(f"FAIL: experiment {exp_id} not registered")
    return exp


def parse_gates(pairs: list[str]) -> dict:
    gates: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"FAIL: gate '{pair}' must be KEY=VALUE")
        key, value = pair.split("=", 1)
        if key not in GATE_KEYS:
            raise SystemExit(
                f"FAIL: gate key '{key}' not in closed vocabulary {GATE_KEYS}"
            )
        if key == "ci_excludes_null":
            gates[key] = value.strip().lower() in ("true", "1", "yes")
        else:
            gates[key] = float(value)
        if key in gates and key != "ci_excludes_null" and gates[key] < 0:
            raise SystemExit(f"FAIL: gate '{key}' must be non-negative")
    return gates


def cmd_register(args: argparse.Namespace) -> int:
    ledger = load_ledger()
    if args.exp_id in ledger["experiments"]:
        raise SystemExit(f"FAIL: {args.exp_id} already registered")
    spec = pathlib.Path(args.spec).resolve()
    if not spec.exists():
        raise SystemExit(f"FAIL: SPEC not found: {spec}")
    prereg = spec.parent / "PREREGISTRATION.json"
    if not prereg.exists():
        raise SystemExit(f"FAIL: PREREGISTRATION.json missing next to SPEC")
    gates = parse_gates(args.gate or [])
    entry = {
        "exp_id": args.exp_id,
        "state": "REGISTERED",
        "registered_at": utcnow(),
        "spec_path": str(spec.relative_to(ROOT)) if spec.is_relative_to(ROOT) else str(spec),
        "spec_sha256": sha256_file(spec),
        "preregistration_sha256": sha256_file(prereg),
        "gates": gates,
        "attempts": [],
        "decisions": [],
    }
    ledger["experiments"][args.exp_id] = entry
    save_ledger(ledger)
    print(f"OK registered {args.exp_id} spec_sha={entry['spec_sha256'][:12]} gates={gates}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    ledger = load_ledger()
    exp = get_exp(ledger, args.exp_id)
    if exp["state"] in ("PROMOTED", "FORCED_PROMOTION", "BANNED"):
        raise SystemExit(f"FAIL: {args.exp_id} is terminal ({exp['state']}); no new attempts")
    if len(exp["attempts"]) >= MAX_ATTEMPTS:
        raise SystemExit(
            f"FAIL: {args.exp_id} hit the {MAX_ATTEMPTS}-attempt cap; park or ban it"
        )
    run_dir = pathlib.Path(args.run_dir).resolve()
    metrics = run_dir / "metrics.json"
    if not metrics.exists():
        raise SystemExit(f"FAIL: metrics.json missing in {run_dir}")
    digest = sha256_file(metrics)
    for prev in exp["attempts"]:
        if prev["run_dir"] == str(run_dir):
            if prev["metrics_sha256"] == digest:
                print(f"OK idempotent re-record of identical bytes ({digest[:12]})")
                return 0
            raise SystemExit(
                f"FAIL: {run_dir} already recorded with DIFFERENT bytes; "
                "recorded runs are immutable"
            )
    metrics_json = json.loads(metrics.read_text())
    attempt = {
        "attempt": len(exp["attempts"]) + 1,
        "recorded_at": utcnow(),
        "run_dir": str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir),
        "metrics_sha256": digest,
    }
    exp["attempts"].append(attempt)
    exp["state"] = "RECORDED"
    # snapshot the metric values the gate vocabulary cares about (audit trail)
    exp["last_metrics_view"] = {
        k: metrics_json.get(k, "<ABSENT>")
        for k in ("score", "fidelity", "usd", "jobs", "ci_excludes_null")
        if k in metrics_json or k in [METRIC_KEY_FOR_GATE[g] for g in exp["gates"]]
    }
    save_ledger(ledger)
    print(f"OK recorded attempt {attempt['attempt']} for {args.exp_id} sha={digest[:12]}")
    return 0


def check_promotable(exp: dict, run_dir: pathlib.Path | None) -> tuple[bool, list[str]]:
    """Re-hash SPEC + metrics and evaluate every registered gate. Missing = FAIL."""
    problems: list[str] = []
    spec_path = ROOT / exp["spec_path"]
    if not spec_path.exists() or sha256_file(spec_path) != exp["spec_sha256"]:
        problems.append(f"SPEC hash mismatch: {exp['spec_path']}")
    prereg = spec_path.parent / "PREREGISTRATION.json"
    if not prereg.exists() or sha256_file(prereg) != exp["preregistration_sha256"]:
        problems.append("PREREGISTRATION.json hash mismatch")

    if run_dir is None:
        if not exp["attempts"]:
            return False, ["no recorded attempt"]
        run_dir = pathlib.Path(exp["attempts"][-1]["run_dir"])
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
    metrics = run_dir / "metrics.json"
    if not metrics.exists():
        return False, [f"metrics.json missing: {metrics}"]
    digest = sha256_file(metrics)
    recorded = [a for a in exp["attempts"] if a["run_dir"].endswith(run_dir.name)]
    if not recorded or recorded[-1]["metrics_sha256"] != digest:
        problems.append(f"metrics.json bytes do not match the recorded hash ({digest[:12]})")

    metrics_json = json.loads(metrics.read_text())
    for gate_key, bound in exp["gates"].items():
        metric_key = METRIC_KEY_FOR_GATE[gate_key]
        if metric_key not in metrics_json:
            problems.append(f"gate {gate_key}: metric '{metric_key}' ABSENT from metrics.json -> FAIL")
            continue
        value = metrics_json[metric_key]
        if gate_key == "ci_excludes_null":
            if value is not True:
                problems.append(f"gate ci_excludes_null: metrics value {value} is not true")
        elif gate_key.endswith("_max"):
            if not isinstance(value, (int, float)) or value > bound:
                problems.append(
                    f"gate {gate_key}: metric {metric_key}={value} exceeds bound {bound}"
                )
        elif gate_key.endswith("_min"):
            if not isinstance(value, (int, float)) or value < bound:
                problems.append(
                    f"gate {gate_key}: metric {metric_key}={value} below bound {bound}"
                )
    return (not problems), problems


def cmd_promote(args: argparse.Namespace) -> int:
    ledger = load_ledger()
    exp = get_exp(ledger, args.exp_id)
    if exp["state"] in ("PROMOTED", "FORCED_PROMOTION", "BANNED", "PARKED"):
        raise SystemExit(f"FAIL: {args.exp_id} already in terminal state {exp['state']}")
    ok, problems = check_promotable(exp, pathlib.Path(args.run).resolve() if args.run else None)
    decision = {
        "decision": "PROMOTE",
        "at": utcnow(),
        "attempt": exp["attempts"][-1]["attempt"] if exp["attempts"] else 0,
        "checks": problems,
    }
    if ok and not args.force:
        exp["state"] = "PROMOTED"
    elif args.force:
        if not args.disclosure:
            raise SystemExit("FAIL: --force requires --disclosure (stamped forever)")
        exp["state"] = "FORCED_PROMOTION"
        decision["decision"] = "FORCED_PROMOTION"
        decision["disclosure"] = args.disclosure
        decision["failed_checks"] = problems
    else:
        for p in problems:
            print(f"BLOCKED: {p}", file=sys.stderr)
        print(f"FAIL: promote refused for {args.exp_id} (use park/ban, or fix and re-attempt)", file=sys.stderr)
        return 1
    exp["decisions"].append(decision)
    save_ledger(ledger)
    print(f"OK {exp['state']} {args.exp_id}")
    return 0


def cmd_park_ban(args: argparse.Namespace, verb: str) -> int:
    ledger = load_ledger()
    exp = get_exp(ledger, args.exp_id)
    if not args.cause_class:
        raise SystemExit(f"FAIL: {verb} requires --cause-class")
    exp["state"] = "BANNED" if verb == "ban" else "PARKED"
    exp["decisions"].append(
        {
            "decision": verb.upper(),
            "at": utcnow(),
            "cause_class": args.cause_class,
            "note": args.note or "",
        }
    )
    save_ledger(ledger)
    print(f"OK {verb} {args.exp_id} cause={args.cause_class}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    ledger = load_ledger()
    if args.exp_id:
        print(json.dumps(get_exp(ledger, args.exp_id), indent=2))
    else:
        for exp_id, exp in ledger["experiments"].items():
            print(f"{exp_id:24s} {exp['state']:16s} attempts={len(exp['attempts'])}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Re-verify every terminal decision against current bytes (tamper check)."""
    ledger = load_ledger()
    bad = 0
    for exp_id, exp in ledger["experiments"].items():
        if exp["state"] in ("PROMOTED",):
            ok, problems = check_promotable(exp, None)
            if not ok:
                bad += 1
                print(f"TAMPERED {exp_id}: {problems}")
            else:
                print(f"clean    {exp_id}")
    print("audit:", "FAIL" if bad else "PASS")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register")
    p.add_argument("exp_id")
    p.add_argument("spec")
    p.add_argument("--gate", action="append", default=[])
    p.set_defaults(fn=cmd_register)

    p = sub.add_parser("record")
    p.add_argument("exp_id")
    p.add_argument("run_dir")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("promote")
    p.add_argument("exp_id")
    p.add_argument("--run")
    p.add_argument("--force", action="store_true")
    p.add_argument("--disclosure")
    p.set_defaults(fn=cmd_promote)

    p = sub.add_parser("park")
    p.add_argument("exp_id")
    p.add_argument("--cause-class", required=True)
    p.add_argument("--note")
    p.set_defaults(fn=lambda a: cmd_park_ban(a, "park"))

    p = sub.add_parser("ban")
    p.add_argument("exp_id")
    p.add_argument("--cause-class", required=True)
    p.add_argument("--note")
    p.set_defaults(fn=lambda a: cmd_park_ban(a, "ban"))

    p = sub.add_parser("show")
    p.add_argument("exp_id", nargs="?")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("audit")
    p.set_defaults(fn=cmd_audit)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
