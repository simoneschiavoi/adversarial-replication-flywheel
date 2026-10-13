"""G2 — freeze the 48-circuit campaign suite. ONE-SHOT: refuses if MANIFEST exists.

PIVOT DESIGN (post G1.5b/G1.5c; see EXP-002 park + EXP-002B):
  The sponsor peaked-circuit endpoint is 403-denied on this account, and the
  pauli-path truncation window on random RCS is degenerate at feasible epsilon
  (1e-5 rejected server-side; 1e-3 returns EV exactly 0.0). Per the
  preregistered cut order, the acceptance suite falls back to the EXACT-TRUTH
  lane and the mutation space shrinks to the core set {chi, permutation, shots}:

  Lane R (48 = the whole suite): local RCS brickwork n in {20,24,26} x depth
      in {4,8,12,16} x 4 seeds. Scored by per-circuit NORMALIZED XEB against
      locally computed exact probabilities (float32 truth, sha-pinned).
      Attacker device: mps.cpu (chi/shots/permutation are the knobs).

  Split 24 train / 12 val / 12 LOCKED holdout via a seeded permutation of all
  48 circuits (numpy default_rng(20261107), first 24 train, next 12 val, rest
  holdout). Holdout circuits + truths are chmod-000'd; holdout_eval.py is the
  only reader (one-shot, sentinel-guarded, access-logged).

  Optional telemetry OUTSIDE the frozen suite (added to the report, never to
  the acceptance): pauli-path window at 32-56q (EXP-002B evidence) and mps.cpu
  feasibility at 56q (g15b). These are not part of this manifest.

The freeze dispatches ZERO cloud jobs: all material is local (circuits + truth).

Usage:
  .venv/bin/python -u src/freeze_suite.py            # normal freeze
  .venv/bin/python -u src/freeze_suite.py --check    # verify lock + manifest
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

EXP = "EXP-003-G2-FREEZE"
SPLIT_SEED = 20261107
R_BASE_SEED = 20261100
SIZES = (20, 24, 26)
DEPTHS = (4, 8, 12, 16)
PER_CELL = 4  # seeds per (n, d) -> 3*4*4 = 48 circuits
SUITES = ROOT / "suite"


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(body: dict) -> str:
    """Sha over the manifest body WITHOUT the self-referencing suite_sha256."""
    probe = {k: v for k, v in body.items() if k != "suite_sha256"}
    return hashlib.sha256(
        json.dumps(probe, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def freeze() -> int:
    from circuits import rcs_circuit, save_circuit
    from sim_exact import precompute_suite

    if (SUITES / "MANIFEST.json").exists():
        print("FAIL: suite/MANIFEST.json already exists — the suite is FROZEN. "
              "A second freeze requires deleting the campaign (fraud risk).")
        return 1

    circ_dir = SUITES / "circuits"
    hold_dir = SUITES / "holdout"
    truth_dir = SUITES / "truth"
    for d in (circ_dir, hold_dir, truth_dir):
        d.mkdir(parents=True, exist_ok=True)

    circuits: list[dict] = []
    r_jobs: list[tuple[str, str]] = []
    for n in SIZES:
        for d in DEPTHS:
            for s in range(PER_CELL):
                seed = R_BASE_SEED + n * 100 + d * 10 + s
                qc = rcs_circuit(n, d, seed=seed)
                name = f"rcs_n{n}_d{d}_s{seed}"
                qpy = circ_dir / f"{name}.qpy"
                save_circuit(qc, qpy)
                circuits.append({
                    "id": name, "lane": "R", "n": n, "depth": d, "seed": seed,
                    "qpy": f"circuits/{name}.qpy", "sha256": _sha(qpy),
                    "truth": f"truth/p_{name}.npy",
                })
                r_jobs.append((str(qpy), str(truth_dir / f"p_{name}.npy")))

    print(f"[freeze] exact truth for {len(r_jobs)} circuits (parallel, local)…")
    # 2 workers: 3 simultaneous n26 statevector peaks (~3.3 GiB each) OOM'd
    # the box (swap full, silent kill at 34/48); worker count does not affect
    # the computed truths (deterministic per circuit), only scheduling
    precompute_suite(r_jobs, workers=2)
    for c in circuits:
        c["truth_sha256"] = _sha(SUITES / c["truth"])

    # ---- deterministic split ---------------------------------------------------
    import numpy as np
    rng = np.random.default_rng(SPLIT_SEED)
    perm = rng.permutation(len(circuits))
    for rank, i in enumerate(perm):
        circuits[i]["split"] = ("train" if rank < 24
                                else "val" if rank < 36 else "holdout")
    counts: dict[str, int] = {}
    for c in circuits:
        counts[c["split"]] = counts.get(c["split"], 0) + 1
    by_cell = {}
    for c in circuits:
        k = (c["n"], c["depth"])
        by_cell.setdefault(k, []).append(c["split"])
    print(f"split counts: {counts}")
    print("per-cell (n,d) splits:")
    for k in sorted(by_cell):
        print(f"  n={k[0]:2d} d={k[1]:2d}: {by_cell[k]}")

    # ---- holdout lock ----------------------------------------------------------
    for c in circuits:
        if c["split"] != "holdout":
            continue
        os.rename(circ_dir / f"{c['id']}.qpy", hold_dir / f"{c['id']}.qpy")
        c["qpy"] = f"holdout/{c['id']}.qpy"
        os.rename(SUITES / c["truth"], hold_dir / f"p_{c['id']}.npy")
        c["truth"] = f"holdout/p_{c['id']}.npy"
    (hold_dir / "HOLDOUT_ACCESS.log").write_text(
        f"{dt.datetime.now(dt.timezone.utc).isoformat()} LOCKED at freeze\n")
    for f in hold_dir.iterdir():
        f.chmod(0)
    hold_dir.chmod(0)

    # ---- manifest ---------------------------------------------------------------
    body = {
        "exp": EXP,
        "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "design": "post-pivot exact-truth suite (EXP-002 parked: peaked endpoint "
                  "403; EXP-002B: pauli-path eps window degenerate on random RCS)",
        "split_seed": SPLIT_SEED,
        "split_rule": "seeded permutation over all 48 (numpy default_rng(20261107)); "
                      "first 24 -> train, next 12 -> val, rest -> holdout",
        "acceptance_metric": "mean per-circuit normalized XEB over the 12 val "
                             "circuits, paired per-circuit vs the incumbent; "
                             "cost = sum of (queue+run) minutes of the val jobs",
        "score_definition": "xeb_normalized = raw_linear_xeb / (2^n * sum(p^2) - 1) "
                            "with p = exact local statevector probabilities; "
                            "exact sampler -> 1, uniform -> 0; mps.cpu count keys "
                            "are canonicalized (bit-un-reversed) before scoring",
        "devices": {"attack": "mps.cpu", "exact_anchor": "local statevector (qiskit)"},
        "mutation_space": ["chi_alloc", "permutation", "shots_alloc"],
        "circuits": circuits,
        "counts": counts,
        "holdout_locked": True,
        "freeze_dispatched_cloud_jobs": 0,
    }
    body["suite_sha256"] = canonical_sha(body)
    (SUITES / "MANIFEST.json").write_text(json.dumps(body, indent=2))
    print(f"FROZEN: suite/MANIFEST.json suite_sha256={body['suite_sha256']}")

    # ledger-recordable run artifact (freeze runs zero cloud jobs)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"{stamp}_g2"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps({
        "gate": "G2", "exp": EXP, "suite_sha256": body["suite_sha256"],
        "counts": counts, "circuits": len(circuits),
        "holdout_locked": True, "freeze_dispatched_cloud_jobs": 0,
        "usd": 0.0, "jobs": 0,
    }, indent=2))
    print(f"artifact: {run_dir / 'metrics.json'}")
    return 0


def check() -> int:
    man = SUITES / "MANIFEST.json"
    if not man.exists():
        print("FAIL: no manifest")
        return 1
    body = json.loads(man.read_text())
    ok = canonical_sha(body) == body["suite_sha256"]
    hold = SUITES / "holdout"
    try:
        next(iter(hold.iterdir()))  # iterdir is lazy: the PermissionError
        locked = False               # fires on first next(), not on creation
    except PermissionError:
        locked = True
    except StopIteration:
        locked = False  # empty + readable == definitely not locked
    print(f"manifest sha ok={ok} holdout locked={locked} "
          f"counts={body['counts']}")
    return 0 if ok and locked else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return check() if args.check else freeze()


if __name__ == "__main__":
    sys.exit(main())
