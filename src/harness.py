"""G3/G4 — flywheel round engine (one mutation per round, ledger-enforced PROMOTE).

POST-PIVOT design (EXP-003): the acceptance suite is 48 exact-truth RCS circuits
on mps.cpu. Score = per-circuit normalized XEB (canonical count keys).
Mutation space (frozen): {chi_alloc, permutation, shots_alloc}. One per round.

Sub-commands:
  baseline        G3: incumbent on train+val, val a SECOND time for noise
                  calibration (min_delta), chi telemetry sweep (val, chi in
                  {32,128,256}), ledger EXP-004, campaign PREDICTIONS row.
  propose         print the next round's mutation without running anything.
  round --k N     run round N: candidate = incumbent + ONE mutation; evaluate on
                  train (selection feedback) + val (decision); paired stats;
                  register EXP-005-RN (flywheel) / EXP-006-RN (control) with
                  preregistered gates; record; PROMOTE via ledger only if the
                  gates pass. Flywheel rounds write a researcher insight;
                  control rounds never do (no memory).
  canary --k N    noise canary: re-evaluate the INCUMBENT on val; drift beyond
                  the noise band tightens min_delta (state.drift_flag).

State: runs/flywheel/state.json (atomic tmp+replace).
Fraud guards: refuses rounds already terminal in the ledger or in state.history;
never re-runs a healthy recorded run (L-004); refuses after holdout sentinel.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

FLYWHEEL_DIR = ROOT / "runs" / "flywheel"
STATE_PATH = FLYWHEEL_DIR / "state.json"
LEDGER = [".venv/bin/python", "tools/ledger.py"]

BASELINE_CONFIG = {
    "name": "r0-baseline",
    "device": "mps.cpu",
    "chi_alloc": "uniform64",
    "permutation_seed": None,   # identity site order
    "shots_alloc": "uniform20k",
}

# mutation families (ONE per round; deterministic 'propose')
CHI_PRESETS = {          # chi by depth class (easy: d<=8, hard: d>=12)
    "uniform64":    {"easy": 64,  "hard": 64},
    "uniform32":    {"easy": 32,  "hard": 32},
    "uniform128":   {"easy": 128, "hard": 128},
    "uniform256":   {"easy": 256, "hard": 256},
    "easy32hard128": {"easy": 32, "hard": 128},
    "easy16hard128": {"easy": 16, "hard": 128},
    "easy32hard256": {"easy": 32, "hard": 256},
}
PERM_SEEDS = [11, 23, 37, 51]
SHOT_PRESETS = {         # shots by depth class; totals preserved per 6+6 cells
    "uniform20k":   {"easy": 20000, "hard": 20000},   # 6*20k + 6*20k = 240k
    "easy10khard30k": {"easy": 10000, "hard": 30000},  # 6*10k + 6*30k = 240k
    "easy4khard36k":  {"easy": 4000,  "hard": 36000},  # 6*4k  + 6*36k = 240k
}

CHI_LADDER = ["easy32hard128", "uniform128", "easy32hard256", "uniform256",
              "easy16hard128", "uniform32"]
SHOT_LADDER = ["easy10khard30k", "easy4khard36k"]


# ---------------------------------------------------------------- utilities

def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"campaign": None, "round": 0, "incumbent": None, "min_delta": None,
            "history": [], "canaries": [], "drift_flag": False,
            "control_incumbent": None}


def save_state(state: dict) -> None:
    FLYWHEEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def ledger(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(LEDGER + list(args), cwd=ROOT, capture_output=True,
                          text=True)


def manifest() -> dict:
    m = ROOT / "suite" / "MANIFEST.json"
    if not m.exists():
        raise SystemExit("FAIL: suite not frozen (suite/MANIFEST.json missing)")
    if (ROOT / "suite" / ".HOLDOUT_EVALUATED").exists():
        raise SystemExit("FAIL: campaign CLOSED (holdout evaluated once); "
                         "no further rounds or canaries are legal")
    return json.loads(m.read_text())


def split_circuits(man: dict, split: str) -> list[dict]:
    return [c for c in man["circuits"] if c["split"] == split]


def perm_of(n: int, seed: int | None) -> list[int] | None:
    if seed is None:
        return None
    import numpy as np
    return list(np.random.default_rng(seed).permutation(n))


def inv_perm(perm: list[int]) -> list[int]:
    inv = [0] * len(perm)
    for logical, site in enumerate(perm):
        inv[site] = logical
    return inv


def permute_bitstring(s: str, perm: list[int]) -> str:
    """out[perm[i]] = s[i] (site-order string of logical string s)."""
    out = ["0"] * len(s)
    for logical, site in enumerate(perm):
        out[site] = s[logical]
    return "".join(out)


def unpermute_key(s: str, perm: list[int]) -> str:
    """Map a permuted-circuit count key back to logical qubit order.

    Keys arrive in qiskit display order (leftmost char = site n-1). The
    permuted circuit puts logical L's bit at site perm[L], so unpermuting is
    a GATHER by perm in site space; the reversal to site order and back is
    required because string-position reversal does not commute with the
    permutation (G4 r4 scoring bug, 2026-10-06 — old path scored ~0 XEB on
    every circuit; see src/repro_perm_bug.py).
    """
    site_bits = s[::-1]
    logical = "".join(site_bits[perm[l]] for l in range(len(s)))
    return logical[::-1]


def chi_for(cfg: dict, depth: int) -> int:
    klass = CHI_PRESETS[cfg["chi_alloc"]]
    return klass["easy"] if depth <= 8 else klass["hard"]


def shots_for(cfg: dict, depth: int) -> int:
    klass = SHOT_PRESETS[cfg["shots_alloc"]]
    return klass["easy"] if depth <= 8 else klass["hard"]


# ---------------------------------------------------------------- evaluation

def evaluate_config(client, man: dict, cfg: dict, circuits: list[dict],
                    exp_id: str, purpose: str) -> dict:
    """One mps.cpu job per circuit under `cfg`; normalized XEB per circuit."""
    from bq import run_batch, RoundSpec
    from circuits import load_circuit, permuted, measure_all
    from metrics import xeb_normalized, canonical_counts
    import numpy as np

    specs, meta = [], []
    for c in circuits:
        qc = load_circuit(ROOT / "suite" / c["qpy"])
        if qc.num_clbits:
            qc = qc.remove_final_measurements(inplace=False)
        pi = perm_of(qc.num_qubits, cfg["permutation_seed"])
        if pi is not None:
            qc = permuted(qc, pi)
        specs.append(RoundSpec(
            measure_all(qc), shots=shots_for(cfg, c["depth"]),
            options={"mps_bond_dimension": chi_for(cfg, c["depth"])},
            label=f"{purpose}-{c['id']}"))
        meta.append({"id": c["id"], "depth": c["depth"], "n": c["n"],
                     "truth": c["truth"], "perm": pi})

    res = run_batch(client, exp_id, purpose, specs, device=cfg["device"],
                    max_concurrent=2)
    by_name = {v["job"].job_name: v for v in res["jobs"].values()}
    rows, total_min, usd = [], 0.0, 0.0
    for m in meta:
        r = by_name.get(f"{purpose}-{m['id']}")
        job = r["job"] if r else None
        if r is None or r["counts"] is None:
            rows.append({"id": m["id"], "xeb": None,
                         "job_id": job.job_id if job else None,
                         "error": (job.error_message if job else "missing")})
            continue
        counts = canonical_counts(r["counts"], cfg["device"])
        if m["perm"] is not None:
            counts = {unpermute_key(k, m["perm"]): v for k, v in counts.items()}
        p = np.load(ROOT / "suite" / m["truth"], mmap_mode="r")
        wall_min = ((job.queue_time_ms or 0) + (job.run_time_ms or 0)) / 60000
        total_min += wall_min
        usd += job.cost or 0.0
        rows.append({"id": m["id"], "xeb": round(xeb_normalized(counts, p), 6),
                     "job_id": job.job_id, "wall_min": round(wall_min, 4),
                     "chi": chi_for(cfg, m["depth"]),
                     "shots": shots_for(cfg, m["depth"])})
    return {"rows": rows, "mean_xeb": _mean([r["xeb"] for r in rows]),
            "cost_min": round(total_min, 4), "usd": round(usd, 6),
            "jobs": len(rows), "config": cfg}


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- ledger flow

def exp_id_for_round(k: int, control: bool) -> str:
    prefix = "EXP-006" if control else "EXP-005"
    return f"{prefix}-R{k:02d}"


def round_gates(incumbent: dict, min_delta: float, drift_factor: float) -> dict:
    md = min_delta * drift_factor
    return {
        "fidelity_min": round(incumbent["mean_xeb"] + md, 6),
        "score_max": round(incumbent["cost_min"] * 1.02, 4),
        "ci_excludes_null": True,
        "usd_max": 0.50,
        "jobs_max": 40,
    }


def write_round_spec(k: int, exp_id: str, cfg: dict, incumbent_cfg: dict,
                     mutation: dict, gates: dict, min_delta: float,
                     control: bool) -> pathlib.Path:
    d = ROOT / "experiments" / exp_id
    d.mkdir(parents=True, exist_ok=True)
    arm = "no-memory CONTROL arm" if control else "flywheel arm"
    spec = f"""# {exp_id} — flywheel round {k} ({arm})

ONE mutation vs the incumbent: {json.dumps(mutation)}

Incumbent config: {json.dumps(incumbent_cfg)}
Candidate config: {json.dumps(cfg)}

Decision rule (frozen in EXP-003): paired per-circuit normalized-XEB deltas on
the 12 val circuits; bootstrap 95% CI of the mean must exclude zero AND mean
delta > min_delta; cost (sum of queue+run minutes over val jobs, L-005)
noninferior within 2%. Enforced by ledger gates: {json.dumps(gates)}

Train-circuit evaluation is selection feedback only; never part of the gate.
"""
    (d / "SPEC.md").write_text(spec)
    (d / "PREREGISTRATION.json").write_text(json.dumps({
        "exp_id": exp_id, "round": k, "arm": "control" if control else "flywheel",
        "mutation": mutation, "candidate_config": cfg,
        "incumbent_config": incumbent_cfg, "gates": gates,
        "min_delta_effective": min_delta,
        "frozen_at": utcnow(),
    }, indent=2))
    return d / "SPEC.md"


# ---------------------------------------------------------------- proposals

def propose_flywheel(state: dict, man: dict) -> dict:
    """Memory arm: next family with live evidence, next untried ladder value.

    Deterministic given (state, manifest). Families with 3 consecutive
    rejections go into cooldown. When everything is tried, permutations extend
    past the initial seed list (deterministic successor seeds)."""
    hist = state["history"]
    fam_stats: dict[str, list[bool]] = {}
    tried: dict[str, set] = {}
    for h in hist:
        if h.get("arm") != "flywheel":
            continue
        fam = h["mutation"]["family"]
        fam_stats.setdefault(fam, []).append(h["accepted"])
        tried.setdefault(fam, set()).add(json.dumps(h["mutation"]["value"],
                                                    sort_keys=True))
    cooldown = {f for f, acc in fam_stats.items()
                if len(acc) >= 3 and not any(acc[-3:])}

    for fam in ("chi_alloc", "permutation", "shots_alloc"):
        if fam in cooldown:
            continue
        if fam == "chi_alloc":
            for v in CHI_LADDER:
                if json.dumps(v, sort_keys=True) not in tried.get(fam, set()):
                    return {"family": "chi_alloc", "value": v}
        elif fam == "permutation":
            for v in PERM_SEEDS + [101, 137, 173]:
                if json.dumps(v, sort_keys=True) not in tried.get(fam, set()):
                    return {"family": "permutation", "value": v}
        else:
            for v in SHOT_LADDER:
                if json.dumps(v, sort_keys=True) not in tried.get(fam, set()):
                    return {"family": "shots_alloc", "value": v}
    # saturated: deepen the permutation search (deterministic successors)
    used = tried.get("permutation", set())
    s = 211
    while json.dumps(s, sort_keys=True) in used:
        s += 41
    return {"family": "permutation", "value": s}


def propose_control(k: int) -> dict:
    """No-memory arm: FIXED ladder, zero dependence on any result."""
    seq = ([{"family": "chi_alloc", "value": v} for v in CHI_LADDER]
           + [{"family": "permutation", "value": s} for s in PERM_SEEDS]
           + [{"family": "shots_alloc", "value": v} for v in SHOT_LADDER])
    return seq[(k - 1) % len(seq)]


def apply_mutation(cfg: dict, mutation: dict) -> dict:
    out = json.loads(json.dumps(cfg))
    fam, val = mutation["family"], mutation["value"]
    if fam == "chi_alloc":
        if val not in CHI_PRESETS:
            raise SystemExit(f"FAIL: unknown chi preset {val}")
        out["chi_alloc"] = val
        out["name"] = f"chi-{val}"
    elif fam == "permutation":
        out["permutation_seed"] = int(val)
        out["name"] = f"perm{val}"
    elif fam == "shots_alloc":
        if val not in SHOT_PRESETS:
            raise SystemExit(f"FAIL: unknown shots preset {val}")
        out["shots_alloc"] = val
        out["name"] = f"shots-{val}"
    else:
        raise SystemExit(f"FAIL: unknown mutation family {fam}")
    return out


def add_insight(statement: str, falsifier: str) -> None:
    subprocess.run([".venv/bin/python", "tools/rsi.py", "add-ins",
                    "--statement", statement, "--falsifier", falsifier],
                   cwd=ROOT, capture_output=True, text=True)


# ---------------------------------------------------------------- commands

def cmd_baseline(args) -> int:
    from bq import get_client
    man = manifest()
    state = load_state()
    if state.get("incumbent"):
        raise SystemExit("FAIL: baseline already ledgered (L-004 no-healthy-rerun)")
    exp_dir = ROOT / "experiments" / "EXP-004-G3-BASELINE"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "SPEC.md").write_text("""# EXP-004 — G3 baseline incumbent

Incumbent (uniform-allocation config) on the frozen 48-circuit suite:
mps.cpu, chi=64 everywhere, 20k shots everywhere, identity site order.

Runs: val x2 (the second identical pass calibrates pure run-to-run noise),
train x1, plus a chi telemetry sweep on the val circuits at chi in
{32, 128, 256} (report evidence for the chi-vs-XEB gradient; chi=64 comes
from val run 1). NO acceptance decision here — this IS the incumbent.

min_delta formula (frozen): max(2.0 * sd(paired per-circuit XEB deltas between
the two identical val runs), 0.005).

Gates: caps only (jobs_max=90, usd_max=0.50; all cpu-class devices are $0).
""")
    (exp_dir / "PREREGISTRATION.json").write_text(json.dumps({
        "exp_id": "EXP-004-G3-BASELINE",
        "hypothesis": "The uniform chi=64 / 20k-shot MPS config defines a "
                      "beatable round-0 incumbent: its val XEB is materially "
                      "below 1 on the deep circuits (G1 evidence: 0.76 at "
                      "26q d=16), so allocation mutations have headroom.",
        "config": BASELINE_CONFIG, "frozen_at": utcnow(),
        "min_delta_formula": "max(2.0*sd_paired, 0.005)",
        "chi_sweep": [32, 64, 128, 256],
    }, indent=2))
    out = ledger("register", "EXP-004-G3-BASELINE", str(exp_dir / "SPEC.md"),
                 "--gate", "jobs_max=90", "--gate", "usd_max=0.50")
    if out.returncode != 0 and "already registered" not in out.stdout:
        raise SystemExit(f"FAIL register EXP-004: {out.stdout}{out.stderr}")

    client = get_client()
    val = split_circuits(man, "val")
    train = split_circuits(man, "train")
    print(f"[g3] baseline: {len(train)} train + {len(val)} val (x2) + chi sweep")
    run1 = evaluate_config(client, man, BASELINE_CONFIG, val,
                           "EXP-004-G3-BASELINE", "g3val1")
    run2 = evaluate_config(client, man, BASELINE_CONFIG, val,
                           "EXP-004-G3-BASELINE", "g3val2")
    train_run = evaluate_config(client, man, BASELINE_CONFIG, train,
                                "EXP-004-G3-BASELINE", "g3train")
    chi_sweep = {}
    for chi in (32, 128, 256):
        cfg = json.loads(json.dumps(BASELINE_CONFIG))
        cfg["chi_alloc"] = f"uniform{chi}"
        cfg["name"] = f"chi-{chi}"
        chi_sweep[chi] = evaluate_config(client, man, cfg, val,
                                         "EXP-004-G3-BASELINE", f"g3chi{chi}")

    paired = [(a["xeb"] - b["xeb"]) for a, b in zip(run1["rows"], run2["rows"])
              if a["xeb"] is not None and b["xeb"] is not None]
    import numpy as np
    sd = float(np.std(paired, ddof=1)) if len(paired) > 1 else 0.01
    min_delta = max(2.0 * sd, 0.005)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = FLYWHEEL_DIR / f"{stamp}_g3"
    run_dir.mkdir(parents=True, exist_ok=True)
    total_jobs = (run1["jobs"] + run2["jobs"] + train_run["jobs"]
                  + sum(s["jobs"] for s in chi_sweep.values()))
    (run_dir / "metrics.json").write_text(json.dumps({
        "gate": "G3", "exp": "EXP-004-G3-BASELINE", "config": BASELINE_CONFIG,
        "val_run1": run1, "val_run2": run2, "train": train_run,
        "chi_sweep": {str(k): v for k, v in chi_sweep.items()},
        "noise_sd_paired": sd, "min_delta": min_delta,
        "usd": round(run1["usd"] + run2["usd"] + train_run["usd"]
                     + sum(s["usd"] for s in chi_sweep.values()), 6),
        "jobs": total_jobs,
    }, indent=2))
    state.update({
        "campaign": {"frozen_suite_sha256": man["suite_sha256"],
                     "started_at": utcnow()},
        "round": 0,
        "incumbent": {"config": BASELINE_CONFIG, "mean_xeb": run1["mean_xeb"],
                      "val_rows": run1["rows"], "cost_min": run1["cost_min"]},
        # control arm's OWN lineage: identical r0 (same baseline evaluation) so
        # the two arms start equal; from here on they never share incumbents
        "control_incumbent": {"config": json.loads(json.dumps(BASELINE_CONFIG)),
                              "mean_xeb": run1["mean_xeb"],
                              "val_rows": json.loads(json.dumps(run1["rows"])),
                              "cost_min": run1["cost_min"]},
        "incumbent_val_run2": run2["rows"],
        "min_delta": min_delta, "noise_sd": sd,
        "history": [], "canaries": [], "drift_flag": False,
        "g3_run_dir": str(run_dir.relative_to(ROOT)),
    })
    save_state(state)
    out = ledger("record", "EXP-004-G3-BASELINE", str(run_dir))
    if out.returncode != 0:
        raise SystemExit(f"FAIL record EXP-004: {out.stdout}{out.stderr}")
    if run1["mean_xeb"] is not None:
        base = run1["mean_xeb"]
        point = base + 0.5 * (1.0 - base)
        pred = subprocess.run(
            [".venv/bin/python", "tools/rsi.py", "predict",
             "--campaign", "flywheel-test",
             "--metric", "final_incumbent_holdout_mean_xeb",
             "--point", f"{point:.6f}",
             "--band", f"{base:.6f},{max(point, 0.999):.6f}"],
            cwd=ROOT, capture_output=True, text=True)
        if pred.returncode != 0:
            raise SystemExit(
                f"FAIL prediction freeze (rsi.py predict rc={pred.returncode}): "
                f"{pred.stdout}{pred.stderr}")
        print(f"[g3] prediction: {pred.stdout.strip()}{pred.stderr.strip()}")
    print(f"[g3] mean XEB={run1['mean_xeb']:.5f} noise_sd={sd:.5f} "
          f"min_delta={min_delta:.5f} jobs={total_jobs} -> {run_dir}")
    return 0


def cmd_propose(args) -> int:
    state = load_state()
    k = state["round"] + 1
    m = propose_control(k) if args.control else propose_flywheel(state, manifest())
    print(json.dumps(m))
    return 0


def cmd_round(args) -> int:
    from bq import get_client
    man = manifest()
    state = load_state()
    control = bool(args.control)
    if args.k:
        k = args.k
    elif control:
        k = 1 + sum(1 for h in state.get("history", [])
                    if h["arm"] == "control")
    else:
        k = state["round"] + 1
    exp_id = exp_id_for_round(k, control)
    if any(h["round"] == k and h["arm"] == ("control" if control else "flywheel")
           for h in state.get("history", [])):
        raise SystemExit(f"FAIL: round {k} already in state history (L-004)")
    show = ledger("show", exp_id)
    if show.returncode == 0 and "REGISTERED" not in show.stdout \
            and "not registered" not in show.stdout:
        raise SystemExit(f"FAIL: {exp_id} already terminal in ledger (L-004)")

    # each arm mutates ITS OWN incumbent (no memory may leak across arms;
    # a control acceptance must never overwrite the flywheel lineage)
    if control and state.get("control_incumbent") is None:
        raise SystemExit("FAIL: run `harness.py baseline` first (control "
                         "lineage is seeded from the G3 r0 evaluation)")
    inc = state["control_incumbent"] if control else state["incumbent"]
    mutation = (json.loads(args.mutation) if args.mutation else
                (propose_control(k) if control else propose_flywheel(state, man)))
    inc_cfg = inc["config"]
    cfg = apply_mutation(inc_cfg, mutation)
    print(f"[r{k}] {'CONTROL' if control else 'FLYWHEEL'} mutation={mutation} "
          f"config={cfg['name']}")

    drift_factor = 1.5 if state.get("drift_flag") else 1.0
    gates = round_gates(inc, state["min_delta"], drift_factor)
    spec = write_round_spec(k, exp_id, cfg, inc_cfg, mutation, gates,
                            state["min_delta"] * drift_factor, control)
    gate_args = []
    for gk, gv in gates.items():
        gate_args += ["--gate", f"{gk}={gv}"]
    out = ledger("register", exp_id, str(spec), *gate_args)
    if out.returncode != 0 and "already registered" not in (out.stdout + out.stderr):
        raise SystemExit(f"FAIL register: {out.stdout}{out.stderr}")
    # recovery path: a round whose experiment is REGISTERED but unrecorded
    # (crash mid-run, no metrics) is legal to re-run; L-004 still blocks any
    # attempt to re-run a round that reached `record`

    client = get_client()
    val = split_circuits(man, "val")
    train = split_circuits(man, "train")
    val_run = evaluate_config(client, man, cfg, val, exp_id,
                              f"r{k}{'c' if control else ''}val")
    train_run = evaluate_config(client, man, cfg, train, exp_id,
                                f"r{k}{'c' if control else ''}train")

    inc_rows = {r["id"]: r["xeb"] for r in inc["val_rows"]}
    deltas = [(r["xeb"] - inc_rows[r["id"]]) for r in val_run["rows"]
              if r["xeb"] is not None and inc_rows.get(r["id"]) is not None]
    from metrics import paired_delta, acceptance
    stats = paired_delta(deltas)
    cost_ratio = (val_run["cost_min"] / inc["cost_min"]
                  if inc["cost_min"] else 1.0)
    acc = acceptance(stats, state["min_delta"] * drift_factor, cost_ratio)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = FLYWHEEL_DIR / f"{stamp}_r{k}{'_control' if control else ''}"
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "fidelity": stats["mean_delta"] + inc["mean_xeb"],
        "score": val_run["cost_min"],
        "usd": round(val_run["usd"] + train_run["usd"], 6),
        "jobs": val_run["jobs"] + train_run["jobs"],
        "ci_excludes_null": acc["ci_excludes_null"],
        "mean_delta": stats["mean_delta"], "ci_low": stats["ci_low"],
        "ci_high": stats["ci_high"], "cost_ratio": round(cost_ratio, 6),
        "accepted": acc["accepted"], "mutation": mutation, "round": k,
        "arm": "control" if control else "flywheel",
        "val": val_run, "train": train_run, "gates": gates,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    out = ledger("record", exp_id, str(run_dir))
    if out.returncode != 0:
        raise SystemExit(f"FAIL record: {out.stdout}{out.stderr}")

    if acc["accepted"]:
        out = ledger("promote", exp_id, "--run", str(run_dir))
        print(f"[r{k}] promote -> {out.stdout.strip()}")
        if out.returncode != 0:
            raise SystemExit(f"FAIL promote (ledger refused): {out.stderr}")
        new_inc = {"config": cfg, "mean_xeb": val_run["mean_xeb"],
                   "val_rows": val_run["rows"], "cost_min": val_run["cost_min"]}
        if control:
            state["control_incumbent"] = new_inc
        else:
            state["incumbent"] = new_inc
    if not control:
        state["round"] = k  # rounds advance on rejection too — rejection is data
        add_insight(
            f"Round {k} ({mutation['family']}={mutation['value']}): mean val "
            f"delta {stats['mean_delta']:+.5f}, CI [{stats['ci_low']:+.5f}, "
            f"{stats['ci_high']:+.5f}], cost ratio {cost_ratio:.3f} -> "
            f"{'ACCEPTED' if acc['accepted'] else 'rejected'}.",
            "Any future val evaluation of the same config that regresses "
            "beyond noise_sd falsifies this round's acceptance; a holdout "
            "delta opposite in sign falsifies the campaign.")
    state["history"].append({
        "round": k, "arm": "control" if control else "flywheel", "exp_id": exp_id,
        "mutation": mutation, "config": cfg["name"],
        "chi_alloc": cfg["chi_alloc"], "shots_alloc": cfg["shots_alloc"],
        "permutation_seed": cfg["permutation_seed"],
        "accepted": acc["accepted"], "mean_delta": stats["mean_delta"],
        "ci_low": stats["ci_low"], "ci_high": stats["ci_high"],
        "val_mean_xeb": val_run["mean_xeb"], "cost_min": val_run["cost_min"],
        "run_dir": str(run_dir.relative_to(ROOT)), "at": utcnow(),
    })
    save_state(state)
    print(f"[r{k}] delta={stats['mean_delta']:+.5f} CI[{stats['ci_low']:+.5f},"
          f"{stats['ci_high']:+.5f}] accepted={acc['accepted']} "
          f"cost_ratio={cost_ratio:.3f}")
    return 0


def cmd_canary(args) -> int:
    from bq import get_client
    man = manifest()
    state = load_state()
    k = args.k
    exp_id = f"EXP-005-CANARY{k:02d}"
    # noise canaries make no acceptance decision; register caps-only so every
    # job still runs under a REGISTERED experiment (traceability invariant)
    exp_dir = ROOT / "experiments" / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "SPEC.md").write_text(f"""# {exp_id} — noise canary at flywheel round {k}

Re-evaluates the CURRENT incumbent on the 12 val circuits (identical config,
fresh sampling noise). Decision rule (frozen): |mean paired delta| >
2 x noise_sd (from G3) sets state.drift_flag, which tightens round gates by
1.5x min_delta. No promotion, no mutation, no insight written.

Gates: caps only (jobs_max=14, usd_max=0.50).
""")
    (exp_dir / "PREREGISTRATION.json").write_text(json.dumps({
        "exp_id": exp_id, "kind": "noise_canary", "round_k": k,
        "drift_rule": "|mean paired delta| > 2*noise_sd -> drift_flag",
        "frozen_at": utcnow(),
    }, indent=2))
    out = ledger("register", exp_id, str(exp_dir / "SPEC.md"),
                 "--gate", "jobs_max=14", "--gate", "usd_max=0.50")
    if out.returncode != 0 and "already registered" not in (out.stdout + out.stderr):
        raise SystemExit(f"FAIL register {exp_id}: {out.stdout}{out.stderr}")

    client = get_client()
    val = split_circuits(man, "val")
    run = evaluate_config(client, man, state["incumbent"]["config"], val,
                          exp_id, f"canary{k}")
    inc_rows = {r["id"]: r["xeb"] for r in state["incumbent"]["val_rows"]}
    deltas = [(r["xeb"] - inc_rows[r["id"]]) for r in run["rows"]
              if r["xeb"] is not None and inc_rows.get(r["id"]) is not None]
    import numpy as np
    drift = bool(deltas) and abs(float(np.mean(deltas))) > 2.0 * state["noise_sd"]
    state["canaries"].append({"round_k": k, "mean_delta": _mean(deltas),
                              "drift": drift, "rows": run["rows"], "at": utcnow()})
    if drift:
        state["drift_flag"] = True
    save_state(state)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    can_dir = FLYWHEEL_DIR / f"{stamp}_canary{k}"
    can_dir.mkdir(parents=True, exist_ok=True)
    (can_dir / "metrics.json").write_text(json.dumps({
        "gate": "canary", "exp": exp_id, "round_k": k,
        "incumbent": state["incumbent"]["config"],
        "mean_delta": _mean(deltas), "drift": drift,
        "noise_sd": state["noise_sd"], "val": run,
        "usd": run["usd"], "jobs": run["jobs"],
    }, indent=2))
    out = ledger("record", exp_id, str(can_dir))
    if out.returncode != 0:
        raise SystemExit(f"FAIL record {exp_id}: {out.stdout}{out.stderr}")
    print(f"[canary@r{k}] mean_delta={_mean(deltas)} drift={drift}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline").set_defaults(fn=cmd_baseline)
    p = sub.add_parser("propose")
    p.add_argument("--control", action="store_true")
    p.set_defaults(fn=cmd_propose)
    p = sub.add_parser("round")
    p.add_argument("--k", type=int, default=0)
    p.add_argument("--mutation")
    p.add_argument("--control", action="store_true")
    p.set_defaults(fn=cmd_round)
    p = sub.add_parser("canary")
    p.add_argument("--k", type=int, required=True)
    p.set_defaults(fn=cmd_canary)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
