"""G1 amendment — rescore the mps lane with canonical (un-reversed) count keys.

The original scoring consumed mps.cpu count keys as-is; they are bit-reversed
relative to the cpu device / qiskit display order (evidence: n=20 d=4 circuit
rcs_n20_d4_s20263010, job <mps64_job_id>: normalized XEB same-order=-0.0329,
reversed-keys=+1.0248). This script refetches counts for every mps64 job from
the server (no new jobs), rescores with canonical_counts, rewrites metrics.json
with an explicit amendment block, and regenerates the plot.

Legal because EXP-001 has NOT been ledger-recorded yet (record() pins bytes;
we amend before the pin, and the amendment itself is recorded in the file).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

RUN_DIR = ROOT / "runs" / "20261006T025115Z_g1"


def main() -> int:
    from bq import get_client
    from metrics import xeb_normalized, xeb_linear, canonical_counts
    import numpy as np

    client = get_client()
    m_path = RUN_DIR / "metrics.json"
    m = json.loads(m_path.read_text())
    changed = 0
    for r in m["rows"]:
        jr = client.get(r["mps64_job_id"])
        raw = jr.get_counts()
        counts = canonical_counts(raw, "mps.cpu")
        p = np.load(r["prob"], mmap_mode="r")
        idx = np.fromiter((int(b, 2) for b in counts), dtype=np.int64)
        w = np.fromiter(counts.values(), dtype=np.float64)
        q = np.asarray(p, dtype=np.float64)[idx]
        n = r["n"]
        p64 = np.asarray(p, dtype=np.float64)
        const = float(2**n * float(np.dot(p64, p64)) - 1.0)
        raw_xeb = float(2**n * np.dot(w, q) / w.sum() - 1.0)
        r["mps64_xeb"] = raw_xeb / const
        r["mps64_xeb_raw"] = raw_xeb
        changed += 1
    m["amendments"] = [{
        "what": "mps64 lane rescored with canonical (un-reversed) count keys",
        "why": "mps.cpu returns count keys bit-reversed vs cpu device; original "
               "scoring consumed them as-is, giving XEB~0 artifacts",
        "evidence": "n=20 d=4 rcs_n20_d4_s20263010: same-order=-0.0329, "
                    "reversed=+1.0248 (normalized XEB)",
        "no_new_jobs": True,
        "refetched_counts_from_job_ids": True,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rows_rescored": changed,
    }]
    m_path.write_text(json.dumps(m, indent=2))
    # summary by (n, depth)
    print(f"rescored {changed} rows")
    for n in (20, 24, 26):
        vals = [r["mps64_xeb"] for r in m["rows"] if r["n"] == n]
        print(f"  n={n}: " + " ".join(f"{v:+.3f}" for v in vals))

    # regenerate plot
    from plots import g1_plot
    g1_plot(m["rows"], RUN_DIR / "xeb_vs_depth.png")
    print("plot regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
