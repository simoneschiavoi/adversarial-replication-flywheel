"""One-shot recovery for control r1 (EXP-006-R01), 2026-10-06.

cmd_round crashed AFTER `ledger record` and AFTER the acceptance decision but
BEFORE `ledger promote` (argparse attr bug: cmd_promote read args.run_dir but
the parser defines --run; fixed in tools/ledger.py the same day). The promote
has since been completed by hand against the recorded, gate-passing run:
    ledger.py promote EXP-006-R01 --run runs/flywheel/20261006T084042Z_r1_control

This script redoes ONLY the in-memory state mutations that cmd_round performs
after a successful promote (control arm branch): rebuild cfg via
apply_mutation, swap control_incumbent, append the history row, save_state.
No jobs are dispatched, no metrics are touched.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from harness import apply_mutation, load_state, save_state, utcnow  # noqa: E402

EXP_ID = "EXP-006-R01"
RUN_DIR = ROOT / "runs/flywheel/20261006T084042Z_r1_control"


def main() -> int:
    state = load_state()
    if any(h["round"] == 1 and h["arm"] == "control" for h in state["history"]):
        print("already recovered — nothing to do")
        return 0
    m = json.loads((RUN_DIR / "metrics.json").read_text())
    assert m["arm"] == "control" and m["round"] == 1 and m["accepted"] is True

    cfg = apply_mutation(state["control_incumbent"]["config"], m["mutation"])
    assert cfg["name"] == f"chi-{m['mutation']['value']}"
    state["control_incumbent"] = {
        "config": cfg,
        "mean_xeb": m["val"]["mean_xeb"],
        "val_rows": m["val"]["rows"],
        "cost_min": m["val"]["cost_min"],
    }
    state["history"].append({
        "round": 1, "arm": "control", "exp_id": EXP_ID,
        "mutation": m["mutation"], "config": cfg["name"],
        "chi_alloc": cfg["chi_alloc"], "shots_alloc": cfg["shots_alloc"],
        "permutation_seed": cfg["permutation_seed"],
        "accepted": True, "mean_delta": m["mean_delta"],
        "ci_low": m["ci_low"], "ci_high": m["ci_high"],
        "val_mean_xeb": m["val"]["mean_xeb"], "cost_min": m["val"]["cost_min"],
        "run_dir": str(RUN_DIR.relative_to(ROOT)), "at": utcnow(),
    })
    save_state(state)
    print(f"OK recovered {EXP_ID}: control_incumbent -> {cfg['name']} "
          f"mean_xeb={m['val']['mean_xeb']:.5f} history rows="
          f"{len(state['history'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
