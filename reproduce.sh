#!/usr/bin/env bash
# Reproduce the Adversarial Replication Flywheel campaign end-to-end.
#
# Costs: $0 on a cpu-class-only plan (mps.cpu). ~850 mps jobs, ~1 day of
# wall clock. Requires BLUEQUBIT_API_KEY_ACCOUNT_TEST (or any BlueQubit
# token) in ../.env — see OCT11-RUNBOOK.md for the personal-account rerun.
#
# The frozen suite is committed (suite/ minus the locked holdout, whose
# truths stay chmod-000 until the one-shot evaluation). Re-running this
# script builds a FRESH suite (new freeze) — to reproduce the shipped
# numbers exactly, keep the committed suite and start at step 2.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 0. environment + scientific core (no jobs) =="
.venv/bin/python -u src/validate_core.py

echo "== 1. freeze a fresh 48-circuit suite (local compute only, 0 jobs) =="
.venv/bin/python -u src/freeze_suite.py
.venv/bin/python -u src/freeze_suite.py --check

echo "== 2. G3 baseline (val x2 + train + chi sweep; ~84 mps jobs) =="
.venv/bin/python -u src/harness.py baseline

echo "== 3. G4 flywheel + equal-budget no-memory control (10 + 10 rounds) =="
for k in 1 2 3 4 5 6 7 8 9 10; do
  .venv/bin/python -u src/harness.py round --k "$k"
  .venv/bin/python -u src/harness.py round --k "$k" --control
  if [ "$k" = "6" ] || [ "$k" = "10" ]; then
    .venv/bin/python -u src/harness.py canary --k "$k"
  fi
done

echo "== 4. G6 one-shot locked holdout (WRITES THE SENTINEL — once ever) =="
.venv/bin/python -u src/holdout_eval.py

echo "== 5. G7 report + claims ledger + job export =="
.venv/bin/python -u src/report.py
.venv/bin/python tools/rsi.py verify

echo "Done: runs/report/report.md"
