"""Build a self-contained, hash-verified data bundle for the notebooks.

Copies (byte-for-byte, no transformation) the reviewable evidence of one
campaign tree into notebooks/data/<label>/, mirroring the tree's relative
paths, and writes PROVENANCE.json with the source path, size and sha256 of
every copied file.

Why a bundle: the public repository's .gitignore keeps the per-round run
directories (runs/flywheel/*) and EXP-008 payloads local, but the audit
notebooks need the per-circuit rows inside them. The ledger pinned the sha256
of every recorded run's metrics.json at record time, so the notebooks can
prove these copies are the exact files the ledger accepted.

Usage:
    python tools/build_bundle.py --tree ../prototype --label test-campaign
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
NB_ROOT = HERE.parent

STATIC = [
    "runs/report/summary.json",
    "runs/report/rounds.json",
    "runs/report/claims.json",
    "runs/report/jobs_export.csv",
    "runs/flywheel/state.json",
    "ledger/experiments.json",
    "researcher/PREDICTIONS.jsonl",
    "experiments/EXP-008-GATE-CALIBRATION/data/analysis.json",
    "suite/MANIFEST.json",
]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, help="campaign tree (e.g. ../prototype)")
    ap.add_argument("--label", required=True, help="bundle name under notebooks/data/")
    ap.add_argument("--max-file-mb", type=float, default=2.0)
    args = ap.parse_args()

    tree = pathlib.Path(args.tree).resolve()
    out = NB_ROOT / "data" / args.label
    ledger = json.loads((tree / "ledger/experiments.json").read_text())["experiments"]

    wanted = list(STATIC)
    # every recorded attempt's metrics.json (the file whose sha the ledger pinned)
    for exp in ledger.values():
        for att in exp.get("attempts", []):
            wanted.append(f"{att['run_dir']}/metrics.json")
        # SPEC + PREREGISTRATION (hash-pinned at registration)
        spec = exp.get("spec_path")
        if spec:
            wanted.append(spec)
            prereg = str(pathlib.Path(spec).parent / "PREREGISTRATION.json")
            wanted.append(prereg)

    if out.exists():
        shutil.rmtree(out)
    files = []
    skipped = []
    for rel in dict.fromkeys(wanted):  # de-dup, keep order
        src = tree / rel
        if not src.is_file():
            skipped.append({"path": rel, "reason": "missing in tree"})
            continue
        size = src.stat().st_size
        if size > args.max_file_mb * 1e6:
            skipped.append({"path": rel, "reason": f"larger than {args.max_file_mb} MB ({size} B)"})
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        h_src, h_dst = sha256(src), sha256(dst)
        assert h_src == h_dst, rel
        files.append({"path": rel, "bytes": size, "sha256": h_src})

    prov = {
        "label": args.label,
        "source_tree": tree.name,
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "builder": "notebooks/tools/build_bundle.py",
        "builder_sha256": sha256(pathlib.Path(__file__)),
        "n_files": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
        "skipped": skipped,
    }
    (out / "PROVENANCE.json").write_text(json.dumps(prov, indent=1) + "\n")
    print(f"bundle {out.relative_to(NB_ROOT)}: {len(files)} files, "
          f"{prov['total_bytes'] / 1e6:.2f} MB; skipped {len(skipped)}")
    for s in skipped:
        print("  skipped:", s["path"], "-", s["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
