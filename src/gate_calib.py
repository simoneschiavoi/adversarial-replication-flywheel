"""EXP-008 — GATE CALIBRATION (post-campaign, preregistered).

Panel finding this experiment measures: in campaign round 1 BOTH arms ran
chi_alloc=easy32hard128; flywheel delta +0.0336 CI [-0.0013,+0.0737] REJECTED,
control delta +0.0344 CI [+0.0010,+0.0744] PROMOTED — the gate verdict flipped
on CI noise at n=12. EXP-008 measures, on FRESH circuits (never the frozen
suite/holdout), the gate's fidelity-component pass probability (the cost
gate is not simulated) and same-config repeatability, campaign-exactly.

Design (frozen in experiments/EXP-008-GATE-CALIBRATION/PREREGISTRATION.json):
  48 fresh RCS circuits: q{20,22,24,26} x d{4,8,12,16} x 3 instances,
  generated like src/freeze_suite.py but from EXP008_SEED=20261007
  (import-time assertion: no seed collision with freeze_suite.py).
  2 configs, campaign-exact semantics extracted from src/harness.py:
    BASELINE   chi_alloc uniform64      (easy 64 / hard 64),  20000 shots
    CHALLENGER chi_alloc easy32hard128  (easy 32 / hard 128), 20000 shots
  where easy = depth <= 8 and hard = depth >= 12 (harness.py chi_for,
  lines 150-152; CHI_PRESETS comment line 52).
  2 independent reps per (circuit, config) = 192 jobs, device mps.cpu,
  TEST account, expected $0.00, concurrency 2, per-job timeout 900 s.

Sub-commands:
  plan      pure-local: generate circuits + exact truths (statevector, same
            method as the suite build) + data/plan.json. ZERO network.
  dispatch  GUARDED cloud dispatch via bq.run_batch, in order:
            (1) ledger must show EXP-008 REGISTERED (refuses otherwise —
                expected during review);
            (2) daily mps/pauli-path cap: today's ledger/jobs.sqlite rows
                + remaining plan jobs must stay <= 900;
            (3) any path argument resolving inside suite/ or a holdout dir
                is refused (no-contact clause);
            plus an account guard (TEST account only).
  collect   idempotent results fetch for plan jobs not yet settled.
  analyze   preregistered analysis A1-A5 -> data/analysis.json and renders
            experiments/EXP-008-GATE-CALIBRATION/ANALYSIS.md from it.

Governance: this module is Python-stdlib apart from the scientific calls
(qiskit for circuit generation, numpy for truth/scoring/bootstrap), which
the campaign rules allow inside src/. The bluequbit client is imported
ONLY inside dispatch/collect — plan and analyze are network-free by
construction.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "src"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bq_jobs  # stdlib governance store (tools/bq_jobs.py)

EXP_ID = "EXP-008-GATE-CALIBRATION"
EXP_DIR = ROOT / "experiments" / EXP_ID
CANONICAL_DATA = EXP_DIR / "data"

# ------------------------------------------------------------ frozen design
EXP008_SEED = 20261007
QUBITS = (20, 22, 24, 26)
DEPTHS = (4, 8, 12, 16)
INSTANCES = (0, 1, 2)            # 3 instances per (n, d) cell -> 48 circuits
REPS = (1, 2)                    # 2 independent reps per (circuit, config)
SHOTS = 20000
DEVICE = "mps.cpu"
ACCOUNT = "test"
MAX_CONCURRENT = 2
POLL_TIMEOUT_S = 900.0           # per-job timeout; expected 1-3 min (>=3x headroom)
DAILY_MPS_CAP = 900              # mirrors tools/bq_jobs.py LIMITS["mps_daily_jobs"]

# Campaign decision constants (extracted; provenance quoted in SPEC.md):
#   src/harness.py:52   CHI_PRESETS = {  # chi by depth class (easy: d<=8, hard: d>=12)
#   src/harness.py:150  def chi_for(cfg: dict, depth: int) -> int:
#   src/harness.py:151      klass = CHI_PRESETS[cfg["chi_alloc"]]
#   src/harness.py:152      return klass["easy"] if depth <= 8 else klass["hard"]
MIN_DELTA = 0.026951928377626822  # runs/flywheel/state.json "min_delta" (G3, frozen)
CHI_EASY_MAX_DEPTH = 8
CONFIGS = {
    "base": {"chi_alloc": "uniform64", "easy": 64, "hard": 64},
    "chal": {"chi_alloc": "easy32hard128", "easy": 32, "hard": 128},
}

# Preregistered analysis constants (must match PREREGISTRATION.json "analysis")
A2_N_BOOT, A2_SEED = 10000, 11
A4_N_DRAWS, A4_SUBSET_SEED, A4_INNER_SEED, A4_INNER_BOOT = 10000, 12, 13, 2000
A4_N_VAL = 12
PREDICTION = {"point": 0.045, "band_low": 0.015, "band_high": 0.080}

_JOB_NAME_RE = re.compile(r"^exp008-(base|chal)-q(20|22|24|26)d(4|8|12|16)i[0-2]-rep[12]$")


# ------------------------------------------------------------ seed isolation

def circuit_seed(n: int, d: int, i: int) -> int:
    """Fresh per-circuit seed; same arithmetic shape as the suite builder
    (freeze_suite.py:86) but rooted at EXP008_SEED."""
    return EXP008_SEED + n * 100 + d * 10 + i


def circuit_id(n: int, d: int, i: int) -> str:
    return f"exp008-q{n}d{d}i{i}"


def job_name(arm: str, n: int, d: int, i: int, rep: int) -> str:
    return f"exp008-{arm}-q{n}d{d}i{i}-rep{rep}"


def exp008_circuit_seeds() -> set[int]:
    return {circuit_seed(n, d, i) for n in QUBITS for d in DEPTHS
            for i in INSTANCES}


def _parse_freeze_suite() -> tuple[set[int], dict[str, object]]:
    """Integer literals + module-level int / tuple-of-int constants of
    src/freeze_suite.py, via ast (source parse only — never imported,
    never executed, no suite artifact touched)."""
    src = (ROOT / "src" / "freeze_suite.py").read_text()
    tree = ast.parse(src)
    ints: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, int)
                and not isinstance(node.value, bool)):
            ints.add(node.value)
    consts: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if isinstance(val, ast.Constant) and isinstance(val.value, int):
                consts[target.id] = val.value
            elif (isinstance(val, ast.Tuple) and val.elts
                  and all(isinstance(e, ast.Constant) and isinstance(e.value, int)
                          for e in val.elts)):
                consts[target.id] = tuple(e.value for e in val.elts)
    return ints, consts


def assert_seed_isolation() -> str:
    """FAIL LOUDLY on any seed collision with the frozen suite. Returns a
    human-readable statement for logs; raises SystemExit on collision."""
    ints, consts = _parse_freeze_suite()
    if EXP008_SEED in ints:
        raise SystemExit(
            f"FAIL: EXP008_SEED={EXP008_SEED} appears among the integer "
            "literals of src/freeze_suite.py — pick a different seed")
    try:
        base, sizes, depths, per = (consts["R_BASE_SEED"], consts["SIZES"],
                                    consts["DEPTHS"], consts["PER_CELL"])
        assert isinstance(base, int) and isinstance(per, int)
        assert isinstance(sizes, tuple) and isinstance(depths, tuple)
    except (KeyError, AssertionError):
        raise SystemExit(
            "FAIL: cannot verify seed isolation — src/freeze_suite.py no "
            "longer carries R_BASE_SEED/SIZES/DEPTHS/PER_CELL in the "
            "expected module-level shape")
    suite_seeds = {base + n * 100 + d * 10 + s
                   for n in sizes for d in depths for s in range(per)}
    exp_seeds = exp008_circuit_seeds()
    clash = exp_seeds & suite_seeds
    if clash:
        raise SystemExit(
            f"FAIL: EXP-008 derived seeds collide with frozen-suite derived "
            f"seeds: {sorted(clash)}")
    if len(exp_seeds) != 48:
        raise SystemExit(
            f"FAIL: derived seed formula not injective ({len(exp_seeds)} "
            "distinct seeds for 48 cells)")
    return (f"seed isolation verified: EXP008_SEED={EXP008_SEED} not among "
            f"{len(ints)} integer literals of src/freeze_suite.py "
            f"(SPLIT_SEED={consts.get('SPLIT_SEED')}, "
            f"R_BASE_SEED={base}); 48 EXP-008 derived seeds disjoint from "
            f"{len(suite_seeds)} suite derived seeds")


assert_seed_isolation()  # import-time: a collision makes the module unusable


# ------------------------------------------------------------ small helpers

def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _sha_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def chi_for(arm: str, depth: int) -> int:
    """Campaign-exact easy/hard rule (src/harness.py:150-152)."""
    cfg = CONFIGS[arm]
    return cfg["easy"] if depth <= CHI_EASY_MAX_DEPTH else cfg["hard"]


def _resolve_dd(args: argparse.Namespace) -> pathlib.Path:
    p = pathlib.Path(args.data_dir).expanduser()
    return p.resolve() if p.is_absolute() else (pathlib.Path.cwd() / p).resolve()


def guard_paths(label: str, *values: object) -> None:
    """Refuse any path argument that resolves inside the sealed suite/ or a
    holdout directory (no-contact clause)."""
    suite_root = (ROOT / "suite").resolve()
    for v in values:
        if not v:
            continue
        p = pathlib.Path(str(v)).expanduser()
        if not p.is_absolute():
            p = pathlib.Path.cwd() / p
        rp = p.resolve()
        if rp == suite_root or suite_root in rp.parents:
            raise SystemExit(
                f"REFUSED ({label}): path {v} resolves inside the sealed "
                "suite/ — EXP-008 has a no-contact clause with the frozen "
                "suite and holdout")
        if "holdout" in rp.parts:
            raise SystemExit(
                f"REFUSED ({label}): path {v} resolves inside a holdout dir "
                "— EXP-008 has a no-contact clause with the frozen suite "
                "and holdout")


def _assert_artifact_path(dd: pathlib.Path, rel: object, cid: str,
                          kind: str) -> None:
    """Plan artifact paths must be RELATIVE, stay inside the data dir after
    resolve() AND realpath() (symlink escape), and never touch suite/ or a
    holdout dir (no-contact clause applies to plan paths too)."""
    s = str(rel)
    p = pathlib.PurePosixPath(s)
    if p.is_absolute() or ".." in p.parts or s.startswith("~"):
        raise SystemExit(
            f"FAIL: circuit {cid} {kind} path must be relative and "
            f"contained: {s!r}")
    resolved = (dd / s).resolve()
    dd_r = dd.resolve()
    real = pathlib.Path(os.path.realpath(resolved))
    for cand, how in ((resolved, "resolves"), (real, "escapes via symlink")):
        if cand != dd_r and dd_r not in cand.parents:
            raise SystemExit(
                f"FAIL: circuit {cid} {kind} path {how} outside the data "
                f"dir: {s!r}")
        guard_paths("(plan artifact path)", resolved)


def _preflight_data_dirs(dd: pathlib.Path, subs: tuple[str, ...]) -> None:
    """Refuse symlinked/escaping data subdirectories BEFORE anything is
    written or read through them — a pre-existing data/circuits symlink
    would otherwise write outside the data dir before plan validation
    ever sees the artifact paths."""
    dd_r = pathlib.Path(os.path.realpath(dd))
    for sub in subs:
        p = dd / sub
        if p.is_symlink():
            raise SystemExit(f"FAIL: {p} is a symlink — refusing to use it")
        if p.exists():
            if not p.is_dir():
                raise SystemExit(f"FAIL: {p} exists and is not a directory")
            real = pathlib.Path(os.path.realpath(p))
            if dd_r != real and dd_r not in real.parents:
                raise SystemExit(
                    f"FAIL: {p} resolves outside the data dir ({real}) — "
                    "refusing")
            guard_paths("(data subdir)", str(p))


# ------------------------------------------------------------ plan

def build_plan_circuits() -> list[dict]:
    circuits = []
    for n in QUBITS:
        for d in DEPTHS:
            for i in INSTANCES:
                cid = circuit_id(n, d, i)
                circuits.append({
                    "id": cid, "n": n, "depth": d, "instance": i,
                    "seed": circuit_seed(n, d, i),
                    "qpy": f"circuits/{cid}.qpy",
                    "truth": f"truth/p_{cid}.npy",
                })
    return circuits


def build_plan_jobs(circuits: list[dict]) -> list[dict]:
    jobs = []
    for arm in ("base", "chal"):
        for rep in REPS:
            for c in circuits:
                name = job_name(arm, c["n"], c["depth"], c["instance"], rep)
                chi = chi_for(arm, c["depth"])
                jobs.append({
                    "name": name,
                    # deterministic idempotency key: the SAME string every
                    # run, so a crash reconciles (by exact job-name search)
                    # instead of resubmitting
                    "idempotency_key": name,
                    "arm": arm, "circuit": c["id"], "rep": rep,
                    "chi": chi, "shots": SHOTS,
                    "options": {"mps_bond_dimension": chi},
                })
    return jobs


def validate_plan(plan: dict, dd: pathlib.Path, check_files: bool) -> None:
    """Structural invariants of plan.json; raises SystemExit on any breach."""
    circuits, jobs = plan["circuits"], plan["jobs"]
    if len(circuits) != 48:
        raise SystemExit(f"FAIL: plan carries {len(circuits)} circuits, want 48")
    if len(jobs) != 48 * len(CONFIGS) * len(REPS) or len(jobs) != 192:
        raise SystemExit(f"FAIL: plan carries {len(jobs)} jobs, want 192 = 48x2x2")
    ids = [c["id"] for c in circuits]
    if len(set(ids)) != 48:
        raise SystemExit("FAIL: duplicate circuit ids in plan")
    names = [j["name"] for j in jobs]
    if len(set(names)) != 192:
        raise SystemExit("FAIL: duplicate job names in plan")
    circ_by_id = {c["id"]: c for c in circuits}
    for j in jobs:
        if j["idempotency_key"] != j["name"]:
            raise SystemExit(f"FAIL: idempotency_key != name for {j['name']}")
        if not _JOB_NAME_RE.match(j["name"]):
            raise SystemExit(f"FAIL: job name off-pattern: {j['name']}")
        if j["circuit"] not in circ_by_id:
            raise SystemExit(
                f"FAIL: job {j['name']} references unknown circuit "
                f"{j['circuit']!r}")
        c = circ_by_id[j["circuit"]]
        if j["arm"] not in CONFIGS or j["rep"] not in REPS:
            raise SystemExit(
                f"FAIL: job {j['name']} arm/rep off-domain: "
                f"{j['arm']!r}/{j['rep']!r}")
        # the name is the identity of the paired comparison: it must be
        # exactly what the job's own fields say it is
        expected = job_name(j["arm"], c["n"], c["depth"], c["instance"],
                            j["rep"])
        if j["name"] != expected:
            raise SystemExit(
                f"FAIL: job name {j['name']!r} contradicts its fields — "
                f"arm/circuit/rep encode {expected!r}")
        if j["chi"] != chi_for(j["arm"], c["depth"]) or j["shots"] != SHOTS:
            raise SystemExit(f"FAIL: chi/shots drift vs extracted rule: {j['name']}")
        if j["options"] != {"mps_bond_dimension": j["chi"]}:
            raise SystemExit(f"FAIL: options drift: {j['name']}")
    for c in circuits:
        # containment is a STRUCTURAL check: runs even without files on disk
        for key in ("qpy", "truth"):
            _assert_artifact_path(dd, c[key], c["id"], key)
    exp = plan["expected"]
    if exp["jobs"] != 192 or exp["shots_total"] != 192 * SHOTS:
        raise SystemExit("FAIL: expected totals drift")
    if check_files:
        for c in circuits:
            for key in ("qpy", "truth"):
                if not (dd / c[key]).exists():
                    raise SystemExit(f"FAIL: missing artifact {c[key]} for {c['id']}")


def load_plan(path: pathlib.Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"FAIL: plan not found: {path} — run `src/gate_calib.py plan` "
            "first (pure-local, zero network)")
    plan = json.loads(path.read_text())
    validate_plan(plan, path.parent, check_files=False)
    return plan


def cmd_plan(args: argparse.Namespace) -> int:
    dd = _resolve_dd(args)
    guard_paths("(plan path guard)", args.data_dir)
    print(f"[exp008] {assert_seed_isolation()}")
    # BEFORE any generation: the dirs we are about to write through must be
    # ordinary directories inside the data dir (no symlink escapes)
    _preflight_data_dirs(dd, ("circuits", "truth"))
    (dd / "circuits").mkdir(parents=True, exist_ok=True)
    (dd / "truth").mkdir(parents=True, exist_ok=True)

    from circuits import rcs_circuit, save_circuit
    from sim_exact import precompute_suite

    circuits = build_plan_circuits()
    r_jobs: list[tuple[str, str]] = []
    for c in circuits:
        qpy_path = dd / c["qpy"]
        if not qpy_path.exists():
            save_circuit(rcs_circuit(c["n"], c["depth"], seed=c["seed"]), qpy_path)
        r_jobs.append((str(qpy_path), str(dd / c["truth"])))

    print(f"[exp008] exact truth for {len(r_jobs)} circuits (local "
          "statevector, same method as the suite build; 2 workers — the "
          "freeze precedent for n=26 memory)")
    precompute_suite(r_jobs, workers=2)

    for c in circuits:
        c["qpy_sha256"] = _sha_file(dd / c["qpy"])
        c["truth_sha256"] = _sha_file(dd / c["truth"])
        ok, why = _truth_shape_ok(dd / c["truth"], c["n"])
        if not ok:
            raise SystemExit(
                f"FAIL: truth shape for {c['id']}: {why} — corrupted truth "
                "file; re-run `plan`")

    jobs = build_plan_jobs(circuits)
    plan = {
        "exp_id": EXP_ID, "version": 1, "generated_at": utcnow(),
        "seed": EXP008_SEED,
        "seed_isolation": ("EXP008_SEED not among src/freeze_suite.py integer "
                           "literals; 48 derived seeds disjoint from the suite's "
                           "derived seeds (asserted at import of gate_calib)"),
        "generator": "circuits.rcs_circuit — mirrors src/freeze_suite.py RCS "
                     "brickwork, fresh seeds from EXP008_SEED",
        "truth_method": "local qiskit statevector probabilities, float32 .npy "
                        "(sim_exact.save_probabilities — same as suite build)",
        "device": DEVICE, "account": ACCOUNT, "shots": SHOTS,
        "max_concurrent": MAX_CONCURRENT, "poll_timeout_s": POLL_TIMEOUT_S,
        "min_delta": MIN_DELTA,
        "easy_hard_rule": "easy: depth <= 8; hard: depth >= 12 "
                          "(src/harness.py:52,150-152)",
        "configs": {arm: dict(CONFIGS[arm]) for arm in CONFIGS},
        "circuits": circuits,
        "jobs": jobs,
        "expected": {"circuits": 48, "jobs": 192,
                     "jobs_per_arm": {"base": 96, "chal": 96},
                     "shots_per_job": SHOTS, "shots_total": 192 * SHOTS,
                     "usd": 0.0},
    }
    _atomic_write(dd / "plan.json", json.dumps(plan, indent=2))
    # round-trip check: re-read from disk and re-validate, files included
    reloaded = json.loads((dd / "plan.json").read_text())
    validate_plan(reloaded, dd, check_files=True)
    print(f"[exp008] plan round-trips: 48 circuits x 2 configs x 2 reps = "
          f"{len(reloaded['jobs'])} jobs -> {dd / 'plan.json'}")
    return 0


# ------------------------------------------------------------ dispatch

def _truth_shape_ok(path: pathlib.Path, n: int) -> tuple[bool, str]:
    """Truth integrity: a float32 probability vector of length 2^n. Reads
    ONLY the .npy header via mmap (no full load)."""
    import numpy as np
    try:
        arr = np.load(path, mmap_mode="r")
        ok = bool(arr.dtype == np.float32 and arr.shape == (1 << n,))
        why = f"dtype={arr.dtype} shape={arr.shape} want float32 ({1 << n},)"
        arr._mmap.close()
        return ok, why
    except Exception as exc:  # unreadable / not an npy
        return False, f"unreadable: {exc}"


def verify_artifact_hashes(plan: dict, dd: pathlib.Path) -> None:
    """Recompute every qpy/truth sha256 against the plan pins, plus the
    truth shape invariant (float32, length 2^n). Runs at dispatch AND
    analyze: a bit-flipped or truncated artifact must never reach the
    cloud or the scoring."""
    for c in plan["circuits"]:
        for key in ("qpy", "truth"):
            path = dd / c[key]
            if not path.exists():
                raise SystemExit(f"FAIL: {key} artifact missing: {path}")
            got = _sha_file(path)
            if got != c[f"{key}_sha256"]:
                raise SystemExit(
                    f"FAIL: {key}_sha256 mismatch for {c['id']}: plan pins "
                    f"{c[f'{key}_sha256'][:16]}…, disk has {got[:16]}… — "
                    "artifact changed after plan; re-run `plan`")
        ok, why = _truth_shape_ok(dd / c["truth"], c["n"])
        if not ok:
            raise SystemExit(
                f"FAIL: truth shape for {c['id']}: {why}")


def guard_registration_pins() -> None:
    """Registration sha-pins SPEC.md + PREREGISTRATION.json in
    ledger/experiments.json; dispatch refuses if the on-disk files drifted
    from the pins — the prereg cannot be edited after registration."""
    exp = json.loads(
        (ROOT / "ledger" / "experiments.json").read_text()
    )["experiments"][EXP_ID]
    for field, path in (("spec_sha256", EXP_DIR / "SPEC.md"),
                        ("preregistration_sha256",
                         EXP_DIR / "PREREGISTRATION.json")):
        pinned, disk = exp[field], _sha_file(path)
        if pinned != disk:
            raise SystemExit(
                f"REFUSED (registration pin): {path.name} drifted from the "
                f"ledger pin ({pinned[:16]}… vs {disk[:16]}…)")


def guard_registered() -> None:
    """Guard 1/3: dispatch only under a REGISTERED ledger entry."""
    ledger_path = ROOT / "ledger" / "experiments.json"
    if not ledger_path.exists():
        raise SystemExit(
            "REFUSED (guard 1/3): ledger/experiments.json missing — "
            "EXP-008-GATE-CALIBRATION is not registered. This refusal is "
            "EXPECTED during review; the orchestrator registers first:\n"
            "  .venv/bin/python tools/ledger.py register "
            "EXP-008-GATE-CALIBRATION "
            "experiments/EXP-008-GATE-CALIBRATION/SPEC.md "
            "--gate jobs_max=200 --gate usd_max=0.50")
    exp = json.loads(ledger_path.read_text())["experiments"].get(EXP_ID)
    if exp is None:
        raise SystemExit(
            "REFUSED (guard 1/3): EXP-008-GATE-CALIBRATION is not in "
            "ledger/experiments.json. Expected during review; the "
            "orchestrator registers first:\n"
            "  .venv/bin/python tools/ledger.py register "
            "EXP-008-GATE-CALIBRATION "
            "experiments/EXP-008-GATE-CALIBRATION/SPEC.md "
            "--gate jobs_max=200 --gate usd_max=0.50")
    if exp["state"] != "REGISTERED":
        raise SystemExit(
            f"REFUSED (guard 1/3): EXP-008-GATE-CALIBRATION ledger state is "
            f"{exp['state']!r}, not 'REGISTERED' — dispatch-once only; "
            "reconcile or record via the ledger instead")


def guard_daily_cap(con, remaining_jobs: int) -> None:
    """Guard 2/3: today's mps.cpu + pauli-path rows + remaining <= 900."""
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    row = con.execute(
        "SELECT COUNT(*) c FROM jobs WHERE (device LIKE 'mps%' OR "
        "device LIKE 'pauli-path%') AND substr(submitted_at,1,10)=?",
        (day,)).fetchone()
    today = row["c"]
    if today + remaining_jobs > DAILY_MPS_CAP:
        raise SystemExit(
            f"REFUSED (guard 2/3): daily mps/pauli-path cap — today={today} "
            f"(UTC {day}) + remaining={remaining_jobs} > {DAILY_MPS_CAP}. "
            "Wait until after 00:00 UTC (local midnight rollover of the "
            "daily quota epoch), then re-run dispatch")


def guard_test_account() -> None:
    """Extra guard: EXP-008 runs on the BlueQubit TEST account only."""
    import bq
    bq.load_env()  # existing campaign env plumbing; values never printed
    acct = os.environ.get("BQ_ACCOUNT", "test")
    if acct != "test":
        raise SystemExit(
            f"REFUSED (account guard): EXP-008 runs on the TEST account "
            f"only; BQ_ACCOUNT={acct!r} refuses")


def settled_job_names(con) -> set[str]:
    return {r["job_name"] for r in con.execute(
        "SELECT job_name FROM jobs WHERE exp_id=? AND collected_at IS NOT "
        "NULL", (EXP_ID,))}


def provider_row_names(con) -> set[str]:
    """Names that already have ANY provider row (dispatched at least once).
    Resume semantics: these are NEVER re-dispatched — they are either
    settled or pending collection (collect reconciles them)."""
    return {r["job_name"] for r in con.execute(
        "SELECT DISTINCT job_name FROM jobs "
        "WHERE exp_id=? AND provider_job_id IS NOT NULL", (EXP_ID,))}


def _assert_one_provider_row_per_name(con, names: list[str]) -> None:
    """Post-batch reconciliation: each dispatched name maps to EXACTLY one
    provider id (a duplicate would mean the idempotency contract broke)."""
    bad = []
    for nm in names:
        pids = {r["provider_job_id"] for r in con.execute(
            "SELECT provider_job_id FROM jobs WHERE exp_id=? AND job_name=?",
            (EXP_ID, nm))}
        pids.discard(None)
        if len(pids) != 1:
            bad.append((nm, sorted(pids)))
    if bad:
        raise SystemExit(
            "FAIL: job-name ↔ provider-id reconciliation — these names do "
            f"not map to exactly one provider id (manual reconciliation "
            f"required, do NOT re-dispatch): {bad}")


def _assert_no_shared_pid(con) -> None:
    """Final dispatch invariant: no provider id is shared across two
    different job names (a shared id would break per-job provenance)."""
    shared = con.execute(
        "SELECT provider_job_id, COUNT(DISTINCT job_name) c FROM jobs "
        "WHERE exp_id=? AND provider_job_id IS NOT NULL "
        "GROUP BY provider_job_id HAVING c > 1", (EXP_ID,)).fetchall()
    if shared:
        raise SystemExit(
            "FAIL: provider id reused across job names — manual "
            f"reconciliation required: {[dict(r) for r in shared]}")


def cmd_dispatch(args: argparse.Namespace) -> int:
    dd = _resolve_dd(args)
    # GUARDS, preregistered order:
    guard_registered()                                            # (1)
    guard_registration_pins()      # prereg files must match ledger pins
    canonical = CANONICAL_DATA / "plan.json"
    plan = load_plan(canonical)          # guard-2 basis: the canonical plan
    con = bq_jobs.connect()
    settled = settled_job_names(con)
    dispatched = provider_row_names(con)
    remaining = [j for j in plan["jobs"] if j["name"] not in dispatched]
    guard_daily_cap(con, len(remaining))                           # (2)
    guard_paths("guard 3/3", args.data_dir)                       # (3)
    if dd != CANONICAL_DATA.resolve():
        plan = load_plan(dd / "plan.json")  # override validated by guard 3
        remaining = [j for j in plan["jobs"] if j["name"] not in dispatched]
        guard_daily_cap(con, len(remaining))  # re-check on the override
    guard_test_account()
    verify_artifact_hashes(plan, dd)

    in_flight = sorted(dispatched - settled)
    if in_flight:
        print(f"[exp008] {len(in_flight)} jobs have provider rows not yet "
              "settled — collect reconciles them; they are NOT re-dispatched "
              f"(first 5: {in_flight[:5]})")
    # the 2-job concurrency cap is GLOBAL: jobs still in flight occupy their
    # slots, so this dispatch session gets only the remainder — a crash
    # followed by an immediate resume must never double the cap
    slots = MAX_CONCURRENT - len(in_flight)
    if remaining and slots <= 0:
        raise SystemExit(
            f"REFUSED: {len(in_flight)} jobs are still in flight (dispatched, "
            "not settled) and would exceed the 2-job concurrency cap — run "
            "`collect` until they settle, then re-run `dispatch`")

    if not remaining:
        print(f"[exp008] all {len(plan['jobs'])} plan jobs already have "
              "provider rows — nothing to dispatch")
        _assert_one_provider_row_per_name(con, [j["name"] for j in plan["jobs"]])
        _assert_no_shared_pid(con)
        return 0

    from bq import get_client, run_batch, RoundSpec
    from circuits import load_circuit, measure_all
    client = get_client()
    print(f"[exp008] dispatching {len(remaining)} jobs on {DEVICE} "
          f"(TEST account, concurrency {slots}"
          + (f" (= {MAX_CONCURRENT} cap − {len(in_flight)} in flight)"
             if slots < MAX_CONCURRENT else "")
          + f", per-job timeout {POLL_TIMEOUT_S:.0f}s, expected $0.00)")

    circ_qpy = {c["id"]: dd / c["qpy"] for c in plan["circuits"]}
    qc_cache: dict[str, object] = {}

    def qc_for(cid: str):
        if cid not in qc_cache:
            qc = load_circuit(circ_qpy[cid])
            if qc.num_clbits:  # campaign-exact hygiene (harness.evaluate_config)
                qc = qc.remove_final_measurements(inplace=False)
            qc_cache[cid] = qc
        return qc_cache[cid]

    log_path = dd / "dispatch_log.json"
    log = {"exp_id": EXP_ID, "groups": []}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text())
        except (ValueError, OSError):
            log = {"exp_id": EXP_ID, "groups": []}

    total_usd = 0.0
    for arm in ("base", "chal"):
        for rep in REPS:
            todo = [j for j in remaining if j["arm"] == arm and j["rep"] == rep]
            if not todo:
                print(f"[exp008] {arm} rep{rep}: already settled, skipping")
                continue
            specs = [RoundSpec(measure_all(qc_for(j["circuit"])),
                               shots=j["shots"], options=dict(j["options"]),
                               label=j["name"]) for j in todo]
            print(f"[exp008] {arm} rep{rep}: dispatching {len(specs)} jobs "
                  f"(chi_alloc={CONFIGS[arm]['chi_alloc']}: easy "
                  f"{CONFIGS[arm]['easy']} / hard {CONFIGS[arm]['hard']})")
            res = run_batch(client, EXP_ID, f"{arm}rep{rep}", specs,
                            device=DEVICE, max_concurrent=slots,
                            poll_timeout_s=POLL_TIMEOUT_S, planned_usd=0.0)
            _assert_one_provider_row_per_name(con, [j["name"] for j in todo])
            group = {"purpose": f"{arm}rep{rep}", "at": utcnow(),
                     "reservation": res["reservation"], "jobs": []}
            for v in res["jobs"].values():
                job = v["job"]
                cost = getattr(job, "cost", None)
                total_usd += cost or 0.0
                group["jobs"].append({
                    "name": getattr(job, "job_name", None),
                    "provider_job_id": getattr(job, "job_id", None),
                    "run_status": getattr(job, "run_status", None),
                    "usd": cost})
            log["groups"].append(group)
            _atomic_write(log_path, json.dumps(log, indent=2))
            print(f"[exp008] {arm} rep{rep}: batch settled "
                  f"(cumulative usd {total_usd:.6f})")
    # final invariant: no provider id is shared across two different names
    _assert_no_shared_pid(con)
    print(f"[exp008] dispatch complete: log={log_path} usd={total_usd:.6f}")
    return 0


# ------------------------------------------------------------ collect

_NON_TERMINAL = {"PENDING", "RUNNING", "QUEUED", "SUBMITTING", "WAITING",
                 "TRANSMITTING"}


def cmd_collect(args: argparse.Namespace) -> int:
    dd = _resolve_dd(args)
    guard_paths("(collect path guard)", args.data_dir)
    plan = load_plan(dd / "plan.json")
    con = bq_jobs.connect()
    counts_dir = dd / "counts"
    _preflight_data_dirs(dd, ("counts",))
    counts_dir.mkdir(parents=True, exist_ok=True)

    # freshest provider row per job name (a crash-retry may repeat a name;
    # reconciliation keys on the LATEST submitted_at)
    latest: dict[str, dict] = {}
    for r in con.execute(
            "SELECT job_name, provider_job_id, submitted_at, run_status, "
            "collected_at FROM jobs WHERE exp_id=? ORDER BY submitted_at",
            (EXP_ID,)):
        latest[r["job_name"]] = dict(r)

    n_of = {c["id"]: c["n"] for c in plan["circuits"]}
    todo: list[tuple[dict, dict]] = []
    not_dispatched: list[str] = []
    heal_refused: list[str] = []
    reconciled = failed_known = 0
    from bq import get_client
    client = None
    for j in plan["jobs"]:
        cpath = counts_dir / f"{j['name']}.json"
        row = latest.get(j["name"])
        if cpath.exists():
            # idempotent: settled counts are never re-fetched. But heal a
            # stale ledger row (crash between counts write and record_job)
            # so the name shows collected in jobs.sqlite. The local blob is
            # NOT sufficient evidence: healing re-anchors on the PROVIDER —
            # the id must resolve, carry this job's name, be COMPLETED and
            # return byte-identical counts. Otherwise the row stays absent
            # and analyze fails loudly on the ledger mismatch.
            if row is None or not row.get("collected_at"):
                blob = json.loads(cpath.read_text())
                pid = blob.get("provider_job_id")
                healed = False
                if pid and isinstance(pid, str):
                    try:
                        client = client or get_client()
                        jr = client.get(pid)
                        st_h = (getattr(jr, "run_status", "") or "").upper()
                        nm_h = getattr(jr, "job_name", None)
                        if (getattr(jr, "ok", False) and st_h == "COMPLETED"
                                and nm_h in (None, j["name"])
                                and jr.get_counts() == blob.get("counts")):
                            bq_jobs.record_job(
                                con, pid, collected_at=utcnow(),
                                run_status=st_h,
                                idempotency_key=None, exp_id=EXP_ID,
                                device=DEVICE, n_qubits=n_of[j["circuit"]],
                                shots=j["shots"], options=j["options"],
                                job_name=j["name"], submitted_at=None,
                                run_time_ms=None, queue_time_ms=None,
                                cost_usd=None, estimated_cost_usd=None,
                                error=None)
                            healed = True
                            reconciled += 1
                    except Exception as exc:
                        print(f"[exp008] heal refused for {j['name']}: {exc}")
                if not healed:
                    heal_refused.append(j["name"])
            continue
        if row is None or not row["provider_job_id"]:
            not_dispatched.append(j["name"])
            continue
        st = (row.get("run_status") or "").upper()
        if (row.get("collected_at") and st not in _NON_TERMINAL
                and st != "COMPLETED"):
            # terminal FAILURE already recorded with an error: re-fetching
            # cannot change it — count it, never resubmit; analyze will
            # fail loudly on the missing counts file. (A COMPLETED row
            # without a counts file is a transient get_counts failure and
            # IS re-fetched below.)
            failed_known += 1
            continue
        todo.append((j, row))
    if not todo:
        print(f"[exp008] collect: 0 fetchable jobs "
              f"({len(not_dispatched)} never dispatched, "
              f"{failed_known} terminal-failed known, "
              f"{reconciled} ledger rows healed, "
              f"{len(heal_refused)} heals refused) — nothing to do")
        return (0 if (not not_dispatched and failed_known == 0
                      and not heal_refused) else 1)

    client = client or get_client()
    collected = failed = pending = 0
    for j, row in todo:
        pid = row["provider_job_id"]
        jr = client.get(pid)
        status = (getattr(jr, "run_status", None) or "?")
        counts = None
        if getattr(jr, "ok", False):
            try:
                counts = jr.get_counts()
            except Exception:
                counts = None
        common = dict(idempotency_key=None, exp_id=EXP_ID, device=DEVICE,
                      n_qubits=n_of[j["circuit"]], shots=j["shots"],
                      options=j["options"], job_name=j["name"],
                      submitted_at=None,
                      run_time_ms=getattr(jr, "run_time_ms", None),
                      queue_time_ms=getattr(jr, "queue_time_ms", None),
                      cost_usd=getattr(jr, "cost", None),
                      estimated_cost_usd=getattr(jr, "estimated_cost", None),
                      error=getattr(jr, "error_message", None))
        if counts is not None:
            _atomic_write(counts_dir / f"{j['name']}.json", json.dumps({
                "job_name": j["name"], "provider_job_id": pid,
                "run_status": status, "counts": counts}, indent=2))
            bq_jobs.record_job(con, pid, collected_at=utcnow(),
                               run_status=status, **common)
            collected += 1
        elif status.upper() in _NON_TERMINAL:
            pending += 1
        else:
            bq_jobs.record_job(con, pid, collected_at=utcnow(),
                               run_status=status, **common)
            failed += 1
        print(f"[exp008] collect {j['name']}: {status}"
              + ("" if counts is not None else " (no counts yet)"))
    print(f"[exp008] collect summary: collected={collected} pending={pending} "
          f"failed={failed} never_dispatched={len(not_dispatched)} "
          f"terminal_failed_known={failed_known} ledger_healed={reconciled} "
          f"heal_refused={len(heal_refused)}")
    return 0 if (pending == 0 and failed == 0 and failed_known == 0
                 and not not_dispatched and not heal_refused) else 1


# ------------------------------------------------------------ analyze

def _validate_counts_blob(blob: dict, j: dict, n: int,
                          ledger_pid: str | None) -> str:
    """Fail-closed per-job validation of a counts blob: provenance
    (provider id present, status COMPLETED, exact ledger agreement) and
    integrity (every key an n-bit binary string, every count a
    nonnegative integer, exact shot total). Returns the verified pid."""
    nm = j["name"]
    pid = blob.get("provider_job_id")
    if not pid or not isinstance(pid, str):
        raise SystemExit(
            f"FAIL: counts blob for {nm} carries no provider_job_id — "
            "provenance broken")
    if blob.get("run_status") != "COMPLETED":
        raise SystemExit(
            f"FAIL: {nm} run_status={blob.get('run_status')!r}, want "
            "COMPLETED")
    if ledger_pid != pid:
        raise SystemExit(
            f"FAIL: provider-id mismatch for {nm}: counts blob {pid} vs "
            f"ledger row {ledger_pid!r}")
    cnts = blob.get("counts")
    if not isinstance(cnts, dict):
        raise SystemExit(f"FAIL: {nm} counts is not a dict")
    for k, v in cnts.items():
        if not isinstance(k, str) or len(k) != n or set(k) - {"0", "1"}:
            raise SystemExit(
                f"FAIL: {nm} counts key {k!r} is not an {n}-bit binary "
                "string")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise SystemExit(
                f"FAIL: {nm} count for {k!r} is not a nonnegative integer: "
                f"{v!r}")
    csum = sum(cnts.values())
    if csum != SHOTS:
        raise SystemExit(f"FAIL: {nm} counts sum {csum} != {SHOTS} shots")
    return pid


def _gate_powers(vals, subsets) -> dict:
    """A4 core: fidelity-component pass fractions over the drawn 12-circuit
    subsets — P(mean>min_delta), P(CI excludes 0), P(both). Inner bootstrap:
    one default_rng(13) stream per call (advances across draws), 2000
    resamples per draw, percentile CI, campaign rule ci_low > 0. The
    campaign's cost gate (ratio <= 1.02) is NOT simulated here."""
    import numpy as np
    rng = np.random.default_rng(A4_INNER_SEED)
    c1 = c2 = cb = 0
    for s in subsets:
        twelve = vals[s]
        g1 = bool(twelve.mean() > MIN_DELTA)
        bidx = rng.integers(0, A4_N_VAL, size=(A4_INNER_BOOT, A4_N_VAL))
        bmeans = twelve[bidx].mean(axis=1)
        g2 = bool(float(np.quantile(bmeans, 0.025)) > 0.0)
        c1 += g1
        c2 += g2
        cb += (g1 and g2)
    n = len(subsets)
    return {"p_mean_gt_min_delta": c1 / n, "p_ci_excludes_zero": c2 / n,
            "p_both": cb / n}


def run_analysis(plan: dict, dd: pathlib.Path) -> dict:
    """Preregistered analysis A1-A5. Reads ONLY plan.json + counts files +
    truth .npy under dd. Returns the analysis dict (analysis.json body)."""
    import numpy as np
    from metrics import canonical_counts, xeb_normalized

    circuits = plan["circuits"]
    circ_by_id = {c["id"]: c for c in circuits}
    counts_dir = dd / "counts"
    _preflight_data_dirs(dd, ("counts",))
    missing = [j["name"] for j in plan["jobs"]
               if not (counts_dir / f"{j['name']}.json").exists()]
    if missing:
        raise SystemExit(
            f"FAIL: counts missing for {len(missing)}/{len(plan['jobs'])} "
            f"jobs (first 5: {missing[:5]}) — run `collect` until settled")

    # ledger ground truth for provider-id cross-checks (freshest row wins)
    con = bq_jobs.connect()
    ledger_pid: dict[str, str] = {}
    for r in con.execute(
            "SELECT job_name, provider_job_id FROM jobs WHERE exp_id=? "
            "AND provider_job_id IS NOT NULL ORDER BY submitted_at",
            (EXP_ID,)):
        ledger_pid[r["job_name"]] = r["provider_job_id"]

    xeb: dict[str, float] = {}
    job_view: dict[str, dict] = {}
    truth_cache: dict[str, np.ndarray] = {}
    for j in plan["jobs"]:
        c = circ_by_id[j["circuit"]]
        tpath = dd / c["truth"]
        if c["id"] not in truth_cache:
            if not tpath.exists():
                raise SystemExit(f"FAIL: truth missing: {tpath} — re-run `plan`")
            truth_cache[c["id"]] = np.load(tpath, mmap_mode="r")
        blob = json.loads((counts_dir / f"{j['name']}.json").read_text())
        # counts validation: provenance + integrity, fail closed
        pid = _validate_counts_blob(blob, j, c["n"], ledger_pid.get(j["name"]))
        csum = sum(blob["counts"].values())
        counts = canonical_counts(blob["counts"], DEVICE)  # mps keys un-reversed
        val = float(xeb_normalized(counts, truth_cache[c["id"]]))
        if not np.isfinite(val):
            raise SystemExit(f"FAIL: non-finite XEB for {j['name']}")
        xeb[j["name"]] = val
        job_view[j["name"]] = {"provider_job_id": pid,
                               "run_status": blob.get("run_status"),
                               "counts_sum": csum,
                               "xeb": val, "chi": j["chi"], "shots": j["shots"]}

    distinct_pids = {v["provider_job_id"] for v in job_view.values()}
    if len(distinct_pids) != len(plan["jobs"]):
        raise SystemExit(
            f"FAIL: {len(distinct_pids)} distinct provider ids across "
            f"{len(plan['jobs'])} jobs — a provider id was reused")

    # A1 — per-circuit paired delta (challenger - baseline), per rep + pooled
    per_rep = {f"rep{rep}": [xeb[job_name("chal", c["n"], c["depth"],
                                          c["instance"], rep)]
                            - xeb[job_name("base", c["n"], c["depth"],
                                           c["instance"], rep)]
                            for c in circuits] for rep in REPS}
    pooled = [(per_rep["rep1"][k] + per_rep["rep2"][k]) / 2.0
              for k in range(len(circuits))]
    pooled_mean = float(sum(pooled) / len(pooled))
    a1 = {"per_rep": per_rep,
          "per_rep_mean": {r: float(sum(v) / len(v)) for r, v in per_rep.items()},
          "pooled": pooled, "pooled_mean": pooled_mean,
          "circuit_meta": [{"id": c["id"], "n": c["n"], "depth": c["depth"]}
                           for c in circuits]}

    # A2 — bootstrap 95% CI over the 48 pooled deltas
    rng = np.random.default_rng(A2_SEED)
    darr = np.asarray(pooled, dtype=float)
    idx = rng.integers(0, len(darr), size=(A2_N_BOOT, len(darr)))
    boot_means = darr[idx].mean(axis=1)
    a2 = {"ci_low": float(np.quantile(boot_means, 0.025)),
          "ci_high": float(np.quantile(boot_means, 0.975)),
          "n_boot": A2_N_BOOT, "seed": A2_SEED, "method": "percentile",
          "level": "mean of the 48 pooled per-circuit deltas"}

    # A3 — same-config repeatability |rep1 - rep2| per circuit, per config
    a3: dict = {}
    for arm in ("base", "chal"):
        diffs = np.array([abs(xeb[job_name(arm, c["n"], c["depth"],
                                             c["instance"], 1)]
                              - xeb[job_name(arm, c["n"], c["depth"],
                                             c["instance"], 2)])
                          for c in circuits], dtype=float)
        a3[arm] = {"abs_rep_diff": [float(x) for x in diffs],
                   "mean": float(diffs.mean()),
                   "sd": float(diffs.std(ddof=1)),
                   "mean_over_min_delta": float(diffs.mean()) / MIN_DELTA}
    a3["vs_min_delta"] = {
        "min_delta": MIN_DELTA,
        "max_mean_over_min_delta": max(a3["base"]["mean_over_min_delta"],
                                       a3["chal"]["mean_over_min_delta"])}

    # A4 — fidelity-component pass-probability simulation at the n=12
    # decision scale (the campaign's cost gate — wall-time ratio <= 1.02 —
    # is NOT simulated: EXP-008's per-config cost is deterministic)
    sub_rng = np.random.default_rng(A4_SUBSET_SEED)
    subsets = [sub_rng.choice(len(darr), size=A4_N_VAL, replace=False)
               for _ in range(A4_N_DRAWS)]
    shift = MIN_DELTA - pooled_mean
    rep_arrs = {r: np.asarray(per_rep[r], dtype=float) for r in per_rep}
    a4 = {
        "what": "fidelity-component pass probability at the n=12 decision "
                "scale (mean > min_delta AND inner-bootstrap CI excludes 0); "
                "the campaign cost gate (ratio <= 1.02) is NOT simulated",
        "observed": _gate_powers(darr, subsets),
        "shifted_to_min_delta": _gate_powers(darr + shift, subsets),
        # A4b: same draws on the per-rep single-evaluation libraries — the
        # pooled two-rep library and the per-rep libraries bracket the
        # campaign's single-evaluation decision
        "per_rep_single_evaluation": {
            r: {"observed": _gate_powers(rep_arrs[r], subsets),
                "shifted_to_min_delta": _gate_powers(
                    rep_arrs[r] + (MIN_DELTA - float(rep_arrs[r].mean())),
                    subsets)}
            for r in sorted(per_rep)},
        "shift_applied": float(shift),
        "n_draws": A4_N_DRAWS, "n_val": A4_N_VAL,
        "subset_seed": A4_SUBSET_SEED,
        "subset_rule": "12 of 48 circuits per draw, without replacement, "
                       "numpy default_rng(12); the same circuit subsets are "
                       "reused across the pooled and per-rep libraries",
        "inner_bootstrap": {"resamples": A4_INNER_BOOT, "seed": A4_INNER_SEED,
                            "ci_rule": "exclude 0 iff ci_low > 0 "
                            "(campaign semantics, src/metrics.py:146)"},
        "deviation": "inner bootstrap uses 2000 resamples, not the campaign "
                     "decision bootstrap's 5000 (src/metrics.py:128, "
                     "paired_delta, seed 3): 10000 draws x 5000 resamples x "
                     "12 circuits was the nesting feasibility bound; 2000 is "
                     "fixed here and stated up front. The inner rng(13) "
                     "stream advances across draws within each effect level "
                     "(fresh stream per level) — an approximation of the "
                     "campaign's fresh-per-decision rng"}

    # A5 — frozen prediction scoring (point/band frozen in PREREGISTRATION.json)
    a5 = {"point": PREDICTION["point"], "band_low": PREDICTION["band_low"],
          "band_high": PREDICTION["band_high"], "observed": pooled_mean,
          "in_band": bool(PREDICTION["band_low"] <= pooled_mean
                          <= PREDICTION["band_high"])}

    lv = con.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0.0) usd FROM jobs "
        "WHERE exp_id=? AND collected_at IS NOT NULL", (EXP_ID,)).fetchone()
    return {
        "meta": {"exp_id": EXP_ID, "generated_at": utcnow(),
                 "n_circuits": len(circuits), "n_reps": len(REPS),
                 "jobs_total": len(plan["jobs"]), "shots": SHOTS,
                 "device": DEVICE, "account": ACCOUNT,
                 "min_delta": MIN_DELTA, "exp008_seed": EXP008_SEED,
                 "configs": {arm: dict(CONFIGS[arm]) for arm in CONFIGS},
                 "easy_hard_rule": "easy: depth <= 8; hard: depth >= 12 "
                                   "(src/harness.py:52,150-152)",
                 "plan_sha256": _sha_file(dd / "plan.json"),
                 "ledger_view": {"jobs_collected": lv["n"],
                                 "usd_observed": round(lv["usd"], 6)}},
        "a1": a1, "a2": a2, "a3": a3, "a4": a4, "a5": a5,
        "jobs": job_view,
    }


def _render_analysis_md(an: dict) -> str:
    """ANALYSIS.md is rendered ONLY from the analysis dict (no side inputs)."""
    meta, a1, a2, a3, a4, a5 = (an["meta"], an["a1"], an["a2"], an["a3"],
                                an["a4"], an["a5"])
    cells: dict[tuple[int, int], list[float]] = {}
    for m, v in zip(a1["circuit_meta"], a1["pooled"]):
        cells.setdefault((m["n"], m["depth"]), []).append(v)
    rows = "\n".join(
        f"| {n} | {d} | {'easy' if d <= CHI_EASY_MAX_DEPTH else 'hard'} "
        f"| {sum(vs) / len(vs):+.6f} |"
        for (n, d), vs in sorted(cells.items()))
    obs, sh = a4["observed"], a4["shifted_to_min_delta"]
    pr = a4["per_rep_single_evaluation"]
    a4b_lines = "\n".join(
        f"- {r}: P(both) observed {pr[r]['observed']['p_both']:.4f} / "
        f"shifted {pr[r]['shifted_to_min_delta']['p_both']:.4f}"
        for r in sorted(pr))
    return f"""# EXP-008-GATE-CALIBRATION — ANALYSIS (auto-rendered by `gate_calib.py analyze`)

generated: {meta['generated_at']} · source of every number below:
`data/analysis.json` (this file is a render, never hand-edited) · plan
sha256 `{meta['plan_sha256'][:16]}…` · {meta['jobs_total']} jobs on
{meta['device']} (TEST account) · campaign min_delta = {meta['min_delta']:.9f}

## A1 — per-circuit paired Δ (challenger − baseline)
- pooled mean over the 48 circuits: **{a1['pooled_mean']:+.6f}**
- per-rep means: rep1 {a1['per_rep_mean']['rep1']:+.6f} · rep2 {a1['per_rep_mean']['rep2']:+.6f}
- pooled Δ by (n, d) cell (mean over the 3 instances; full 48-value arrays
  in analysis.json):

| n | d | class | pooled Δ |
|---|---|-------|----------|
{rows}

## A2 — bootstrap 95% CI over the 48 circuits
{a2['n_boot']} resamples, numpy default_rng({a2['seed']}), percentile method:
**[{a2['ci_low']:+.6f}, {a2['ci_high']:+.6f}]**

## A3 — same-config repeatability |rep1 − rep2|
- BASELINE (uniform64): mean {a3['base']['mean']:.6f}, sd {a3['base']['sd']:.6f}
  — {a3['base']['mean_over_min_delta']:.2f}× min_delta
- CHALLENGER (easy32hard128): mean {a3['chal']['mean']:.6f}, sd {a3['chal']['sd']:.6f}
  — {a3['chal']['mean_over_min_delta']:.2f}× min_delta
- min_delta = {a3['vs_min_delta']['min_delta']:.9f}: the gate's own noise
  yardstick vs the measured rep-to-rep noise above.

## A4 — fidelity-component pass probability at the n=12 decision scale
{a4['n_draws']} subset draws (numpy default_rng({a4['subset_seed']})),
inner bootstrap {a4['inner_bootstrap']['resamples']} resamples
(default_rng({a4['inner_bootstrap']['seed']})), CI rule: exclude 0 iff
ci_low > 0 (campaign semantics). This simulates ONLY the gate's fidelity
components (mean > min_delta AND CI excludes 0); the campaign's cost gate
(wall-time ratio ≤ 1.02) is NOT simulated — EXP-008's per-config cost is
deterministic. The fresh library includes n=22 circuits (absent from the
frozen suite); subset draws model circuit-subset choice, not fresh shot
noise.

- observed effect (pooled Δ as-is, mean {a1['pooled_mean']:+.6f}):
  P(mean Δ > min_delta) = {obs['p_mean_gt_min_delta']:.4f}
  P(CI excludes 0) = {obs['p_ci_excludes_zero']:.4f}
  **P(both) = {obs['p_both']:.4f}**
- shifted effect (true mean = min_delta exactly, shift
  {a4['shift_applied']:+.6f}):
  P(mean Δ > min_delta) = {sh['p_mean_gt_min_delta']:.4f}
  P(CI excludes 0) = {sh['p_ci_excludes_zero']:.4f}
  **P(both) = {sh['p_both']:.4f}**
- A4b, per-rep single-evaluation libraries (same circuit subsets; the
  pooled two-rep library and these bracket the campaign's
  single-evaluation decision):
{a4b_lines}

DEVIATION (preregistered in PREREGISTRATION.json): the inner bootstrap uses
{a4['inner_bootstrap']['resamples']} resamples per draw, not the campaign
decision bootstrap's 5000 (src/metrics.py:128, seed 3) — {a4['n_draws']}
draws × 5000 resamples × 12 circuits was the nesting feasibility bound;
2000 is fixed here and stated up front. The inner rng(13) stream advances
across draws within each effect level (fresh stream per level) — an
approximation of the campaign's fresh-per-decision rng.

## A5 — frozen prediction (scored once, here)
point +{a5['point']:.3f}, band [+{a5['band_low']:.3f}, +{a5['band_high']:.3f}]
(frozen in PREREGISTRATION.json BEFORE any dispatch) ·
observed pooled mean **{a5['observed']:+.6f}** · in_band = **{a5['in_band']}**

## Traceability
Per-job XEB, provider job ids and run statuses: `data/analysis.json` (`jobs`).
Raw counts: `data/counts/<job_name>.json`. Bookkeeping: `ledger/jobs.sqlite`
(exp_id `{meta['exp_id']}`, {meta['ledger_view']['jobs_collected']} collected
jobs, ${meta['ledger_view']['usd_observed']:.2f}). Truth: local statevector
probabilities under `data/truth/` (sha-pinned in `data/plan.json`).
"""


def _inputs_digest(dd: pathlib.Path, plan: dict) -> str:
    """Digest over EVERY analysis input: plan.json bytes + all counts blobs
    (name-stamped, sorted) — the scoring freeze's no-overwrite key."""
    h = hashlib.sha256()
    h.update((dd / "plan.json").read_bytes())
    for j in sorted(plan["jobs"], key=lambda x: x["name"]):
        h.update(j["name"].encode())
        h.update((dd / "counts" / f"{j['name']}.json").read_bytes())
    return h.hexdigest()


def cmd_analyze(args: argparse.Namespace) -> int:
    dd = _resolve_dd(args)
    guard_paths("(analyze path guard)", args.data_dir)
    plan = load_plan(dd / "plan.json")
    verify_artifact_hashes(plan, dd)
    an_path = dd / "analysis.json"
    digest = _inputs_digest(dd, plan)
    if an_path.exists():
        prev = json.loads(an_path.read_text()).get("meta", {})
        if prev.get("input_digest") != digest:
            raise SystemExit(
                f"REFUSED: {an_path} exists but the analysis INPUTS changed "
                "since it was written (digest mismatch) — investigate "
                "before any re-run; scoring is once-only")
        if not getattr(args, "redo", False):
            raise SystemExit(
                f"REFUSED: {an_path} already exists with IDENTICAL inputs "
                "(digest match) — scoring is once-only; pass --redo to "
                "re-render from the same inputs")
    an = run_analysis(plan, dd)
    an["meta"]["input_digest"] = digest
    _atomic_write(an_path, json.dumps(an, indent=2))
    _atomic_write(EXP_DIR / "ANALYSIS.md", _render_analysis_md(an))
    print(f"[exp008] analysis: pooled Δ {an['a1']['pooled_mean']:+.6f} "
          f"CI [{an['a2']['ci_low']:+.6f}, {an['a2']['ci_high']:+.6f}] "
          f"p_pass(observed)={an['a4']['observed']['p_both']:.4f} "
          f"p_pass(@min_delta)="
          f"{an['a4']['shifted_to_min_delta']['p_both']:.4f} "
          f"in_band={an['a5']['in_band']} -> {dd / 'analysis.json'} + "
          f"{EXP_DIR / 'ANALYSIS.md'}")
    return 0


# ------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(
        description="EXP-008 gate calibration (preregistered; see "
                    "experiments/EXP-008-GATE-CALIBRATION/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (
            ("plan", cmd_plan, "pure-local: circuits + exact truths + plan.json"),
            ("dispatch", cmd_dispatch, "guarded cloud dispatch via bq.run_batch"),
            ("collect", cmd_collect, "idempotent results fetch"),
            ("analyze", cmd_analyze, "preregistered analysis A1-A5 + ANALYSIS.md")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--data-dir", default=str(CANONICAL_DATA),
                      help="data dir holding plan.json/counts/truth "
                           "(default: experiments/EXP-008-GATE-CALIBRATION/data)")
        if name == "analyze":
            p.add_argument("--redo", action="store_true",
                           help="re-render analysis.json/ANALYSIS.md when it "
                                "already exists AND the inputs digest is "
                                "unchanged (scoring is otherwise once-only)")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
